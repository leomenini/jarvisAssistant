#!/usr/bin/env python3
"""
Jarvis — punto de entrada.

Une las tres piezas:
  1. config.toml     -> tus perillas del detector + tu lista de acciones
  2. clap_detector   -> escucha el mic y detecta el doble aplauso (lógica reusada)
  3. actions         -> ejecuta las acciones con wmctrl sobre X11/Cinnamon

Uso:
  python jarvis.py                 # usa config.toml al lado de este archivo
  python jarvis.py otro_config.toml
"""

from __future__ import annotations

import logging
import sys
import tomllib
from pathlib import Path

from actions import run_actions
from clap_detector import DetectorConfig, listen

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("jarvis")


def _load_config(path: Path) -> dict:
    if not path.is_file():
        log.error("No encuentro el config: %s", path)
        example = path.parent / "config.example.toml"
        if path.name == "config.toml" and example.is_file():
            log.error("Copiá la plantilla y editala:  cp %s %s", example.name, path.name)
        raise SystemExit(1)
    with path.open("rb") as f:
        return tomllib.load(f)


def _build_detector_config(raw: dict) -> DetectorConfig:
    """
    Toma la sección [detector] del TOML y llena un DetectorConfig. Solo copia las
    claves que el DetectorConfig conoce (así una clave de más no rompe nada).
    """
    section = raw.get("detector", {}) or {}
    cfg = DetectorConfig()
    known = cfg.__dataclass_fields__  # nombres de campos válidos
    for key, value in section.items():
        if key in known:
            setattr(cfg, key, value)
        else:
            log.warning("[detector] tiene una clave desconocida: %r (la ignoro).", key)
    return cfg


def main() -> int:
    config_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent / "config.toml"
    raw = _load_config(config_path)

    cfg = _build_detector_config(raw)
    actions = raw.get("actions", []) or []

    if not actions:
        log.warning("No hay [[actions]] en el config; el doble aplauso no hará nada.")
    else:
        log.info("%d acción(es) cargada(s) desde %s.", len(actions), config_path.name)

    def on_double_clap() -> None:
        run_actions(actions)

    return listen(cfg, on_double_clap)


if __name__ == "__main__":
    sys.exit(main())
