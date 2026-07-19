#!/usr/bin/env python3
"""
Reproducción de audio para Jarvis (música de fondo + mensaje de bienvenida).

No usa librerías de Python: se apoya en un reproductor de línea de comandos que
ya viene en el sistema. Prueba en orden `ffplay` (parte de ffmpeg) y `cvlc`
(VLC sin interfaz). Si no hay ninguno, avisa y sigue de largo — el audio nunca
debe impedir que se abran las apps.

Dos modos de reproducción:
  play_background()  -> arranca y vuelve enseguida (la música suena mientras
                        siguen corriendo las demás acciones).
  play_and_wait()    -> bloquea hasta que el archivo termina (el mensaje de
                        bienvenida se escucha completo antes de seguir).

La música de fondo puede sonar de dos formas:
  gui=True   -> VLC con su ventana (actions.py la manda al workspace que diga el
                config). Se cierra solo cuando termina la canción, y podés
                cerrarlo a mano antes si no lo querés.
  gui=False  -> ffplay sin ventana (no se ve, no se puede cerrar a mano).
"""

from __future__ import annotations

import atexit
import logging
import random
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger("jarvis.audio")

_AUDIO_EXTS = {".mp3", ".wav", ".ogg", ".oga", ".flac", ".m4a", ".opus"}

# Proceso de la música de fondo (None si no hay nada sonando).
_background: Optional[subprocess.Popen] = None
# Momento (reloj monotónico) en que arrancó la música. Lo usa `wait_since_music`
# para medir "10-15 segundos desde que empezó la musiquita".
_music_started_at: Optional[float] = None
# Si es True, al cerrarse Jarvis la música se deja sonando (no la matamos).
_keep_on_exit: bool = False


# --- elegir el reproductor ---------------------------------------------------

def _headless_cmd(path: Path, volume: int) -> Optional[list[str]]:
    """Reproductor sin ventana: no se ve ni se puede cerrar a mano."""
    ffplay = shutil.which("ffplay")
    if ffplay:
        return [
            ffplay,
            "-nodisp",       # sin ventana
            "-autoexit",     # cerrar al terminar el archivo
            "-loglevel", "quiet",
            "-volume", str(volume),
            str(path),
        ]

    cvlc = shutil.which("cvlc")
    if cvlc:
        # VLC toma la ganancia como un factor (1.0 = volumen original).
        return [
            cvlc,
            "--intf", "dummy",
            "--play-and-exit",
            "--gain", f"{volume / 100:.2f}",
            str(path),
        ]

    return None


def _gui_cmd(path: Path, volume: int) -> Optional[list[str]]:
    """
    VLC con ventana, para que puedas subirle el volumen, pausarlo o cerrarlo a
    mano. Con --play-and-exit se cierra solo cuando termina la canción.

    Ojo: NO usamos --qt-start-minimized porque en Cinnamon manda VLC a la bandeja
    del sistema y deja de aparecer en la barra de tareas (justo lo contrario de
    lo que queremos). La ventana se deja visible y actions.py la manda al
    workspace del config para que no tape nada.
    """
    vlc = shutil.which("vlc")
    if vlc is None:
        return None
    return [
        vlc,
        "--play-and-exit",        # se cierra solo al terminar
        "--no-video",             # es un mp3, no queremos ventana de video
        "--no-qt-privacy-ask",    # sin el diálogo de bienvenida de VLC
        "--gain", f"{volume / 100:.2f}",
        str(path),
    ]


def _clamp_volume(volume) -> int:
    try:
        value = int(volume)
    except (TypeError, ValueError):
        log.warning("Volumen inválido %r; uso 100.", volume)
        return 100
    return max(0, min(100, value))


# --- elegir el archivo -------------------------------------------------------

def pick_random(folder: Path, include: Optional[str] = None) -> Optional[Path]:
    """
    Elige al azar un archivo de audio dentro de `folder` (busca también en
    subcarpetas). `include`, si está, filtra por un pedazo del nombre —  sirve
    para separar idiomas, por ejemplo include = "Bienv" para los mensajes en
    español. Devuelve None si no encuentra nada.
    """
    if not folder.is_dir():
        log.warning("La carpeta de audio no existe: %s", folder)
        return None

    files = [p for p in sorted(folder.rglob("*")) if p.suffix.lower() in _AUDIO_EXTS]
    if include:
        needle = include.lower()
        files = [p for p in files if needle in p.name.lower()]

    if not files:
        log.warning("No hay archivos de audio en %s (include=%r).", folder, include)
        return None

    return random.choice(files)


# --- reproducir --------------------------------------------------------------

def play_background(
    path: Path,
    volume: int = 100,
    gui: bool = True,
    keep_on_exit: bool = True,
) -> bool:
    """
    Arranca `path` de fondo y vuelve enseguida. True si pudo lanzarlo.

    gui=True           -> VLC con su ventana (actions.py la manda al workspace
                          que diga el config; la podés pausar o cerrar a mano).
    keep_on_exit=True  -> la música sigue sonando aunque Jarvis se cierre.
    """
    global _background, _music_started_at, _keep_on_exit

    stop_background()

    volume = _clamp_volume(volume)
    cmd = _gui_cmd(path, volume) if gui else _headless_cmd(path, volume)
    if cmd is None:
        if gui:
            log.warning("No encuentro vlc; instalalo con: sudo apt install vlc")
        else:
            log.warning("No encuentro ffplay ni cvlc; no puedo reproducir audio. "
                        "Instalá ffmpeg con: sudo apt install ffmpeg")
        return False

    _background = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    _music_started_at = time.monotonic()
    _keep_on_exit = keep_on_exit
    log.info("música: %s (volumen %d, %s)", path.name, volume,
             "VLC con ventana" if gui else "sin ventana")
    return True


def play_and_wait(path: Path, volume: int = 100, timeout: float = 120.0) -> bool:
    """
    Reproduce `path` y bloquea hasta que termina (o hasta `timeout`). Siempre sin
    ventana: el mensaje de bienvenida dura unos segundos y no tiene sentido que
    abra un reproductor.
    """
    cmd = _headless_cmd(path, _clamp_volume(volume))
    if cmd is None:
        log.warning("No encuentro ffplay ni cvlc; no puedo reproducir audio. "
                    "Instalá ffmpeg con: sudo apt install ffmpeg")
        return False

    log.info("audio: %s (volumen %d)", path.name, volume)
    try:
        subprocess.run(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        log.warning("El audio %s se pasó de %.0fs; lo corto.", path.name, timeout)
        return False
    return True


def stop_background() -> None:
    """Corta la música de fondo si está sonando (pedido explícito)."""
    global _background, _music_started_at, _keep_on_exit

    _keep_on_exit = False
    if _background is None:
        return
    if _background.poll() is None:  # sigue vivo
        _background.terminate()
        try:
            _background.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            _background.kill()
    _background = None
    _music_started_at = None


def wait_since_music(seconds: float) -> None:
    """
    Duerme lo que falte para que hayan pasado `seconds` desde que arrancó la
    música. Si las apps ya tardaron más que eso, no espera nada. Si no hay
    música sonando, espera `seconds` completos.
    """
    if _music_started_at is None:
        time.sleep(max(0.0, seconds))
        return

    elapsed = time.monotonic() - _music_started_at
    remaining = seconds - elapsed
    if remaining > 0:
        log.info("espero %.1fs más de música (van %.1fs de %.1fs).", remaining, elapsed, seconds)
        time.sleep(remaining)
    else:
        log.info("la música ya lleva %.1fs (>= %.1fs); sigo sin esperar.", elapsed, seconds)


def _cleanup_on_exit() -> None:
    """
    Al cerrarse Jarvis (Ctrl+C, o el fin de run_once): si la música se lanzó con
    keep_on_exit=True la dejamos sonando hasta el final — el reproductor es un
    proceso independiente y se cierra solo. Si no, la cortamos para no dejar
    audio colgado sin ventana que lo apague.
    """
    if _keep_on_exit and _background is not None and _background.poll() is None:
        log.info("Jarvis se cierra; dejo la música sonando (cerrala a mano si querés).")
        return
    stop_background()


atexit.register(_cleanup_on_exit)
