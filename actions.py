#!/usr/bin/env python3
"""
Ejecutor de acciones para X11 / Cinnamon usando `wmctrl` (NADA de ctypes/WinAPI).

Lee la lista [[actions]] del config.toml y las corre EN ORDEN. Cada acción es un
dict con un "type" y sus parámetros. Tipos soportados:

  run       -> lanza un programa cualquiera (cmd = [...])
  open_url  -> abre una URL en Brave (o el navegador por defecto)
  activate  -> enfoca una ventana ya abierta (o la lanza si no está)
  wait      -> pausa unos segundos entre acciones
  music     -> arranca música de fondo (archivo al azar de una carpeta)
  welcome   -> reproduce un mensaje de bienvenida y espera a que termine
  stop_music-> corta la música de fondo
  say       -> (documentado, sin implementar todavía: TTS local a futuro)

Parámetros de ventana comunes (opcionales) en run/open_url/activate:
  workspace   -> número de espacio de trabajo de Cinnamon al que mandar la ventana
  fullscreen  -> true/false, pone la ventana en pantalla completa (EWMH)
  match       -> substring de la clase/título de ventana a esperar o enfocar

Cada acción se corre dentro de un try/except: si una falla, avisa y sigue con
las demás.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import time
import webbrowser
from pathlib import Path
from typing import Optional

import audio

log = logging.getLogger("jarvis.actions")

# Las rutas del config (por ejemplo "assets/music") se resuelven contra la
# carpeta del proyecto, así da igual desde dónde ejecutes jarvis.py.
_BASE_DIR = Path(__file__).resolve().parent

# Cuánto esperar (segundos) a que aparezca la ventana de una app recién lanzada.
_NEW_WINDOW_TIMEOUT_S = 15.0
_POLL_INTERVAL_S = 0.15


# --- utilidades wmctrl -------------------------------------------------------

def _have_wmctrl() -> bool:
    return shutil.which("wmctrl") is not None


def _wmctrl(*args: str) -> subprocess.CompletedProcess:
    """Corre wmctrl con los argumentos dados y devuelve el resultado."""
    return subprocess.run(
        ["wmctrl", *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )


def _list_windows() -> list[dict]:
    """
    Devuelve las ventanas actuales como dicts: id, desktop, wm_class, title.
    Usa `wmctrl -lx` (la -x agrega la WM_CLASS, que es más estable que el título).
    """
    res = _wmctrl("-lx")
    windows: list[dict] = []
    if res.returncode != 0:
        return windows
    for line in res.stdout.splitlines():
        # Formato: <id> <desktop> <wm_class> <host> <título...>
        parts = line.split(None, 4)
        if len(parts) < 5:
            continue
        win_id, desktop, wm_class, _host, title = parts
        windows.append(
            {
                "id": win_id,
                "desktop": desktop,
                "wm_class": wm_class,
                "title": title,
            }
        )
    return windows


def _window_ids() -> set[str]:
    return {w["id"] for w in _list_windows()}


def _matches(window: dict, needle: str) -> bool:
    needle = needle.lower()
    return needle in window["wm_class"].lower() or needle in window["title"].lower()


def _wait_for_new_window(
    before: set[str], match: Optional[str], timeout: float
) -> Optional[str]:
    """
    Espera a que aparezca una ventana que no estaba antes. Si `match` está seteado,
    exige además que su clase/título lo contenga. Devuelve el id o None si expira.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(_POLL_INTERVAL_S)
        for w in _list_windows():
            if w["id"] in before:
                continue
            if match and not _matches(w, match):
                continue
            return w["id"]
    return None


def _find_window(match: str) -> Optional[str]:
    for w in _list_windows():
        if _matches(w, match):
            return w["id"]
    return None


def _move_to_workspace(win_id: str, workspace: int) -> None:
    # En el config los workspaces son 1-based (Workspace 1 = el primero, como los
    # muestra Cinnamon). wmctrl los cuenta desde 0, así que restamos 1.
    if workspace < 1:
        log.warning("workspace=%d inválido (usá 1, 2, 3...). Salteo el movimiento.", workspace)
        return
    index = workspace - 1
    res = _wmctrl("-i", "-r", win_id, "-t", str(index))
    if res.returncode != 0:
        log.warning("No pude mover %s al workspace %d: %s", win_id, workspace, res.stderr.strip())
    else:
        log.info("Ventana %s -> workspace %d", win_id, workspace)


def _set_fullscreen(win_id: str) -> None:
    res = _wmctrl("-i", "-r", win_id, "-b", "add,fullscreen")
    if res.returncode != 0:
        log.warning("No pude poner %s en fullscreen: %s", win_id, res.stderr.strip())


# --- división de la pantalla (tile) ------------------------------------------

# Cada layout es un rectángulo en FRACCIONES del área útil: x, y, ancho, alto.
# Agregar uno nuevo ("top", "bottom", cuartos...) es una línea más acá.
_TILES = {
    "left":  (0.0, 0.0, 0.5, 1.0),
    "right": (0.5, 0.0, 0.5, 1.0),
}


def _current_desktop() -> int:
    """Índice (0-based) del workspace activo; 0 si no se puede determinar."""
    res = _wmctrl("-d")
    for line in res.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "*" and parts[0].isdigit():
            return int(parts[0])
    return 0


def _work_area(desktop: int) -> Optional[tuple[int, int, int, int]]:
    """
    Área ÚTIL del escritorio (x, y, ancho, alto), del campo `WA:` de `wmctrl -d`.

    Es el rectángulo que el WM deja libre para las ventanas: si hay un panel que
    reserva espacio, ya viene descontado. Por eso usamos esto y no `xrandr`, que
    devuelve la resolución cruda y nos haría meter ventanas bajo el panel.
    """
    res = _wmctrl("-d")
    if res.returncode != 0:
        return None
    for line in res.stdout.splitlines():
        parts = line.split()
        if not parts or not parts[0].isdigit() or int(parts[0]) != desktop:
            continue
        if "WA:" not in parts:
            return None
        i = parts.index("WA:")
        try:
            x, y = (int(v) for v in parts[i + 1].split(","))
            w, h = (int(v) for v in parts[i + 2].split("x"))
        except (IndexError, ValueError):
            return None
        return x, y, w, h
    return None


def _frame_extents(win_id: str) -> tuple[int, int, int, int]:
    """
    Grosor del marco de la ventana (izq, der, arriba, abajo) según EWMH.

    Devuelve ceros si la ventana no publica la propiedad —las apps con
    decoración del lado del cliente, como Brave, no lo hacen— o si `xprop` no
    está instalado. Un marco desconocido se trata como marco nulo, no como error.
    """
    if shutil.which("xprop") is None:
        return (0, 0, 0, 0)
    res = subprocess.run(
        ["xprop", "-id", win_id, "_NET_FRAME_EXTENTS"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, check=False,
    )
    if res.returncode != 0 or "=" not in res.stdout:
        return (0, 0, 0, 0)
    try:
        vals = [int(v.strip()) for v in res.stdout.split("=", 1)[1].split(",")]
    except ValueError:
        return (0, 0, 0, 0)
    return (vals[0], vals[1], vals[2], vals[3]) if len(vals) >= 4 else (0, 0, 0, 0)


def _unmaximize(win_id: str) -> None:
    """Una ventana maximizada ignora los pedidos de geometría; hay que soltarla."""
    _wmctrl("-i", "-r", win_id, "-b", "remove,maximized_vert,maximized_horz")


def _tile_window(win_id: str, tile: str, desktop: int) -> None:
    """Ubica la ventana en una fracción del área útil (mitad izquierda/derecha)."""
    frac = _TILES.get(str(tile).strip().lower())
    if frac is None:
        log.warning("tile=%r desconocido. Valores válidos: %s", tile, ", ".join(_TILES))
        return

    area = _work_area(desktop)
    if area is None:
        log.warning("No pude leer el área útil del escritorio %d; salteo el tile.", desktop)
        return

    ax, ay, aw, ah = area
    fx, fy, fw, fh = frac
    x = ax + round(aw * fx)
    y = ay + round(ah * fy)
    w = round(aw * fw)
    h = round(ah * fh)

    _unmaximize(win_id)

    # `wmctrl -e` dimensiona el ÁREA DE CLIENTE, sin contar el marco: si no lo
    # descontamos, una ventana con barra de título de 32px termina ocupando
    # 32px más de alto que el rectángulo pedido y se desborda.
    left, right, top, bottom = _frame_extents(win_id)
    w = max(1, w - left - right)
    h = max(1, h - top - bottom)

    res = _wmctrl("-i", "-r", win_id, "-e", f"0,{x},{y},{w},{h}")
    if res.returncode != 0:
        log.warning("No pude ubicar %s en %r: %s", win_id, tile, res.stderr.strip())
    else:
        log.info("Ventana %s -> tile %s (%dx%d en %d,%d)", win_id, tile, w, h, x, y)


def _place_window(win_id: str, action: dict) -> None:
    """Aplica workspace y, según la acción, tile o fullscreen."""
    ws = action.get("workspace")
    if isinstance(ws, int):
        _move_to_workspace(win_id, ws)

    tile = action.get("tile")
    if tile and action.get("fullscreen"):
        log.warning("'tile' y 'fullscreen' son incompatibles; uso 'tile' e ignoro 'fullscreen'.")

    if tile:
        # El tile se calcula contra el escritorio donde va a quedar la ventana.
        desktop = (ws - 1) if isinstance(ws, int) and ws >= 1 else _current_desktop()
        _tile_window(win_id, tile, desktop)
    elif action.get("fullscreen"):
        _set_fullscreen(win_id)


def _place_new_window(before: set[str], action: dict, default_match: Optional[str]) -> None:
    """
    Para run/open_url: si la acción pide workspace, tile o fullscreen, espera la
    ventana nueva y se la aplica. Si no pide nada de ventana, no espera (más rápido).
    """
    wants_placement = (
        isinstance(action.get("workspace"), int)
        or action.get("fullscreen")
        or action.get("tile")
    )
    if not wants_placement:
        return
    if not _have_wmctrl():
        log.warning("wmctrl no está instalado; no puedo mover/fullscreen la ventana.")
        return
    match = action.get("match") or default_match
    win_id = _wait_for_new_window(before, match, _NEW_WINDOW_TIMEOUT_S)
    if win_id is None:
        log.warning(
            "No apareció la ventana esperada (match=%r) en %.0fs; salteo el placement.",
            match,
            _NEW_WINDOW_TIMEOUT_S,
        )
        return
    _place_window(win_id, action)


# --- lanzadores --------------------------------------------------------------

def _spawn(cmd: list[str]) -> None:
    """Lanza un proceso desacoplado (no bloquea, sin heredar la terminal)."""
    subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _browser_command(browser: str) -> Optional[list[str]]:
    """
    Traduce un nombre de navegador a un comando ejecutable.
    'brave' -> brave-browser (o brave). Si no está, devuelve None (usamos webbrowser).
    """
    name = (browser or "brave").strip().lower()
    if name in ("brave", "brave-browser"):
        exe = shutil.which("brave-browser") or shutil.which("brave")
        return [exe] if exe else None
    # cualquier otro nombre: probamos tal cual en el PATH
    exe = shutil.which(name)
    return [exe] if exe else None


# --- handlers por tipo de acción ---------------------------------------------

def _do_run(action: dict) -> None:
    cmd = action.get("cmd")
    if not isinstance(cmd, list) or not cmd:
        log.warning("Acción 'run' sin 'cmd' válido (lista de strings). Salteo.")
        return
    exe = shutil.which(cmd[0]) or cmd[0]
    before = _window_ids() if _have_wmctrl() else set()
    log.info("run: %s", " ".join(cmd))
    _spawn([exe, *cmd[1:]])
    _place_new_window(before, action, default_match=cmd[0])


def _do_open_url(action: dict) -> None:
    url = (action.get("url") or "").strip()
    if not url:
        log.warning("Acción 'open_url' sin 'url'. Salteo.")
        return
    browser = action.get("browser", "brave")
    new_window = bool(action.get("new_window", True))
    cmd = _browser_command(browser)
    before = _window_ids() if _have_wmctrl() else set()

    if cmd is None:
        log.warning("No encontré el navegador %r; abro con el navegador por defecto.", browser)
        if not webbrowser.open(url):
            log.warning("No hay ningún navegador disponible; salteo la acción.")
            return
        # Abrió OTRO navegador y no sabemos cuál: buscar por el nombre pedido
        # nos dejaría esperando 15s una ventana que nunca aparece. Sin match,
        # tomamos la primera ventana nueva que salga.
        default_match = None
    else:
        args = list(cmd)
        if new_window:
            args.append("--new-window")
        args.append(url)
        log.info("open_url (%s): %s", browser, url)
        _spawn(args)
        # El nombre del navegador suele estar en su WM_CLASS
        # ("Navigator.brave-browser", "Navigator.firefox"). Tiene que salir del
        # navegador pedido y no de una constante, o con browser="firefox" nos
        # quedaríamos esperando una ventana de Brave que nunca aparece.
        default_match = browser

    _place_new_window(before, action, default_match=default_match)


def _do_activate(action: dict) -> None:
    match = (action.get("match") or "").strip()
    if not match:
        log.warning("Acción 'activate' sin 'match'. Salteo.")
        return
    if not _have_wmctrl():
        log.warning("wmctrl no está instalado; no puedo activar ventanas.")
        return

    win_id = _find_window(match)
    if win_id is None:
        launch = action.get("launch")
        if isinstance(launch, list) and launch:
            log.info("No hay ventana %r abierta; la lanzo: %s", match, " ".join(launch))
            before = _window_ids()
            exe = shutil.which(launch[0]) or launch[0]
            _spawn([exe, *launch[1:]])
            win_id = _wait_for_new_window(before, match, _NEW_WINDOW_TIMEOUT_S)
            if win_id is None:
                log.warning("Lancé %r pero no apareció su ventana a tiempo.", match)
                return
        else:
            log.warning("No hay ventana %r abierta y no hay 'launch'. Salteo.", match)
            return
    else:
        # -x -a activa la ventana por clase (la trae al frente y cambia de workspace).
        _wmctrl("-x", "-a", match)

    _place_window(win_id, action)


def _do_wait(action: dict) -> None:
    try:
        seconds = float(action.get("seconds", 0))
    except (TypeError, ValueError):
        log.warning("Acción 'wait' con 'seconds' inválido. Salteo.")
        return
    if seconds > 0:
        log.info("wait: %.2fs", seconds)
        time.sleep(seconds)


def _resolve_folder(raw: Optional[str], default: str) -> Path:
    folder = Path(raw or default)
    return folder if folder.is_absolute() else _BASE_DIR / folder


def _do_music(action: dict) -> None:
    folder = _resolve_folder(action.get("folder"), "assets/music")
    track = audio.pick_random(folder, action.get("include"))
    if track is None:
        return

    gui = bool(action.get("gui", True))
    before = _window_ids() if gui and _have_wmctrl() else set()

    started = audio.play_background(
        track,
        action.get("volume", 100),
        gui=gui,
        keep_on_exit=bool(action.get("keep_on_exit", True)),
    )

    # Con gui=true VLC abre su ventana: la mandamos al workspace que diga el
    # config para que no tape nada. Queda visible en la barra de ese workspace,
    # así la podés cerrar a mano cuando quieras.
    if started and gui:
        _place_new_window(before, action, default_match="vlc")


def _do_welcome(action: dict) -> None:
    # Si la acción trae after_s, esperamos a que la música lleve ese tiempo
    # sonando (contado desde que arrancó, no desde ahora).
    after = action.get("after_s")
    if after is not None:
        try:
            audio.wait_since_music(float(after))
        except (TypeError, ValueError):
            log.warning("Acción 'welcome' con 'after_s' inválido (%r); no espero.", after)

    folder = _resolve_folder(action.get("folder"), "assets/welcome")
    message = audio.pick_random(folder, action.get("include"))
    if message is None:
        return

    # Por defecto cortamos la música para que se entienda la voz.
    if action.get("stop_music", True):
        audio.stop_background()

    audio.play_and_wait(message, action.get("volume", 100))


def _do_stop_music(action: dict) -> None:
    audio.stop_background()


def _do_say(action: dict) -> None:
    # Reservado para TTS local (Piper) en una próxima iteración. Ver SPEC.md §8.
    log.info("say: (TTS todavía no implementado) %r", action.get("text", ""))


_HANDLERS = {
    "run": _do_run,
    "open_url": _do_open_url,
    "activate": _do_activate,
    "wait": _do_wait,
    "music": _do_music,
    "welcome": _do_welcome,
    "stop_music": _do_stop_music,
    "say": _do_say,
}


def run_actions(actions: list[dict]) -> None:
    """
    Corre la lista de acciones en orden. Pensada para llamarse desde el callback
    del detector (ya viene en su propio hilo). Una acción que falla no frena las
    otras.
    """
    if not _have_wmctrl():
        log.warning("wmctrl no está instalado: workspace/fullscreen/activate no funcionarán.")
    for i, action in enumerate(actions):
        atype = action.get("type")
        handler = _HANDLERS.get(atype)
        if handler is None:
            log.warning("Acción #%d con type desconocido %r. Tipos válidos: %s",
                        i + 1, atype, ", ".join(_HANDLERS))
            continue
        try:
            handler(action)
        except Exception as e:  # noqa: BLE001 - una acción no debe tumbar al resto
            log.warning("Acción #%d (%s) falló: %s", i + 1, atype, e)
