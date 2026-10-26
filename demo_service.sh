#!/bin/sh
# Started at login by the systemd user service lyfe-checkin-demo (see README). Starts Docker
# Desktop and waits for Zetaris, then runs the public demo copy on port 8766 for Tailscale
# Funnel. After the judging window it disables itself, so Docker goes back to staying off.
cd "$(dirname "$0")"
UNTIL=2026-11-15
if [ "$(date +%F)" \> "$UNTIL" ]; then
  echo "Demo autostart ended on $UNTIL; disabling."
  systemctl --user disable lyfe-checkin-demo.service
  exit 0
fi
systemctl --user start docker-desktop
ZETARIS_URL=$(sed -n 's/^ZETARIS_URL=//p' .env.local)
for i in $(seq 1 90); do  # up to 6 minutes for Docker Desktop and Zetaris to come up
  curl -s -o /dev/null -m 5 "$ZETARIS_URL" && break
  sleep 4
done
export PUBLIC=1 PORT=8766
export NODE_BIN="${NODE_BIN:-$HOME/.var/app/com.vscodium.codium/data/node/bin/node}"
exec /usr/bin/python3 server.py
