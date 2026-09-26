#!/usr/bin/env bash
# enable_command_center.sh - let the Hermesville command center talk to Hermes.
#
#  1. turns on Hermes's built-in API server (localhost:8642, key-protected)
#  2. allows your GitHub Pages site to call it from the browser (CORS)
#  3. publishes it on a stable HTTPS address with Tailscale Funnel
#     (outbound tunnel: no ports opened on Oracle)
#
# Run as opc (not sudo):   bash enable_command_center.sh https://omkar6060.github.io
set -euo pipefail

ORIGIN="${1:-https://omkar6060.github.io}"
ENV="$HOME/.hermes/.env"
touch "$ENV"; chmod 600 "$ENV"

setvar() {  # setvar NAME VALUE  (replace or append in ~/.hermes/.env)
  if grep -q "^$1=" "$ENV"; then sed -i "s|^$1=.*|$1=$2|" "$ENV"; else echo "$1=$2" >> "$ENV"; fi
}

echo "==> 1/4 Hermes API server settings"
grep -q '^API_SERVER_KEY=' "$ENV" || setvar API_SERVER_KEY "$(openssl rand -hex 32)"
setvar API_SERVER_ENABLED true
setvar API_SERVER_HOST 127.0.0.1
setvar API_SERVER_PORT 8642
setvar API_SERVER_CORS_ORIGINS "$ORIGIN"
KEY=$(grep '^API_SERVER_KEY=' "$ENV" | cut -d= -f2-)

echo "==> 2/4 Restarting the Hermes gateway"
systemctl --user restart hermes-gateway
sleep 6
if curl -fsS -H "Authorization: Bearer $KEY" http://127.0.0.1:8642/v1/models >/dev/null; then
  echo "   API server is answering on 127.0.0.1:8642"
else
  echo "!! API server not answering yet. Check: journalctl --user -u hermes-gateway -n 50"
  exit 1
fi

echo "==> 3/4 Tailscale"
if ! command -v tailscale >/dev/null; then
  curl -fsSL https://tailscale.com/install.sh | sh
fi
sudo systemctl enable --now tailscaled
if ! tailscale status >/dev/null 2>&1; then
  echo "   Open the login link below on your phone or PC and sign in (free account):"
  sudo tailscale up --hostname hermes-server
fi

echo "==> 4/4 Tailscale Funnel -> port 8642"
echo "   If it prints a link to enable Funnel, open it, approve, then run this script again."
sudo tailscale funnel --bg 8642
URL=$(tailscale funnel status 2>/dev/null | grep -o 'https://[^ ]*' | head -1 || true)

echo
echo "================ put these in the app (tap POWER) ================"
echo " Server URL : ${URL:-see 'tailscale funnel status'}"
echo " API key    : $KEY"
echo "=================================================================="
echo "The key gives full control of Hermes on this server. Type it into the"
echo "app yourself; don't screenshot it or paste it into chats."