#!/bin/bash
# Levanta un escritorio y un servidor de audio headless, y corre las
# verificaciones. Ver docker/Dockerfile para el contexto.
set -euo pipefail

echo "=== Entorno de verificación de Jarvis ==="
echo

# --- escritorio virtual ------------------------------------------------------
Xvfb :99 -screen 0 1280x800x24 >/dev/null 2>&1 &
for _ in $(seq 1 50); do
    xdpyinfo -display :99 >/dev/null 2>&1 && break
    sleep 0.1
done
xdpyinfo -display :99 >/dev/null 2>&1 || { echo "FALLO: Xvfb no arrancó"; exit 1; }

# openbox es un WM con soporte EWMH y varios escritorios, igual que Muffin:
# es lo que hace que wmctrl tenga con quién hablar.
openbox >/dev/null 2>&1 &
for _ in $(seq 1 50); do
    wmctrl -m >/dev/null 2>&1 && break
    sleep 0.1
done
wmctrl -m >/dev/null 2>&1 || { echo "FALLO: no hay window manager EWMH"; exit 1; }

# openbox arranca con 4 escritorios; los workspaces del config son 1-based.
wmctrl -n 4 >/dev/null 2>&1 || true

# --- audio -------------------------------------------------------------------
# Un sink nulo: los reproductores tocan de verdad, contra un dispositivo que no
# suena. Alcanza para verificar que el comando existe y termina bien.
pulseaudio --start --exit-idle-time=-1 >/dev/null 2>&1 || true
sleep 1
pactl load-module module-null-sink sink_name=dummy >/dev/null 2>&1 || true
pactl set-default-sink dummy >/dev/null 2>&1 || true
# El .monitor del sink nulo es una fuente de CAPTURA: lo que se reproduce en el
# sink se puede grabar desde ahí. Es lo que nos permite alimentar al detector
# con un aplauso sintético y ejercitarlo de verdad, sin micrófono.
pactl set-default-source dummy.monitor >/dev/null 2>&1 || true

echo "escritorio : $(wmctrl -m | head -1)"
echo "workspaces : $(wmctrl -d | wc -l)"
echo "audio      : $(pactl info 2>/dev/null | grep -i 'default sink' || echo 'sin pulseaudio')"
echo

exec .venv/bin/python docker/verify.py
