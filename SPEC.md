# Especificación técnica — Jarvis

Detector de doble aplauso que dispara una secuencia de acciones de escritorio
configurable, para Linux con X11.

Este documento describe **cómo está construido** el proyecto y por qué. Para
instalarlo y usarlo, ver `README.md`; para configurar workspaces y ventanas, ver
`CONFIGURACION.md`.

---

## 1. Alcance

**Objetivo:** que un doble aplauso ejecute una secuencia de acciones definida por
el usuario en un archivo de texto, sin tocar código.

**Principio de diseño central:** el detector no sabe qué dispara. Detecta un
evento y llama a un callback. Todo el "qué hace" vive en `config.toml`. Esto
mantiene la lógica de audio independiente del sistema operativo y hace que
cambiar el comportamiento no requiera Python.

**Entorno soportado:**

| Componente | Requisito | Motivo |
| ---------- | --------- | ------ |
| Servidor gráfico | X11 | `wmctrl` habla EWMH sobre X11 |
| Window manager | Cualquiera con soporte EWMH (probado en Cinnamon/Muffin) | Mover ventanas, fullscreen |
| Python | 3.11+ | `tomllib` en la stdlib |
| Audio de entrada | PipeWire, PulseAudio o ALSA | PortAudio lee el micrófono a través de ellos |

En Wayland el proyecto arranca y detecta aplausos, pero las operaciones de
ventana (`workspace`, `fullscreen`, `activate`) no tienen efecto: `wmctrl` no
funciona ahí. La degradación es explícita — se avisa por log y la ejecución
continúa.

---

## 2. Arquitectura

Cinco módulos con una responsabilidad cada uno:

```
jarvis.py           Entry point. Carga el TOML, arma el DetectorConfig,
                    conecta el callback. No contiene lógica de negocio.
clap_detector.py    Captura de micrófono y detección del doble aplauso.
                    Sin dependencias de SO ni conocimiento de acciones.
actions.py          Intérprete de la lista [[actions]]. Manejo de ventanas
                    vía wmctrl.
audio.py            Reproducción de música y mensajes vía reproductores
                    de línea de comandos externos.
diagnostico.py      Herramienta de calibración: corre el detector e imprime
                    lo que mide, sin ejecutar ninguna acción.
```

**Dependencia unidireccional:** `jarvis.py` → {`clap_detector`, `actions`} →
`audio`. El detector no importa `actions`; se comunican solo por el callback que
recibe `listen()`. Un cambio en los tipos de acción nunca toca el detector.

**Dependencias de Python:** solo `numpy` y `sounddevice`. Todo lo demás
(manejo de ventanas, reproducción de audio) se delega a binarios del sistema
invocados por `subprocess`, resueltos en tiempo de ejecución con `shutil.which`.
Se eligió así sobre bindings de Python porque los comandos son inspeccionables a
mano en la terminal, no requieren compilación y no se rompen al actualizar el
sistema.

---

## 3. Detección del doble aplauso

Opera sobre el RMS (nivel de volumen) de bloques de ~40 ms leídos con
`sounddevice`/PortAudio.

### 3.1 Umbral adaptativo

El umbral no es absoluto sino **relativo al ruido de la sala**:

```
umbral = max(piso_de_ruido × spike_ratio, min_rms)
```

El piso de ruido es un promedio móvil exponencial (`noise_floor_alpha`, por
defecto 0.992) que **solo se actualiza cuando el nivel está por debajo del
umbral**. Esa condición es la que evita que un aplauso contamine su propia
referencia, permitiendo a la vez que el piso suba y baje si el ambiente cambia
(un ventilador que arranca, una ventana que se abre).

`min_rms` actúa como piso absoluto: en una sala muy silenciosa impide que el
umbral caiga tanto que cualquier ruido lo cruce.

### 3.2 Calibración inicial

Al arrancar se mide el ambiente durante `calibrate_s` segundos y el piso arranca
en ese valor en vez de una constante.

Se usa la **mediana** de las mediciones, no el promedio: un ruido puntual
durante la calibración (una tos, una puerta) desplazaría el promedio y dejaría
el umbral demasiado alto por el resto de la sesión.

Sin esta calibración el piso arrancaba en un valor fijo bajo y, dado que solo
se actualiza por debajo del umbral, en una sala con ruido nunca podía alcanzar
el nivel real: el umbral quedaba pegado a `min_rms` y el detector disparaba
solo. La calibración es la corrección de ese comportamiento.

### 3.3 Máquina de estados

Un aplauso es un cruce de umbral. Dos aplausos forman un evento si:

1. El detector está **armado**. Tras un pico se desarma, y solo se rearma cuando
   el nivel cae por debajo de `umbral × retrigger_ratio`. Esto impide que un
   único aplauso con cola larga se cuente como dos.
2. La separación entre picos cae en `[min_gap_s, max_gap_s]` (0.05–0.35 s).
   Por debajo se descarta como el mismo aplauso; por encima, el segundo pico
   pasa a ser el "primero" de un intento nuevo.
3. Pasó al menos `cooldown_s` desde el último disparo (antirrebote).

### 3.4 Selección de micrófono

PipeWire expone varios dispositivos de entrada y el default del sistema no
siempre es el que tiene señal. La resolución es, en orden:

1. `input_device` del config o la variable de entorno `JARVIS_INPUT_DEVICE`
   (índice numérico o substring del nombre). Si está seteado y no resuelve, es
   un error fatal — un override explícito que falla no debe caer a otro
   dispositivo en silencio.
2. El default del sistema, si al sondearlo `input_probe_s` segundos supera
   `input_silent_rms`.
3. El dispositivo de entrada con mayor pico en el sondeo.
4. El default o el primer input disponible, con advertencia.

### 3.5 Modo de ejecución

`run_once = true` (default): al primer doble aplauso se ejecutan las acciones
**de forma bloqueante** y el proceso termina. Bloqueante es deliberado: el
placement de ventanas debe completarse antes de salir. Las apps lanzadas son
procesos independientes y sobreviven.

`run_once = false`: el detector sigue escuchando y cada disparo corre las
acciones en un hilo daemon aparte, para que un `wait` largo no interrumpa la
captura de audio.

---

## 4. Manejo de ventanas

Todo vía `wmctrl`. Con un solo monitor, la distribución espacial se hace por
**workspaces** en vez de por pantallas.

| Operación | Comando |
| --------- | ------- |
| Listar ventanas con clase | `wmctrl -lx` |
| Mover a workspace | `wmctrl -i -r <id> -t <N>` |
| Activar por clase | `wmctrl -x -a <clase>` |
| Fullscreen | `wmctrl -i -r <id> -b add,fullscreen` |

El fullscreen se hace por EWMH, no simulando la tecla F11 — Cinnamon/Muffin
sobre X11 lo soporta nativamente. Por eso `xdotool` no es una dependencia; solo
haría falta si en el futuro se agregan acciones que envíen teclas.

### 4.1 Numeración de workspaces

`wmctrl` numera desde 0. El config usa **1-based** para coincidir con lo que
muestra Cinnamon, y la conversión se hace en `_move_to_workspace`. Un valor
menor a 1 se rechaza con advertencia.

### 4.2 Espera de ventanas nuevas

Una app recién lanzada no tiene ventana inmediatamente. El procedimiento es:

1. Capturar el conjunto de IDs de ventana existentes.
2. Lanzar el proceso.
3. Sondear cada 150 ms hasta 15 s buscando un ID nuevo que además cumpla el
   `match` si está definido.
4. Aplicar workspace y/o fullscreen.

Si la ventana no aparece dentro del timeout se registra la advertencia y se
continúa con la acción siguiente. **La espera solo ocurre si la acción pide
`workspace` o `fullscreen`**; sin eso no hay motivo para bloquear.

El `match` compara contra la WM_CLASS y el título, sin distinguir mayúsculas. Se
recomienda la clase: el título cambia con el contenido.

---

## 5. Configuración

`config.toml`, ubicado junto a los scripts salvo que se pase otra ruta como
argumento. Se distribuye `config.example.toml` como plantilla; la copia personal
está en `.gitignore`.

TOML se eligió por ser editable sin conocer Python y estar en la stdlib desde
3.11 (`tomllib`), sin dependencias adicionales.

### 5.1 Sección `[detector]`

Mapea directamente a los campos del dataclass `DetectorConfig`. El cargador
copia solo las claves que el dataclass conoce y **advierte sobre las
desconocidas en vez de fallar**: un typo no debe impedir el arranque.

### 5.2 Lista `[[actions]]`

Array de tablas TOML, ejecutado en orden. Cada entrada tiene un `type` y sus
parámetros.

| `type` | Función | Parámetros |
| ------ | ------- | ---------- |
| `run` | Lanza un programa. Escape hatch general. | `cmd` (req.), `match`, `workspace`, `fullscreen` |
| `open_url` | Abre una URL en un navegador. | `url` (req.), `browser`, `new_window`, `workspace`, `fullscreen` |
| `activate` | Enfoca una ventana existente; la lanza si no está. | `match` (req.), `launch`, `workspace`, `fullscreen` |
| `wait` | Pausa entre acciones. | `seconds` |
| `music` | Música de fondo, archivo al azar de una carpeta. | `folder`, `volume`, `include`, `gui`, `workspace`, `keep_on_exit` |
| `welcome` | Mensaje que bloquea hasta terminar. | `folder`, `volume`, `include`, `after_s`, `stop_music` |
| `stop_music` | Corta la música de fondo. | — |
| `say` | Reservado para TTS. Sin implementar (§8). | `text` |

Las rutas relativas (`folder`) se resuelven contra el directorio del proyecto,
no contra el working directory, para que el comportamiento no dependa de desde
dónde se invoque.

### 5.3 Manejo de errores

Cada acción corre en su propio `try/except`: **una acción que falla no detiene
las restantes**. Un `type` desconocido o un parámetro obligatorio ausente
produce una advertencia identificando el número de acción, no una excepción.

El criterio general es degradar antes que abortar. Falta `wmctrl` → las apps se
abren igual, sin placement. Falta un reproductor → las apps se abren igual, sin
audio. Carpeta de audio vacía → el resto del flujo sigue.

---

## 6. Audio

Sin librerías de Python: se delega en reproductores de línea de comandos, con
fallback entre ellos.

| Modo | Reproductor | Comportamiento |
| ---- | ----------- | -------------- |
| Fondo, `gui = true` | `vlc` | Ventana visible, ubicable en un workspace, cerrable a mano |
| Fondo, `gui = false` | `ffplay`, o `cvlc` | Sin ventana |
| Bloqueante (`welcome`) | `ffplay`, o `cvlc` | Siempre sin ventana; timeout de 120 s |

`--qt-start-minimized` no se usa en el modo GUI: en Cinnamon manda VLC a la
bandeja del sistema y desaparece de la barra de tareas, que es lo contrario de
lo buscado. La ubicación de la ventana la resuelve `actions.py` por workspace.

**`after_s` de `welcome`** se mide desde que arrancó la música, no desde la
acción anterior. Si abrir las apps ya consumió más tiempo que `after_s`, no se
espera de más. Esto hace que el punto de reproducción del mensaje sea estable
frente a máquinas de distinta velocidad.

**`keep_on_exit`** determina qué pasa al terminar el proceso: con `true` la
música queda sonando (el reproductor es un proceso independiente que termina
solo al acabar el archivo), con `false` se corta en el handler de `atexit`. Es
relevante porque bajo `run_once` el proceso termina a los pocos segundos del
aplauso.

---

## 7. Formato de assets

`assets/music/` y `assets/welcome/`. Se escanean recursivamente en cada
ejecución y se elige un archivo al azar; `include` filtra por substring del
nombre.

Extensiones: `.mp3`, `.wav`, `.ogg`, `.oga`, `.flac`, `.m4a`, `.opus`.

El contenido no se versiona (`.gitignore`): son archivos pesados y típicamente
con derechos de terceros. Se versiona la estructura de carpetas y su README.

---

## 8. Fuera de alcance

Decisiones explícitas de **no** implementar, con su motivo:

- **TTS.** El tipo `say` está definido en el intérprete y documentado, pero solo
  registra un log. La implementación prevista es un motor **local y open source**
  (Piper), no un servicio en la nube, para no introducir dependencias de red,
  credenciales ni costos. Los mensajes de bienvenida se resuelven mientras tanto
  con archivos de audio pregrabados.
- **Control fino de reproductores** vía DBus o `spotifyd`. Las apps se lanzan y
  se ubican; su estado interno no se manipula.
- **Autostart / servicio de systemd.** El proyecto se invoca a mano. Agregar un
  `.desktop` en autostart es trivial si se necesita.
- **GUI de configuración.** El TOML comentado cumple la función.
- **Soporte de Wayland.** Requeriría un backend distinto al de `wmctrl` (por
  ejemplo protocolos específicos del compositor), sin equivalente portable.
- **Múltiples monitores.** El diseño reparte por workspaces. Distribuir por
  pantallas requeriría geometría vía `xrandr`.
