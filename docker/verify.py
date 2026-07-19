#!/usr/bin/env python3
"""
Verificaciones de Jarvis en un entorno limpio.

Responde "¿esto funciona en una máquina que no es la mía?" ejercitando el código
real —no imitaciones— contra un escritorio y un servidor de audio headless que
levanta docker/verify.sh.

Lo que NO cubre: la detección de aplausos con un micrófono real. Eso necesita
hardware de entrada y queda como verificación manual (ver README, "Verificar en
limpio").

Se corre solo dentro del contenedor:
    docker build -f docker/Dockerfile -t jarvis-verify .
    docker run --rm jarvis-verify
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
import tomllib
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

# Las acciones logean en WARNING lo que no pueden hacer; queremos verlo.
logging.basicConfig(level=logging.WARNING, format="      %(levelname)s %(message)s")

_failures: list[str] = []
_step = 0
TOTAL = 8


def step(title: str) -> None:
    global _step
    _step += 1
    print(f"[{_step}/{TOTAL}] {title}")


def check(ok: bool, detail: str) -> bool:
    print(f"      {'OK  ' if ok else 'FALLO'}  {detail}")
    if not ok:
        _failures.append(detail)
    return ok


# --- 1. dependencias ---------------------------------------------------------

def verify_dependencies() -> None:
    step("Dependencias instaladas desde cero")

    import numpy
    import sounddevice
    check(True, f"numpy {numpy.__version__}, sounddevice {sounddevice.__version__}")

    import shutil
    for tool in ("wmctrl", "ffplay", "vlc"):
        check(shutil.which(tool) is not None, f"{tool} en el PATH")

    check(sys.version_info >= (3, 11),
          f"Python {sys.version_info.major}.{sys.version_info.minor} (>= 3.11 por tomllib)")


# --- 2. experiencia del clon fresco ------------------------------------------

def verify_fresh_clone() -> None:
    step("Clon fresco: sin config.toml, con la plantilla")

    check(not (BASE / "config.toml").exists(),
          "config.toml NO viaja en el repo (está en .gitignore/.dockerignore)")
    check((BASE / "config.example.toml").is_file(),
          "config.example.toml sí está versionado")

    # jarvis.py debe explicar qué hacer, no tirar un traceback.
    res = subprocess.run([sys.executable, "jarvis.py"], cwd=BASE,
                         capture_output=True, text=True, timeout=60)
    salida = res.stdout + res.stderr
    check(res.returncode != 0, "jarvis.py sin config falla con exit code distinto de 0")
    check("cp config.example.toml config.toml" in salida,
          "el error dice exactamente qué comando correr")
    check("Traceback" not in salida, "no expone un traceback crudo")

    # diagnostico.py debe poder tunear el detector sin config personal.
    src = (BASE / "diagnostico.py").read_text()
    check("config.example.toml" in src,
          "diagnostico.py cae a la plantilla si no hay config.toml")


# --- 3. la plantilla es válida y completa ------------------------------------

def verify_template() -> None:
    step("config.example.toml parsea y todos sus tipos existen")

    import actions

    with (BASE / "config.example.toml").open("rb") as f:
        cfg = tomllib.load(f)

    acciones = cfg.get("actions", [])
    check(len(acciones) > 0, f"{len(acciones)} acciones en la plantilla")

    tipos = {a.get("type") for a in acciones}
    desconocidos = tipos - set(actions._HANDLERS)
    check(not desconocidos, f"tipos usados: {', '.join(sorted(tipos))}")

    # Toda clave de [detector] tiene que existir en el dataclass, o el usuario
    # cree que configuró algo que se ignora en silencio.
    from clap_detector import DetectorConfig
    campos = DetectorConfig().__dataclass_fields__
    huerfanas = [k for k in cfg.get("detector", {}) if k not in campos]
    check(not huerfanas, f"claves [detector] reconocidas (huérfanas: {huerfanas or 'ninguna'})")


# --- 4. manejo de ventanas de verdad -----------------------------------------

def _windows() -> list[dict]:
    import actions
    return actions._list_windows()


def verify_window_placement() -> None:
    step("Ventanas: lanzar una app y mandarla a un workspace")

    import actions

    check(actions._have_wmctrl(), "wmctrl responde")

    escritorios = subprocess.run(["wmctrl", "-d"], capture_output=True, text=True).stdout
    n = len(escritorios.strip().splitlines())
    check(n >= 3, f"{n} workspaces disponibles")

    # El camino real: run_actions con una lista como la de un config.
    actions.run_actions([
        {"type": "run", "cmd": ["xterm"], "match": "xterm", "workspace": 2},
    ])

    xterms = [w for w in _windows() if "xterm" in w["wm_class"].lower()]
    if not check(bool(xterms), "la ventana de xterm apareció"):
        return

    # El config es 1-based y wmctrl 0-based: workspace 2 => desktop "1".
    desktop = xterms[0]["desktop"]
    check(desktop == "1",
          f"xterm quedó en el desktop {desktop} de wmctrl (workspace 2 del config)")

    # Y el fullscreen por EWMH, sin simular F11.
    actions.run_actions([
        {"type": "activate", "match": "xterm", "workspace": 3, "fullscreen": True},
    ])
    time.sleep(0.5)
    xterms = [w for w in _windows() if "xterm" in w["wm_class"].lower()]
    check(bool(xterms) and xterms[0]["desktop"] == "2",
          "activate movió la misma ventana al workspace 3")

    subprocess.run(["pkill", "-f", "xterm"], check=False)


# --- 5. degradación cuando falta wmctrl --------------------------------------

def verify_degradation() -> None:
    step("Sin wmctrl: las apps se abren igual, sin ubicarlas")

    import actions

    original = actions._have_wmctrl
    actions._have_wmctrl = lambda: False
    try:
        # No debe lanzar excepción: el criterio es degradar, no abortar.
        actions.run_actions([
            {"type": "run", "cmd": ["xterm"], "match": "xterm", "workspace": 2},
        ])
        check(True, "run_actions no explota sin wmctrl")
    except Exception as e:  # noqa: BLE001
        check(False, f"run_actions lanzó {type(e).__name__}: {e}")
    finally:
        actions._have_wmctrl = original
        subprocess.run(["pkill", "-f", "xterm"], check=False)

    # Un type inexistente y una acción sin su parámetro obligatorio: ambas deben
    # advertir y seguir, no cortar la secuencia.
    try:
        actions.run_actions([
            {"type": "no_existe"},
            {"type": "run"},                 # sin cmd
            {"type": "open_url"},            # sin url
            {"type": "wait", "seconds": 0.1},
        ])
        check(True, "acciones inválidas advierten y no frenan a las siguientes")
    except Exception as e:  # noqa: BLE001
        check(False, f"una acción inválida tumbó la secuencia: {e}")


# --- 6. audio ----------------------------------------------------------------

def verify_audio() -> None:
    step("Audio: elegir archivo al azar y reproducirlo")

    import audio

    # Los assets no viajan en el repo, así que generamos uno.
    tmp = Path("/tmp/jarvis-audio-test")
    tmp.mkdir(exist_ok=True)
    wav = tmp / "prueba.wav"
    if not wav.exists():
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
             "-loglevel", "quiet", str(wav)],
            check=True, timeout=60,
        )

    elegido = audio.pick_random(tmp)
    check(elegido is not None and elegido.name == "prueba.wav",
          "pick_random encuentra el archivo")

    check(audio.pick_random(tmp, include="no-existe") is None,
          "el filtro include descarta lo que no matchea")

    vacia = Path("/tmp/jarvis-vacia")
    vacia.mkdir(exist_ok=True)
    check(audio.pick_random(vacia) is None,
          "una carpeta vacía devuelve None en vez de explotar")

    check(audio.play_and_wait(wav, volume=20) is True,
          "play_and_wait reproduce y espera a que termine")

    # after_s se cuenta desde que arrancó la música: si ya pasó, no espera.
    audio._music_started_at = time.monotonic() - 10.0
    t0 = time.monotonic()
    audio.wait_since_music(3.0)
    check(time.monotonic() - t0 < 0.5,
          "wait_since_music no espera de más si la música ya lleva tiempo")
    audio._music_started_at = None


# --- 7. el detector, de punta a punta ----------------------------------------

_SR = 44100


def _write_wav(path: Path, tramos: list) -> Path:
    """Concatena tramos de audio y los escribe como WAV mono de 16 bits."""
    import wave

    import numpy as np

    señal = np.clip(np.concatenate(tramos), -1, 1)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(_SR)
        w.writeframes((señal * 32767).astype("int16").tobytes())
    return path


def _silencio(rng, dur: float):
    # No es silencio digital: un piso de ruido bajo, como una sala real.
    return rng.normal(0, 0.0008, int(_SR * dur))


def _aplauso(rng, dur: float = 0.035):
    # Ráfaga de ruido con envolvente decreciente: ataque seco y cola corta.
    import numpy as np

    n = int(_SR * dur)
    return rng.normal(0, 0.45, n) * np.exp(-np.linspace(0, 12, n))


def _correr_detector(wav: Path, timeout: float) -> tuple[bool, bool]:
    """
    Corre el detector real contra el monitor de PulseAudio y reproduce `wav`.

    Devuelve (disparado, hubo_error_de_audio). El segundo valor importa: si el
    stream se cae, el detector NO dispara, y sin distinguir ese caso una prueba
    negativa ("un aplauso solo no debe disparar") pasaría por el motivo
    equivocado. `listen()` devuelve 1 ante un PortAudioError.
    """
    import threading

    from clap_detector import DetectorConfig, listen

    disparado = threading.Event()
    resultado: dict[str, int] = {}

    cfg = DetectorConfig()
    cfg.input_device = "pulse"   # el monitor del sink nulo
    cfg.calibrate_s = 1.0
    cfg.run_once = True          # el hilo termina solo al detectar

    def correr() -> None:
        resultado["rc"] = listen(cfg, disparado.set)

    threading.Thread(target=correr, daemon=True).start()

    # El detector tarda un rato variable en arrancar (enumera dispositivos,
    # sondea el mic, calibra). En vez de adivinar ese tiempo con un sleep fijo
    # —que falla cuando la máquina está cargada— reproducimos en loop hasta que
    # dispare o se acabe el plazo. Las repeticiones quedan separadas por más de
    # max_gap_s, así que dos aplausos de pasadas distintas nunca forman un par.
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if disparado.is_set() or resultado.get("rc") == 1:
            break
        subprocess.run(["paplay", "--device=dummy", str(wav)], check=False, timeout=30)
        if disparado.wait(1.5):
            break

    return disparado.is_set(), resultado.get("rc") == 1


def _detectar_con_reintentos(wav: Path, timeout: float, intentos: int = 3) -> tuple[bool, bool]:
    """
    El puente ALSA->PulseAudio del contenedor tira PaErrorCode -9999 de forma
    intermitente (es del entorno, no del proyecto). Reintentamos ante ese error
    en vez de reportar un fallo que no es real; si agota los intentos, se informa
    como no concluyente.
    """
    for intento in range(1, intentos + 1):
        fired, error = _correr_detector(wav, timeout)
        if not error:
            return fired, False
        if intento < intentos:
            print(f"      ...error de audio del entorno, reintento {intento}/{intentos - 1}")
            time.sleep(2.0)
    return False, True


def verify_detector() -> None:
    step("Detector: doble aplauso sintético por PulseAudio")

    import numpy as np

    rng = np.random.default_rng(42)

    # POSITIVO: dos aplausos separados 0.20s, dentro de [min_gap, max_gap].
    doble = _write_wav(Path("/tmp/doble.wav"), [
        _silencio(rng, 0.4), _aplauso(rng),
        _silencio(rng, 0.20), _aplauso(rng),
        _silencio(rng, 0.6),
    ])
    fired, error = _detectar_con_reintentos(doble, timeout=12.0)
    if error:
        check(False, "el stream de audio no se sostuvo; prueba no concluyente")
    else:
        check(fired, "un doble aplauso (gap 0.20s) dispara el callback")

    # NEGATIVO: un solo aplauso NO debe disparar. Sin esto, un detector que
    # dispara con cualquier ruido pasaría la prueba positiva igual.
    solo = _write_wav(Path("/tmp/solo.wav"), [
        _silencio(rng, 0.4), _aplauso(rng), _silencio(rng, 1.5),
    ])
    fired, error = _detectar_con_reintentos(solo, timeout=6.0)
    if error:
        check(False, "el stream de audio no se sostuvo; prueba no concluyente")
    else:
        check(not fired, "un aplauso solo NO dispara el callback")

    # La prueba negativa deja un detector escuchando (nunca dispara, así que
    # listen() no retorna). Es un hilo daemon y muere con el proceso, pero al
    # desmontarse su stream PortAudio logea un error que aparecería DESPUÉS del
    # resumen y haría dudar de un resultado ya cerrado.
    logging.getLogger("jarvis.detector").setLevel(logging.CRITICAL)


# --- 8. los scripts como programas -------------------------------------------

def verify_scripts_end_to_end() -> None:
    """
    Los pasos anteriores llaman a las funciones como librería. Este corre los
    SCRIPTS: `jarvis.py` de principio a fin (aplauso -> acciones -> salida) y
    `diagnostico.py`. Es la diferencia entre "las piezas andan" y "el programa
    anda", y es donde aparecen los problemas de integración.
    """
    step("Los scripts corren end-to-end (jarvis.py, diagnostico.py)")

    import threading

    import numpy as np

    rng = np.random.default_rng(7)

    # Assets sintéticos: el repo no trae audio.
    tono = np.sin(2 * np.pi * 220 * np.linspace(0, 2, _SR * 2)) * 0.3
    _write_wav(BASE / "assets/music/verify-track.wav", [tono])
    _write_wav(BASE / "assets/welcome/verify-hola.wav", [tono[: _SR // 2]])

    doble = _write_wav(Path("/tmp/e2e-doble.wav"), [
        _silencio(rng, 0.3), _aplauso(rng),
        _silencio(rng, 0.20), _aplauso(rng),
        _silencio(rng, 0.4),
    ])

    # Config propio en /tmp: no creamos config.toml en el repo, que el paso 2
    # verifica que NO exista. jarvis.py acepta la ruta como argumento.
    cfg_path = Path("/tmp/e2e-config.toml")
    cfg_path.write_text(
        '[detector]\n'
        'calibrate_s = 1.0\n'
        'run_once = true\n'
        'input_device = "pulse"\n'
        '\n'
        '[[actions]]\n'
        'type = "music"\n'
        'folder = "assets/music"\n'
        'include = "verify-track"\n'
        'volume = 20\n'
        'gui = true\n'
        'workspace = 3\n'
        '\n'
        '[[actions]]\n'
        'type = "run"\n'
        'cmd = ["xterm"]\n'
        'match = "xterm"\n'
        'workspace = 2\n'
        '\n'
        '[[actions]]\n'
        'type = "welcome"\n'
        'folder = "assets/welcome"\n'
        'include = "verify-hola"\n'
        'after_s = 2\n'
        'stop_music = false\n'
    )

    proc = subprocess.Popen(
        [sys.executable, "jarvis.py", str(cfg_path)],
        cwd=BASE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )

    # Alimentar aplausos hasta que el proceso termine (run_once) o venza el plazo.
    def alimentar() -> None:
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline and proc.poll() is None:
            subprocess.run(["paplay", "--device=dummy", str(doble)],
                           check=False, timeout=30)
            time.sleep(1.5)

    hilo = threading.Thread(target=alimentar, daemon=True)
    hilo.start()

    try:
        salida = proc.communicate(timeout=90)[0]
    except subprocess.TimeoutExpired:
        proc.kill()
        salida = proc.communicate()[0]
        check(False, "jarvis.py no terminó en 90s (run_once no cerró)")
        return

    check(proc.returncode == 0, f"jarvis.py terminó con exit code {proc.returncode}")
    check("¡Doble aplauso!" in salida, "jarvis.py detectó el doble aplauso")
    check("Acciones ejecutadas" in salida, "corrió la secuencia completa y cerró solo")
    check("Traceback" not in salida, "sin excepciones sin capturar")

    # El log dice que movió la ventana; verificamos contra el WM, no contra el log.
    xterms = [w for w in _windows() if "xterm" in w["wm_class"].lower()]
    check(bool(xterms) and xterms[0]["desktop"] == "1",
          "xterm quedó en el workspace 2 tras la corrida real")
    subprocess.run(["pkill", "-f", "xterm"], check=False)

    # Ninguna acción debería tardar 15s esperando una ventana que no viene.
    check("salteo el placement" not in salida,
          "ninguna acción se colgó esperando una ventana inexistente")

    # diagnostico.py: tiene que arrancar, calibrar y salir sin romper.
    diag = subprocess.run([sys.executable, "diagnostico.py", "3"],
                          cwd=BASE, capture_output=True, text=True, timeout=90)
    check(diag.returncode == 0, f"diagnostico.py terminó con exit code {diag.returncode}")
    check("umbral=" in diag.stdout, "diagnostico.py calibró e informó el umbral")


def main() -> int:
    print(f"Jarvis — verificación en entorno limpio (DISPLAY={os.environ.get('DISPLAY')})\n")

    for fn in (verify_dependencies, verify_fresh_clone, verify_template,
               verify_window_placement, verify_degradation, verify_audio,
               verify_detector, verify_scripts_end_to_end):
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            check(False, f"{fn.__name__} lanzó {type(e).__name__}: {e}")
        print()

    if _failures:
        print(f"=== {len(_failures)} verificación(es) FALLARON ===")
        for f in _failures:
            print(f"  - {f}")
        return 1

    print("=== Todo OK: el proyecto funciona en una máquina limpia ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
