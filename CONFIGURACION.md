# Configuración — ventanas y workspaces

Guía para adaptar `config.toml` a **tu** máquina: qué apps abrís, en qué
workspace cae cada una y cómo hacer que el programa las encuentre.

Antes de empezar:

```bash
cp config.example.toml config.toml
```

`config.toml` está en el `.gitignore` — es tuyo y no se sube al repo. Editá ese
archivo, no la plantilla.

---

## 1. Cuántos workspaces tenés

```bash
wmctrl -d
```

Cada línea es un workspace. La `*` marca el actual:

```
0  * DG: 1920x1080  VP: 0,0  WA: 0,27 1920x1053  Workspace 1
1  - DG: 1920x1080  VP: 0,0  WA: 0,27 1920x1053  Workspace 2
2  - DG: 1920x1080  VP: 0,0  WA: 0,27 1920x1053  Workspace 3
```

> **Importante:** `wmctrl` numera desde **0**, pero en `config.toml` el campo
> `workspace` es **1-based** (`1` = el primer espacio, como lo muestra Cinnamon).
> El programa hace la conversión. Si en `wmctrl -d` ves 3 líneas, los valores
> válidos en el config son `1`, `2` y `3`.

**Agregar workspaces en Cinnamon:** Configuración → Preferencias → Espacios de
trabajo, o `Ctrl+Alt+↑` para abrir el selector y usar el `+`. Si apuntás a un
workspace que no existe, la ventana se queda donde está y el log lo avisa.

---

## 2. Encontrar el `match` de una ventana

`match` es cómo el programa reconoce la ventana de una app: busca ese texto
dentro de la **WM_CLASS** y del **título**, sin distinguir mayúsculas.

Abrí la app a mano y corré:

```bash
wmctrl -lx
```

```
0x04000007  0 Navigator.brave-browser  mi-pc  Example Domain — Brave
0x05200003  1 spotify.Spotify          mi-pc  Spotify Premium
                ^^^^^^^^^^^^^^^^
                esta es la WM_CLASS
```

De ahí sale el `match`. Usá el pedazo más estable y distintivo:

```toml
match = "spotify"       # anda: aparece en la WM_CLASS
match = "brave"         # anda: parte de "Navigator.brave-browser"
match = "Premium"       # frágil: es parte del título, cambia solo
```

Elegí siempre la clase antes que el título — el título cambia con la pestaña
abierta, la canción que suena o el archivo que estás editando.

---

## 3. Encontrar el ejecutable de una app

Para `run` y `activate.launch` necesitás el comando real:

```bash
grep -h Exec /usr/share/applications/*.desktop ~/.local/share/applications/*.desktop 2>/dev/null | grep -i <nombre>
```

También sirve `which <nombre>` si ya sabés cómo se llama. Probá el comando suelto
en la terminal antes de ponerlo en el config: si no abre ahí, tampoco va a abrir
desde Jarvis.

En `cmd` va como lista, programa y argumentos por separado:

```toml
cmd = ["firefox", "--new-window", "https://example.com"]   # bien
cmd = ["firefox --new-window https://example.com"]         # mal (no es una shell)
```

---

## 4. Los tres patrones que vas a usar

### Abrir una URL en un workspace

```toml
[[actions]]
type = "open_url"
url = "https://example.com"
browser = "brave"      # opcional; si no lo encuentra, usa el navegador por defecto
new_window = true      # ventana nueva en vez de pestaña — necesario para
                       # poder mandarla a un workspace propio
workspace = 1
fullscreen = false
```

Con `new_window = false` la URL cae como pestaña en una ventana existente, y
entonces `workspace` mueve **esa** ventana entera. Casi siempre querés `true`.

### Lanzar una app y mandarla a un workspace

```toml
[[actions]]
type = "run"
cmd = ["spotify"]
match = "spotify"      # sin esto no sabe qué ventana mover
workspace = 2
fullscreen = false
```

Sin `match` la app se lanza igual, pero queda donde el WM la ponga.

### Enfocar algo que quizá ya está abierto

```toml
[[actions]]
type = "activate"
match = "code"
launch = ["code"]      # opcional: si no la encuentra abierta, la lanza
workspace = 2
```

Es el más amable para apps pesadas: no abre una segunda instancia si ya la
tenías corriendo.

---

## 5. Timing: por qué a veces la ventana no se mueve

Una app recién lanzada tarda en mapear su ventana. El programa saca una foto de
las ventanas existentes, lanza la app y **espera hasta 15 s** a que aparezca una
nueva que matchee. Si no aparece en ese plazo, sigue con la acción siguiente y
lo avisa por log.

Si tu máquina es lenta o la app es pesada, metele aire entre pasos:

```toml
[[actions]]
type = "wait"
seconds = 2.0
```

Otro motivo frecuente de "no se movió": el `match` no coincide con nada. Volvé al
punto 2 y verificá con `wmctrl -lx` **con la app abierta**.

---

## 6. Un ejemplo completo

Navegador en el workspace 1, editor en el 2, música en el 3:

```toml
[[actions]]
type = "music"
folder = "assets/music"
volume = 35
gui = true
workspace = 3
keep_on_exit = true

[[actions]]
type = "open_url"
url = "https://example.com"
new_window = true
workspace = 1

[[actions]]
type = "wait"
seconds = 1.5

[[actions]]
type = "activate"
match = "code"
launch = ["code"]
workspace = 2
fullscreen = true
```

Consejo: armalo **de a una acción por vez**. Agregás un bloque, corrés
`python jarvis.py`, aplaudís, y verificás que haya hecho lo que esperabas antes
de sumar el siguiente. Depurar cinco acciones nuevas juntas es mucho peor.

---

## 7. Si nada de esto funciona

- **`wmctrl: command not found`** → `sudo apt install wmctrl`.
- **`echo $XDG_SESSION_TYPE` dice `wayland`** → `wmctrl` no funciona ahí. Los
  aplausos y el audio andan, pero `workspace`, `fullscreen` y `activate` no
  hacen nada. Cambiá a la sesión X11 desde la pantalla de login.
- **La ventana aparece pero en el workspace equivocado** → acordate del off-by-one:
  el config es 1-based, `wmctrl -d` es 0-based.
- **Querés probar el detector sin abrir nada** → `python diagnostico.py`.
