#!/bin/sh
# Closes the public live demo opened by ./demo_on.sh. Leaves other Tailscale serves alone.
H=""; command -v flatpak-spawn >/dev/null && H="flatpak-spawn --host"
$H tailscale funnel --https=443 off
$H systemctl --user stop lyfe-checkin-demo.service
$H tailscale funnel status
