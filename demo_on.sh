#!/bin/sh
# Opens the public live demo: the lyfe-checkin-demo user service (demo_service.sh) runs a
# public-mode copy of the app on port 8766, and Tailscale Funnel puts it on the internet.
# Needs the Windows laptop (Nightshift). Close it with ./demo_off.sh.
cd "$(dirname "$0")"
H=""; command -v flatpak-spawn >/dev/null && H="flatpak-spawn --host"
$H systemctl --user start lyfe-checkin-demo.service
$H tailscale funnel --bg --https=443 http://127.0.0.1:8766
$H tailscale funnel status
