# DUT image for CI: Debian 13 "Trixie" like Raspberry Pi OS 64-bit (docs/bench-pi.md),
# with only what mcu_emu, vehicled and mediad need. Built per CPU: arm64 (the bench,
# emulated with QEMU on x86) and amd64 (in case the final hardware is x86).
# The R80 checkout is mounted at run time, so the image never holds R80 code.
#   docker build --platform linux/arm64 -t r80-dut-arm64 ci/dut
FROM debian:trixie
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-dbus python3-gi \
      gir1.2-gstreamer-1.0 gstreamer1.0-plugins-base gstreamer1.0-plugins-good \
 && rm -rf /var/lib/apt/lists/*
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
