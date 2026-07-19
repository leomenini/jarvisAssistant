# Entorno de verificación para Jarvis.
#
# NO es para correr el proyecto en producción: Jarvis manipula el escritorio del
# usuario, y acá levantamos un escritorio propio (Xvfb + openbox) dentro del
# contenedor. Sirve para responder "¿esto funciona en una máquina limpia?" sin
# tocar tu sesión real.
#
#   docker build -f docker/Dockerfile -t jarvis-verify .
#   docker run --rm jarvis-verify
#
# Base Ubuntu 24.04 = la misma que Linux Mint 22, con Python 3.12 (tomllib).

FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

# Dependencias declaradas en el README (python3-venv wmctrl ffmpeg vlc) más lo
# necesario para tener un escritorio y un servidor de audio headless.
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-venv \
        wmctrl ffmpeg vlc \
        libportaudio2 \
        xvfb openbox x11-utils xterm \
        pulseaudio \
        ca-certificates procps \
    && rm -rf /var/lib/apt/lists/*

# VLC se niega a correr como root, y en general el setup del README se hace como
# usuario normal: replicamos esa condición.
RUN useradd -m -s /bin/bash jarvis
USER jarvis
WORKDIR /home/jarvis/app

# El proyecto tal cual (ver .dockerignore: no entra ni .venv ni config.toml ni
# los assets de audio — exactamente lo que vería alguien que clona el repo).
COPY --chown=jarvis:jarvis . .

# Paso 3 del README: entorno aislado + dependencias.
RUN python3 -m venv .venv \
    && .venv/bin/pip install --no-cache-dir --upgrade pip \
    && .venv/bin/pip install --no-cache-dir -r requirements.txt

ENV DISPLAY=:99
ENTRYPOINT ["/bin/bash", "docker/verify.sh"]
