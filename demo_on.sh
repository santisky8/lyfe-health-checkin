#!/bin/sh
# Opens the public live demo: a public-mode copy of the app on port 8766, published on the
# internet through Tailscale Funnel. Needs the Windows laptop (Nightshift) and Zetaris running.
# Close it with ./demo_off.sh. Log: data/demo.log
cd "$(dirname "$0")"
TS="tailscale"; command -v tailscale >/dev/null || TS="flatpak-spawn --host tailscale"
if ! curl -s -o /dev/null http://127.0.0.1:8766/api/status; then
  PUBLIC=1 PORT=8766 nohup python3 server.py >> data/demo.log 2>&1 &
  echo $! > data/demo.pid
  sleep 3
fi
$TS funnel --bg --https=443 http://127.0.0.1:8766
$TS funnel status
