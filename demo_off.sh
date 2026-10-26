#!/bin/sh
# Closes the public live demo opened by ./demo_on.sh. Leaves other Tailscale serves alone.
cd "$(dirname "$0")"
TS="tailscale"; command -v tailscale >/dev/null || TS="flatpak-spawn --host tailscale"
$TS funnel --https=443 off
[ -f data/demo.pid ] && kill "$(cat data/demo.pid)" 2>/dev/null; rm -f data/demo.pid
$TS funnel status
