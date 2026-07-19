#!/usr/bin/env python3
"""
Detector de doble aplauso — REUSADO del proyecto original (lógica intacta).

Lee el micrófono con sounddevice/PortAudio, calcula el RMS (volumen) de bloques
cortos de audio y detecta dos "picos" seguidos (un doble aplauso). No sabe NADA
de qué acciones dispara: cuando detecta, llama a la función `on_double_clap` que
le pasás. Así el "cómo escucha" (esto) queda separado del "qué hace" (actions.py
+ config.toml).

Portátil: no depende del sistema operativo. Solo necesita numpy + sounddevice.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np
import sounddevice as sd

log = logging.getLogger("jarvis.detector")


@dataclass
class DetectorConfig:
    """Todas las 'perillas' del detector. Se llenan desde [detector] del TOML."""

    sample_rate: int = 44100
    block_ms: int = 40
    channels: int = 1

    spike_ratio: float = 7.0        # cuántas veces sobre el ruido de fondo = aplauso
    cooldown_s: float = 0.45        # antirrebote entre disparos
    min_gap_s: float = 0.05         # separación mínima entre los dos aplausos
    max_gap_s: float = 0.35         # separación máxima entre los dos aplausos
    retrigger_ratio: float = 0.55   # hay que bajar de umbral*esto para rearmar
    noise_floor_alpha: float = 0.992  # cerca de 1 = el piso de ruido se adapta lento
    min_rms: float = 0.012          # ignora picos por debajo de este nivel absoluto

    # Calibración del ruido ambiente al arrancar (segundos). El piso arranca en
    # el nivel real de tu sala en vez de un valor fijo: sin esto, en una sala con
    # algo de ruido el umbral quedaba pegado a min_rms y disparaba solo.
    calibrate_s: float = 1.0

    # Sondeo de micrófono al arrancar
    input_probe_s: float = 0.5
    input_silent_rms: float = 0.001
    # Forzar un mic: índice (número) o parte del nombre. Vacío = autodetectar.
    input_device: str = ""

    # True = detecta UN doble aplauso, corre las acciones hasta el final y cierra
    #        el detector (las apps abiertas quedan abiertas, son independientes).
    # False = queda escuchando para siempre (dispara en cada doble aplauso).
    run_once: bool = True


def _block_samples(cfg: DetectorConfig) -> int:
    n = int(cfg.sample_rate * cfg.block_ms / 1000)
    return max(n, 1)


def rms_mono(block: np.ndarray) -> float:
    """RMS (nivel de volumen) de un bloque de audio, mezclando a mono si hace falta."""
    if block.ndim > 1:
        block = np.mean(block.astype(np.float64), axis=1)
    else:
        block = block.astype(np.float64)
    if block.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(block**2)))


# --- selección de micrófono (útil con PipeWire, que expone varios inputs) -----

def _input_devices() -> list[tuple[int, dict]]:
    return [
        (i, dev)
        for i, dev in enumerate(sd.query_devices())
        if dev["max_input_channels"] >= 1
    ]


def _resolve_input_device_index(spec: str) -> int:
    spec = spec.strip()
    if spec.isdigit():
        idx = int(spec)
        sd.query_devices(idx)  # valida que exista
        return idx
    needle = spec.lower()
    for idx, dev in _input_devices():
        if needle in dev["name"].lower():
            return idx
    raise ValueError(f"Ningún micrófono coincide con {spec!r}")


def _probe_input_max_rms(cfg: DetectorConfig, device: int, blocksize: int) -> Optional[float]:
    """Abre el mic un ratito y devuelve el pico de RMS (para saber si 'escucha')."""
    try:
        with sd.InputStream(
            device=device,
            samplerate=cfg.sample_rate,
            channels=cfg.channels,
            dtype="float32",
            blocksize=blocksize,
        ) as stream:
            peak = 0.0
            deadline = time.monotonic() + cfg.input_probe_s
            while time.monotonic() < deadline:
                data, _ = stream.read(blocksize)
                peak = max(peak, rms_mono(data))
            return peak
    except sd.PortAudioError:
        return None


def _choose_input_device(cfg: DetectorConfig, blocksize: int) -> int:
    log.info("Dispositivos de audio:\n%s", sd.query_devices())

    override = (cfg.input_device or os.environ.get("JARVIS_INPUT_DEVICE") or "").strip()
    if override:
        try:
            idx = _resolve_input_device_index(override)
        except ValueError as e:
            log.error("%s", e)
            log.error("Poné input_device (o JARVIS_INPUT_DEVICE) a un índice o parte del nombre.")
            raise SystemExit(1) from e
        name = sd.query_devices(idx)["name"]
        peak = _probe_input_max_rms(cfg, idx, blocksize)
        log.info("Usando mic configurado [%d]: %s", idx, name)
        if peak is None:
            log.warning("No se pudo abrir el mic configurado; lo intento igual.")
        elif peak < cfg.input_silent_rms:
            log.warning("El mic configurado parece mudo (rms=%.5f).", peak)
        else:
            log.info("Sondeo de mic OK (rms=%.5f).", peak)
        return idx

    default = sd.default.device[0]
    if default is not None and default >= 0:
        default_name = sd.query_devices(default)["name"]
        peak = _probe_input_max_rms(cfg, default, blocksize)
        if peak is not None and peak >= cfg.input_silent_rms:
            log.info("Usando mic por defecto [%d]: %s (rms=%.5f)", default, default_name, peak)
            return default
        log.warning(
            "El mic por defecto [%d] %s está mudo o no abre (rms=%s); escaneo otros...",
            default,
            default_name,
            f"{peak:.5f}" if peak is not None else "no-abre",
        )

    best_idx: Optional[int] = None
    best_peak = -1.0
    for idx, dev in _input_devices():
        if default is not None and idx == default:
            continue
        peak = _probe_input_max_rms(cfg, idx, blocksize)
        if peak is not None and peak > best_peak:
            best_peak = peak
            best_idx = idx

    if best_idx is not None and best_peak >= cfg.input_silent_rms:
        log.info(
            "Mic autoseleccionado [%d]: %s (rms=%.5f)",
            best_idx,
            sd.query_devices(best_idx)["name"],
            best_peak,
        )
        return best_idx

    if default is not None and default >= 0:
        log.warning("No encontré un mic activo; uso el default [%d].", default)
        return default
    inputs = _input_devices()
    if not inputs:
        log.error("No hay dispositivos de entrada.")
        raise SystemExit(1)
    idx, dev = inputs[0]
    log.warning("No encontré un mic activo; uso [%d] %s.", idx, dev["name"])
    return idx


def _measure_ambient(stream, blocksize: int, seconds: float) -> float:
    """
    Mide el ruido de fondo real de la sala durante `seconds` y devuelve la
    MEDIANA de los RMS. Mediana y no promedio para que un ruido puntual (una
    puerta, una tos) no infle la calibración.
    """
    levels: list[float] = []
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        data, _ = stream.read(blocksize)
        levels.append(rms_mono(data))
    if not levels:
        return 0.0
    return float(np.median(levels))


# --- bucle principal de detección --------------------------------------------

def listen(cfg: DetectorConfig, on_double_clap: Callable[[], None]) -> int:
    """
    Escucha el mic para siempre. Cada vez que detecta un doble aplauso, llama a
    `on_double_clap()` en un hilo aparte (para que las acciones no frenen la
    captura de audio). Ctrl+C corta. Devuelve el exit code.
    """
    blocksize = _block_samples(cfg)
    noise_floor = 1e-4
    last_fired = 0.0
    first_clap_time: Optional[float] = None
    spike_armed = True

    log.info(
        "Escuchando (doble aplauso: %.2f–%.2fs, rate=%d, block=%d ms, "
        "spike_ratio=%.1f, cooldown=%.2fs). Ctrl+C para cortar.",
        cfg.min_gap_s,
        cfg.max_gap_s,
        cfg.sample_rate,
        cfg.block_ms,
        cfg.spike_ratio,
        cfg.cooldown_s,
    )

    input_idx = _choose_input_device(cfg, blocksize)

    try:
        with sd.InputStream(
            device=input_idx,
            samplerate=cfg.sample_rate,
            channels=cfg.channels,
            dtype="float32",
            blocksize=blocksize,
        ) as stream:
            # Calibración: arrancamos el piso en el ruido real de la sala. Antes
            # arrancaba en 1e-4 fijo y, como solo se actualizaba hacia abajo,
            # nunca podía alcanzar un ambiente más ruidoso: el umbral quedaba
            # pegado a min_rms y el detector disparaba solo.
            if cfg.calibrate_s > 0:
                log.info("Calibrando ruido ambiente %.1fs (quedate en silencio)...", cfg.calibrate_s)
                ambient = _measure_ambient(stream, blocksize, cfg.calibrate_s)
                if ambient > 0:
                    noise_floor = ambient
                log.info(
                    "Ruido ambiente = %.5f -> umbral de aplauso = %.5f",
                    noise_floor,
                    max(noise_floor * cfg.spike_ratio, cfg.min_rms),
                )

            while True:
                data, overflowed = stream.read(blocksize)
                if overflowed:
                    log.warning("Overflow de entrada; probá un block_ms más grande.")

                level = rms_mono(data)
                threshold = max(noise_floor * cfg.spike_ratio, cfg.min_rms)
                now = time.monotonic()

                # El piso sigue al ambiente mientras NO haya pico: así un aplauso
                # no contamina el promedio, pero el piso puede subir Y bajar si el
                # ruido de la sala cambia (un ventilador que arranca, etc.).
                if level < threshold:
                    noise_floor = cfg.noise_floor_alpha * noise_floor + (
                        1.0 - cfg.noise_floor_alpha
                    ) * level
                    noise_floor = max(noise_floor, 1e-7)
                retrigger_level = threshold * cfg.retrigger_ratio

                # Rearme: hay que caer por debajo del umbral para contar otro pico.
                if level < retrigger_level:
                    spike_armed = True

                if (
                    spike_armed
                    and level >= threshold
                    and (now - last_fired) >= cfg.cooldown_s
                ):
                    spike_armed = False
                    if first_clap_time is None:
                        first_clap_time = now
                    else:
                        gap = now - first_clap_time
                        if gap < cfg.min_gap_s:
                            pass  # demasiado juntos: es el mismo aplauso, ignorar
                        elif gap <= cfg.max_gap_s:
                            first_clap_time = None
                            last_fired = now
                            log.info(
                                "¡Doble aplauso! (gap=%.3fs, rms=%.5f, piso=%.5f, umbral=%.5f)",
                                gap,
                                level,
                                noise_floor,
                                threshold,
                            )
                            if cfg.run_once:
                                # Corre las acciones de forma bloqueante para que
                                # terminen (mover ventanas al workspace incluido)
                                # ANTES de salir. Las apps son procesos aparte y
                                # quedan abiertas cuando el detector se cierra.
                                on_double_clap()
                                log.info("Acciones ejecutadas; cierro el detector.")
                                return 0
                            threading.Thread(target=on_double_clap, daemon=True).start()
                        else:
                            first_clap_time = now  # muy separados: reinicia el conteo

    except KeyboardInterrupt:
        log.info("Detenido.")
        return 0
    except sd.PortAudioError as e:
        log.error("Error de audio: %s", e)
        log.error("Si PortAudio falla, probá otro sample_rate o revisá PipeWire/ALSA.")
        return 1

    return 0
