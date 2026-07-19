#!/usr/bin/env python3
"""
Diagnóstico del detector de aplausos — para TUNEAR sin abrir nada.

Corre el mismo código que `jarvis.py` (calibración + detección), pero NO ejecuta
ninguna acción: no abre Brave, no lanza Spotify, no suena música. Solo te muestra
qué está escuchando el micrófono.

Uso:
    python diagnostico.py          # 15 segundos
    python diagnostico.py 30       # 30 segundos

Qué mirar:
  - La línea `ambiente=... -> umbral=...` te dice el umbral calibrado.
  - Cada aplauso debería salir como SPIKE con un rms bien por encima del umbral.
  - En silencio NO debería aparecer ningún SPIKE.

Si dispara solo          -> subí `spike_ratio` en config.toml.
Si no escucha tus palmas -> bajalo (probá 4.0).
"""

from __future__ import annotations

import logging
import sys
import time
import tomllib
from pathlib import Path

import sounddevice as sd

from clap_detector import (
    DetectorConfig,
    _block_samples,
    _choose_input_device,
    _measure_ambient,
    rms_mono,
)

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

BASE = Path(__file__).resolve().parent


def main() -> int:
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 15.0

    # En un clon fresco todavía no hay config.toml (está en .gitignore): para
    # tunear el detector alcanza con la sección [detector] de la plantilla.
    config_path = BASE / "config.toml"
    if not config_path.is_file():
        config_path = BASE / "config.example.toml"
        print(f"(sin config.toml — uso {config_path.name})")

    raw = tomllib.load(config_path.open("rb"))
    cfg = DetectorConfig()
    for key, value in (raw.get("detector") or {}).items():
        if key in cfg.__dataclass_fields__:
            setattr(cfg, key, value)

    blocksize = _block_samples(cfg)
    device = _choose_input_device(cfg, blocksize)
    print(f"mic: [{device}] {sd.query_devices(device)['name']}")

    with sd.InputStream(
        device=device,
        samplerate=cfg.sample_rate,
        channels=cfg.channels,
        dtype="float32",
        blocksize=blocksize,
    ) as stream:
        print(f"\ncalibrando {cfg.calibrate_s:.1f}s — quedate en SILENCIO...")
        ambient = _measure_ambient(stream, blocksize, cfg.calibrate_s)
        noise_floor = ambient if ambient > 0 else 1e-4
        threshold = max(noise_floor * cfg.spike_ratio, cfg.min_rms)
        print(f"ambiente={ambient:.5f}  ->  umbral={threshold:.5f}  "
              f"(min_rms={cfg.min_rms}, spike_ratio={cfg.spike_ratio})")

        print(f"\nescuchando {seconds:.0f}s — APLAUDÍ (probá dobles y sueltos)\n")

        spike_armed = True
        first_clap_time = None
        last_fired = 0.0
        spikes = dobles = 0
        peak = 0.0
        t0 = time.monotonic()

        while time.monotonic() - t0 < seconds:
            data, _ = stream.read(blocksize)
            level = rms_mono(data)
            peak = max(peak, level)
            threshold = max(noise_floor * cfg.spike_ratio, cfg.min_rms)
            now = time.monotonic()

            if level < threshold:
                noise_floor = cfg.noise_floor_alpha * noise_floor + (
                    1.0 - cfg.noise_floor_alpha
                ) * level
                noise_floor = max(noise_floor, 1e-7)

            if level < threshold * cfg.retrigger_ratio:
                spike_armed = True

            if spike_armed and level >= threshold and (now - last_fired) >= cfg.cooldown_s:
                spike_armed = False
                spikes += 1
                print(f"{now - t0:5.2f}s  SPIKE  rms={level:.5f}  (umbral={threshold:.5f})")
                if first_clap_time is None:
                    first_clap_time = now
                else:
                    gap = now - first_clap_time
                    if gap < cfg.min_gap_s:
                        pass
                    elif gap <= cfg.max_gap_s:
                        dobles += 1
                        first_clap_time = None
                        last_fired = now
                        print(f"        >>> DOBLE APLAUSO detectado (gap={gap:.3f}s)")
                    else:
                        first_clap_time = now

    print(f"\nRESUMEN: {spikes} spikes, {dobles} dobles aplausos.")
    print(f"pico de rms={peak:.5f}  |  umbral final={max(noise_floor * cfg.spike_ratio, cfg.min_rms):.5f}")
    if spikes == 0:
        print("\n-> No detectó nada. Bajá spike_ratio en config.toml (probá 4.0).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
