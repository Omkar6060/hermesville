#!/usr/bin/env bash
# install.sh - set up the Hermesville back end on your server, privately.
#
#   bash server/install.sh https://<your-github-username>.github.io
#
# What it does (safe to run again; it skips finished steps):
#   1. Turns on Hermes's API server on 127.0.0.1 only, with a random key
#   2. Installs the tracker (Google Calendar + Notion) on 127.0.0.1 only
#   3. Asks you for an app password and sets up 2FA (Google Authenticator etc.)
#   4. Starts the gateway: the ONLY service the internet can reach
#   5. Installs Tailscale and publishes the gateway over HTTPS (Funnel)
#   6. Checks from the outside that everything private really is private
#
# Works on Ubuntu/Debian and Oracle Linux/RHEL. Run as your normal user, not root.
set -euo pipefail

ORIGIN="${1:-}"
if [[ ! "$ORIGIN" =~ ^https://[a-zA-Z0-9.-]+$ ]]; then
  echo "Usage: bash server/install.sh https://<your-github-username>.github.io"
  echo "       (the address your Hermesville app is served from, no path, no trailing slash)"
  exit 1
fi
[ "$(id -u)" -eq 0 ] && { echo "Run this as your normal user (e.g. ubuntu or opc), not root."; exit 1; }

HERE="$(cd "$(dirname "$0")" && pwd)"
DIR="$HOME/hermesville"
ENV="$HOME/.hermes/.env"
UNITS="$HOME/.config/systemd/user"
mkdir -p "$DIR" "$UNITS" "$(dirname "$ENV")"; touch "$ENV"; chmod 600 "$ENV"
setvar() { if grep -q "^$1=" "$ENV"; then sed -i "s|^$1=.*|$1=$2|" "$ENV"; else echo "$1=$2" >> "$ENV"; fi; }
say() { printf '\n==> %s\n' "$1"; }

say "0/6 Checking the basics"
for c in python3 curl openssl systemctl; do command -v "$c" >/dev/null || { echo "Missing: $c"; exit 1; }; done
python3 -c 'import sys; assert sys.version_info >= (3, 9)' || { echo "Python 3.9+ needed"; exit 1; }
systemctl --user cat hermes-gateway >/dev/null 2>&1 || { echo "Hermes gateway service not found. Finish 'hermes gateway install' first (see README step 5)."; exit 1; }
sudo loginctl enable-linger "$USER"
cp "$HERE/gateway.py" "$HERE/tracker.py" "$HERE/report_status.py" "$DIR/"

say "1/6 Hermes API server (127.0.0.1 only)"
grep -q '^API_SERVER_KEY=' "$ENV" || setvar API_SERVER_KEY "$(openssl rand -hex 32)"
setvar API_SERVER_ENABLED true
setvar API_SERVER_HOST 127.0.0.1
setvar API_SERVER_PORT 8642
setvar API_SERVER_CORS_ORIGINS "$ORIGIN"
systemctl --user restart hermes-gateway
for i in $(seq 1 20); do
  curl -fsS -H "Authorization: Bearer $(grep '^API_SERVER_KEY=' "$ENV" | cut -d= -f2-)" http://127.0.0.1:8642/v1/models >/dev/null 2>&1 && break
  sleep 1
done && echo "   Hermes API is answering on 127.0.0.1:8642"

say "2/6 Tracker (Google Calendar + Notion, 127.0.0.1 only)"
cat > "$UNITS/hermesville-tracker.service" <<'EOF'
[Unit]
Description=Hermesville tracker (Google Calendar + Notion)
After=network-online.target

[Service]
ExecStart=/usr/bin/env python3 %h/hermesville/tracker.py
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now hermesville-tracker >/dev/null
systemctl --user restart hermesville-tracker
grep -q '^GCAL_ICS_URL=' "$ENV" || echo "   (optional) add GCAL_ICS_URL=... later for your calendar"
grep -q '^NOTION_TOKEN=' "$ENV" || echo "   (optional) add NOTION_TOKEN=... and NOTION_DB_ID=... later for Notion"

say "3/6 Your login: password + 2FA"
if grep -q '^HV_PASSWORD_HASH=' "$ENV"; then echo "   password already set (change: python3 $DIR/gateway.py set-password)"
else python3 "$DIR/gateway.py" set-password; fi
if grep -q '^HV_TOTP_SECRET=' "$ENV"; then echo "   2FA already set (redo: python3 $DIR/gateway.py setup-2fa)"
else python3 "$DIR/gateway.py" setup-2fa; fi

say "4/6 Gateway (the only public service)"
cat > "$UNITS/hermesville-gateway.service" <<'EOF'
[Unit]
Description=Hermesville gateway (login + 2FA in front of Hermes and the tracker)
After=network-online.target

[Service]
ExecStart=/usr/bin/env python3 %h/hermesville/gateway.py
Restart=always
RestartSec=5
NoNewPrivileges=true

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now hermesville-gateway >/dev/null
systemctl --user restart hermesville-gateway
sleep 2
curl -fsS http://127.0.0.1:8600/health >/dev/null && echo "   gateway is answering on 127.0.0.1:8600"

say "5/6 Tailscale Funnel (HTTPS address for the gateway only)"
command -v tailscale >/dev/null || curl -fsSL https://tailscale.com/install.sh | sh
sudo systemctl enable --now tailscaled
if ! tailscale status >/dev/null 2>&1; then
  echo "   Open the login link below and sign in to Tailscale (free):"
  sudo tailscale up --hostname hermesville
fi
echo "   If a link to enable Funnel appears, open it, approve, then run this script again."
sudo tailscale funnel reset >/dev/null 2>&1 || true
sudo tailscale funnel --bg 8600
URL=$(tailscale funnel status 2>/dev/null | grep -o 'https://[^ ]*' | head -1 | sed 's#/$##')

say "6/6 Checking from the internet side"
sleep 4
ok=1
chk() { local got; got=$(curl -s -o /dev/null -w '%{http_code}' "$URL$1"); printf "   %-26s %s (want %s)\n" "$1" "$got" "$2"; [ "$got" = "$2" ] || ok=0; }
chk /health 200
chk /api/status 401
chk /api/tracking/summary 401
chk /v1/models 404
[ $ok = 1 ] && echo "   All private parts are private." || echo "   !! Something answered unexpectedly. Check 'tailscale funnel status' and the README troubleshooting."

cat <<EOF

Done. Open your app ($ORIGIN/hermesville/) and log in with:
   Server address : $URL
   Password       : the one you chose
   2FA code       : from your authenticator app

Useful later:
   restart after editing ~/.hermes/.env : systemctl --user restart hermes-gateway hermesville-tracker hermesville-gateway
   sign out every device                : python3 $DIR/gateway.py logout-all && systemctl --user restart hermesville-gateway
EOF
