# Jarvis — doble aplauso → acciones (Linux Mint / Cinnamon / X11)

Escucha el micrófono y, cuando detecta un **doble aplauso**, corre una lista de
**acciones que vos definís en `config.toml`**: abrir un navegador en una URL,
lanzar apps, enfocar ventanas, repartirlas por workspaces, poner música de fondo
y reproducir un mensaje de bienvenida.

No hay nada hardcodeado sobre *qué* se abre: el detector solo escucha, y todo el
"qué hace" vive en el TOML. El diseño y las decisiones están en `SPEC.md`.

---

## Arranque rápido

Cinco pasos, unos 10 minutos. El detalle de cada uno está más abajo.

### 0. Verificá que tu sistema sirve (30 segundos)

```bash
echo $XDG_SESSION_TYPE   # tiene que decir "x11" — en Wayland no se mueven las ventanas
python3 --version        # tiene que ser 3.11 o mayor
```

Si `$XDG_SESSION_TYPE` dice `wayland`, cerrá sesión y elegí la sesión **X11** en
la pantalla de login (en Mint, "Cinnamon" a secas suele ser X11). El resto del
proyecto funciona igual, pero `workspace`, `fullscreen` y `activate` no van a
hacer nada.

### 1. Instalá lo que hace falta

```bash
sudo apt install python3-venv wmctrl ffmpeg vlc
```

`wmctrl` mueve ventanas, `ffmpeg` y `vlc` reproducen audio. Sin `wmctrl` el
proyecto arranca pero no ubica ventanas.

### 2. Preparate el entorno

```bash
git clone <URL-DEL-REPO> jarvis && cd jarvis
python3 -m venv .venv
source .venv/bin/activate        # repetí esto en cada terminal nueva
pip install -r requirements.txt
```

### 3. Creá tu config

```bash
cp config.example.toml config.toml
```

**Este es el único archivo que vas a editar.** Está en el `.gitignore`, así que
tus URLs y tus apps no se suben a ningún lado.

### 4. Poné tus audios (opcional)

```bash
cp ~/alguna-cancion.mp3    assets/music/
cp ~/algun-mensaje.mp3     assets/welcome/
```

No vienen incluidos por peso y derechos de autor. Si dejás las carpetas vacías,
las acciones `music` y `welcome` avisan por log y el resto funciona igual.

### 5. Probá

```bash
python diagnostico.py     # ¿te escucha el micrófono? aplaudí y mirá los SPIKE
python jarvis.py          # el programa de verdad — aplaudí dos veces
```

---

## Qué tocar en `config.toml`

Todo lo que vas a cambiar está en dos lugares del archivo:

**1. Las apps que se abren** — los bloques `[[actions]]`. La plantilla trae un
ejemplo genérico (`example.com`, `xterm`); reemplazalo por lo tuyo:

```toml
[[actions]]
type = "open_url"
url = "https://TU-SITIO.com"     # ← tu URL
new_window = true
workspace = 1                     # ← en qué escritorio virtual cae

[[actions]]
type = "run"
cmd = ["TU-APP"]                  # ← el ejecutable (probalo en la terminal primero)
match = "TU-APP"                  # ← cómo reconocer su ventana (wmctrl -lx)
workspace = 2
```

Los tres comandos que necesitás para completar eso:

| Para saber… | Corré |
| ----------- | ----- |
| cómo se llama el ejecutable de una app | `which <nombre>` |
| qué poner en `match` | `wmctrl -lx` con la app abierta |
| cuántos workspaces tenés | `wmctrl -d` |

**2. La sensibilidad del detector** — la sección `[detector]`. Solo si dispara
solo (subí `spike_ratio`) o si no te escucha (bajalo). Usá `diagnostico.py` para
ajustarlo sin abrir nada.

Guía completa de ventanas y workspaces: **[`CONFIGURACION.md`](CONFIGURACION.md)**.

---

## Requisitos

| Requisito | Por qué | Cómo verificar |
| --------- | ------- | -------------- |
| **X11** (no Wayland) | El manejo de ventanas usa `wmctrl`, que habla EWMH sobre X11. | `echo $XDG_SESSION_TYPE` → debe decir `x11` |
| **Window manager EWMH** (Cinnamon/Muffin, probado; XFCE, MATE y KDE-X11 deberían andar) | Mover ventanas entre workspaces y fullscreen. | `echo $XDG_CURRENT_DESKTOP` |
| **Python 3.11+** | Usa `tomllib`, que entró en 3.11. | `python3 --version` |
| **Servidor de audio** (PipeWire, PulseAudio o ALSA a secas) | PortAudio lee el micrófono a través de él. | `python3 -c "import sounddevice as sd; print(sd.query_devices())"` (después del setup) |

> **Wayland:** `wmctrl` no funciona ahí. La detección de aplausos y el audio sí,
> pero `workspace`, `fullscreen` y `activate` van a quedar sin efecto (el
> programa avisa por log y sigue). En Mint, la sesión "Cinnamon" por defecto es
> X11; si estás en Wayland, elegí la sesión X11 en la pantalla de login.

## Piezas

| Archivo                | Qué hace                                                     |
| ---------------------- | ------------------------------------------------------------ |
| `config.example.toml`  | Plantilla versionada. Copiala a `config.toml`.               |
| `config.toml`          | **Lo que vas a editar**: tus perillas y tus acciones. No se sube al repo. |
| `CONFIGURACION.md`     | Cómo mapear tus apps a workspaces (`match`, `wmctrl`, timing). |
| `jarvis.py`         | Entry point: lee el config y conecta detector con acciones.     |
| `clap_detector.py`  | Detecta el doble aplauso (mic + RMS). No sabe qué dispara.      |
| `actions.py`        | Ejecuta las acciones con `wmctrl` (ventanas/workspaces).        |
| `audio.py`          | Música de fondo y mensaje de bienvenida (VLC / ffplay).         |
| `diagnostico.py`    | Tunea el detector sin abrir nada (ver "Tuning").                |
| `assets/music/`     | Canciones de fondo; se elige una al azar en cada arranque.      |
| `assets/welcome/`   | Mensajes de bienvenida; se elige uno al azar.                   |
| `docker/`           | Entorno de verificación en limpio (ver "Verificar en limpio").  |
| `SPEC.md`           | Especificación técnica: arquitectura y decisiones de diseño.    |

## Sobre el setup

(Los comandos están en el **Arranque rápido**, arriba. Acá va el porqué.)

`config.toml` está en el `.gitignore`: es tuyo (tus apps, tus URLs, tus
workspaces) y no se sube al repo. Lo que se versiona es `config.example.toml`.
Editá **el primero**; si rompés algo, siempre podés volver a copiar la plantilla.

Todas las rutas del proyecto se resuelven **relativas al propio script**
(`Path(__file__)`), así que podés clonarlo en cualquier carpeta y moverlo
después sin tocar nada.

Qué aporta cada paquete de sistema:

- **`wmctrl`** — mueve ventanas entre workspaces y las pone en fullscreen.
- **`ffmpeg`** (su `ffplay`) — reproduce el mensaje de bienvenida sin ventana.
- **`vlc`** — toca la música de fondo con una ventana que podés cerrar a mano.
- **`libportaudio2`** — lo usa `sounddevice` para leer el micrófono. En Mint ya
  suele venir instalado; si `import sounddevice` falla, instalalo con
  `sudo apt install libportaudio2`.

Los reproductores se buscan en tiempo de ejecución con `shutil.which`: si te
falta `vlc`, el audio cae a `ffplay` y viceversa. Solo se pierde la parte de
audio que dependa del que falte, el resto sigue andando.

> `xdotool` **no** hace falta. El fullscreen se hace por EWMH con `wmctrl`.

## Audio de ejemplo (no viene incluido)

`assets/music/` y `assets/welcome/` se versionan **vacías** (solo su README):
los audios son pesados y suelen tener derechos de autor de terceros. Poné los
tuyos ahí antes del primer uso:

```bash
cp ~/mi-cancion.mp3        assets/music/
cp ~/mi-bienvenida.mp3     assets/welcome/
```

Extensiones soportadas: `.mp3`, `.wav`, `.ogg`, `.oga`, `.flac`, `.m4a`,
`.opus`. Las carpetas se escanean en cada arranque (subcarpetas incluidas), así
que podés agregar, borrar o renombrar libremente. Si están vacías, las acciones
`music` y `welcome` avisan por log y el resto del flujo sigue igual.

Para generar mensajes de bienvenida propios sirve cualquier TTS local
(`espeak-ng`, `piper`) o el que prefieras — es solo un archivo de audio.

## Correr

```bash
cd /ruta/a/jarvis
source .venv/bin/activate
python jarvis.py
```

Aplaudí dos veces. Cortá con **Ctrl+C**. Para usar otro archivo de config:
`python jarvis.py mi_config.toml`.

## Editar las acciones

Todo vive en `config.toml`. Cada bloque `[[actions]]` es un paso y se ejecutan
**en orden**.

> El flujo que trae la plantilla es una **demo de las piezas**, no una receta:
> música de fondo, una URL en el workspace 1, una app en el 2 y un mensaje de
> bienvenida. Cambiá las URLs, los comandos y los workspaces por lo tuyo — no
> hace falta tocar Python.
>
> **Para mapear tus apps a workspaces, leé [`CONFIGURACION.md`](CONFIGURACION.md)**:
> cómo sacar el `match` de una ventana, cuántos workspaces tenés, y por qué a
> veces una ventana no se mueve.

Tipos de acción:

| `type`       | Parámetros                                                                  |
| ------------ | --------------------------------------------------------------------------- |
| `open_url`   | `url` (oblig.), `browser`, `new_window`, `workspace`, `fullscreen`          |
| `run`        | `cmd = [...]` (oblig.), `match`, `workspace`, `fullscreen`                   |
| `activate`   | `match` (oblig.), `launch = [...]`, `workspace`, `fullscreen`                |
| `wait`       | `seconds`                                                                    |
| `music`      | `folder`, `volume` (0-100), `include`, `gui`, `workspace`, `keep_on_exit`    |
| `welcome`    | `folder`, `volume`, `include`, `after_s`, `stop_music`                       |
| `stop_music` | (sin parámetros — corta la música de fondo)                                 |
| `say`        | (reservado — TTS local a futuro, ver `SPEC.md` §8; hoy no hace nada)         |

### Adaptarlo a tus apps

Los tres comandos que vas a necesitar (el detalle está en
[`CONFIGURACION.md`](CONFIGURACION.md)):

| Para saber… | Corré |
| ----------- | ----- |
| qué poner en `match` | `wmctrl -lx` (con la app abierta) |
| cuántos workspaces tenés | `wmctrl -d` — ojo: es 0-based, el config es 1-based |
| cómo se llama el ejecutable | `grep -h Exec /usr/share/applications/*.desktop \| grep -i <nombre>` |

**Otro navegador:** `browser = "brave"` es el default; si no encuentra el
ejecutable, cae al navegador por defecto del sistema. Para forzar otro, usá
`run` con el comando directo: `cmd = ["firefox", "--new-window", "https://..."]`.

### Música + bienvenida

El flujo del ejemplo: al doble aplauso arranca una canción al azar de
`assets/music/`, se abren las apps, y a los 30 s se reproduce un mensaje al azar
de `assets/welcome/` **por encima** de la música, que sigue hasta el final.

- **`after_s`** se cuenta *desde que arrancó la música*, no desde la acción
  anterior. Si abrir las apps ya tardó más que eso, no espera de más.
- **`gui = true`** abre VLC con ventana (va al `workspace` que le digas) para que
  puedas pausarlo o cerrarlo a mano. Con `false` suena sin ventana.
- **`keep_on_exit = true`** deja la canción sonando hasta el final aunque Jarvis
  ya se haya cerrado (con `run_once = true` eso pasa enseguida).
- **`stop_music = false`** en el `welcome` hace que la voz suene sobre la música;
  con `true` la corta antes de hablar.
- **`include`** filtra por un pedazo del nombre del archivo. Sirve para fijar el
  idioma si nombrás tus archivos con un prefijo consistente. Si preferís algo
  que no dependa de los nombres, armá subcarpetas y apuntá `folder` a una.

Notas:

- **`workspace` es 1-based**: `1` = el primer espacio (como los muestra
  Cinnamon). El programa lo convierte al índice interno de `wmctrl`.
- Para mover/fullscreen una app recién lanzada, el programa espera a que su
  ventana aparezca (hasta 15 s). Si tu máquina es lenta, subí el `wait` previo.

## Tuning del detector (sección `[detector]`)

| Perilla       | Efecto                                                            |
| ------------- | ----------------------------------------------------------------- |
| `spike_ratio` | Subí si hay falsos disparos; bajá si no detecta los aplausos.      |
| `cooldown_s`  | Tiempo mínimo entre dos disparos.                                 |
| `min_gap_s` / `max_gap_s` | Separación permitida entre los dos aplausos.          |
| `min_rms`     | Piso de volumen absoluto (subilo en salas muy silenciosas).       |
| `sample_rate` | Probá `48000` si tu placa no anda con `44100`.                    |
| `calibrate_s` | Segundos de calibración al arrancar. `0` lo desactiva.            |
| `run_once`    | `true` = dispara una vez y cierra; `false` = escucha para siempre. |

**Calibración:** al arrancar, Jarvis mide el ruido de tu sala 1 segundo (quedate
en silencio) y pone el umbral en `ruido × spike_ratio`. Así se adapta solo a un
ambiente ruidoso o silencioso. En el log vas a ver la línea
`Ruido ambiente = X -> umbral de aplauso = Y`: si el detector dispara solo, ese
umbral quedó bajo (subí `spike_ratio`); si no te escucha, quedó alto (bajalo).

**Modo diagnóstico** — la forma más rápida de calibrar, porque no abre nada:

```bash
python diagnostico.py        # escucha 15 segundos
python diagnostico.py 30     # escucha 30 segundos
```

Cada aplauso debería salir como `SPIKE` con un RMS bien por encima del umbral, y
en silencio no debería aparecer ninguno.

**Elegir micrófono:** por defecto se autodetecta el dispositivo que "escucha"
(útil con PipeWire, que expone varios). Para forzar uno, descomentá
`input_device` en el TOML — acepta un índice o parte del nombre. Listar
dispositivos:

```bash
python -c "import sounddevice as sd; print(sd.query_devices())"
```

## Problemas comunes

- **No reacciona a los aplausos:** bajá `spike_ratio` o aplaudí más cerca. Corré
  `diagnostico.py` para ver qué está midiendo el micrófono.
- **Se dispara solo:** subí `spike_ratio` o `cooldown_s`.
- **No mueve/enfoca ventanas:** confirmá que `wmctrl` está instalado
  (`which wmctrl`) y que estás en X11 (`echo $XDG_SESSION_TYPE`).
- **La ventana no va al workspace:** verificá que ese workspace exista
  (`wmctrl -d`) y recordá que la numeración del config es 1-based.
- **Error de PortAudio:** probá otro `sample_rate`, revisá que el micrófono no
  esté tomado por otra app, o reiniciá el servidor de audio
  (`systemctl --user restart pipewire`).
- **No suena nada:** revisá que haya archivos en `assets/music/` y
  `assets/welcome/`, y que `vlc` o `ffplay` estén instalados.

## Verificar en limpio

Para responder "¿esto anda en una máquina que no es la mía?" hay un entorno de
verificación en Docker. **No es para correr Jarvis** (el proyecto manipula tu
escritorio; el contenedor levanta uno propio con Xvfb + openbox): es para probar
que un clon fresco funciona partiendo de cero.

```bash
docker build -f docker/Dockerfile -t jarvis-verify .
docker run --rm jarvis-verify
```

Corre 36 verificaciones sobre el código real, sin tocar tu sesión:

| Qué verifica | Cómo |
| ------------ | ---- |
| El setup del README funciona en una base limpia | Ubuntu 24.04 (= Mint 22), `apt` + `venv` + `pip` desde cero |
| Un clon fresco explica qué hacer | Corre `jarvis.py` sin `config.toml` y revisa el mensaje |
| La plantilla es válida | Parsea `config.example.toml`; todos sus `type` y claves `[detector]` existen |
| **El placement de ventanas anda** | Lanza `xterm`, lo manda al workspace 2, y confirma con `wmctrl` que quedó ahí |
| La degradación es real | Simula que falta `wmctrl` y verifica que igual no rompe |
| El audio suena | Genera un WAV y lo reproduce contra un sink nulo de PulseAudio |
| **El detector detecta** | Sintetiza un doble aplauso, lo reproduce en el sink nulo y lo captura desde su `.monitor` con el detector real |
| **Los scripts corren de verdad** | Ejecuta `jarvis.py` como proceso: aplauso → acciones → salida limpia, con exit code 0. También `diagnostico.py` |

La última merece una nota: el `.monitor` de un sink nulo de PulseAudio es una
**fuente de captura**, así que lo que se reproduce ahí se puede grabar. Eso
permite alimentar a `clap_detector.py` sin micrófono. Se verifican los dos
sentidos: que un doble aplauso (gap 0.20 s) dispare el callback, y que **un
aplauso solo no lo dispare** — sin esta segunda, un detector que se disparara
con cualquier ruido pasaría la primera igual.

Lo que el contenedor **no** cubre: micrófono físico, el ruido y la acústica de
una sala real, y Cinnamon/Muffin en particular (el contenedor usa openbox). El
umbral adaptativo se ejercita, pero contra audio sintético limpio. Para cerrar
eso, la verificación manual es una VM de Mint + Cinnamon (con `virt-manager`)
con el micrófono pasado por USB, corriendo `python diagnostico.py`.

## Estado

Primera versión pública. Probado en Linux Mint con Cinnamon sobre X11 y
PipeWire; la instalación, el manejo de ventanas y el audio se verifican
automáticamente en contenedor (arriba). Reportes de otros WM/distros son
bienvenidos.

Los audios de `assets/` no se distribuyen con el repo (ver `.gitignore`).

## Licencia

MIT — ver [`LICENSE`](LICENSE).

Proyecto personal, publicado como documentación y para poder reutilizar el
código. **Sin soporte ni garantía**: usalo como referencia si te sirve.
