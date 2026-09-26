#!/usr/bin/env bash
# enable_tracking.sh - run the "My Tracking" service (Google Calendar + Notion)
# and publish it at <your ts.net address>/tracking next to the command center.
# Run as opc (not sudo), AFTER enable_command_center.sh:   bash enable_tracking.sh
set -euo pipefail

ENV="$HOME/.hermes/.env"
DIR="$HOME/hermesville"
mkdir -p "$DIR" "$HOME/.config/systemd/user"
cp "$(dirname "$0")/tracker.py" "$DIR/tracker.py"

echo "==> 1/3 Checking settings in ~/.hermes/.env"
for v in API_SERVER_KEY API_SERVER_CORS_ORIGINS; do
  grep -q "^$v=" "$ENV" || { echo "!! $v missing - run enable_command_center.sh first"; exit 1; }
done
grep -q '^GCAL_ICS_URL=' "$ENV" && echo "   Google Calendar: set" || echo "   Google Calendar: not set yet (add GCAL_ICS_URL=...)"
grep -q '^NOTION_TOKEN=' "$ENV" && grep -q '^NOTION_DB_ID=' "$ENV" && echo "   Notion: set" || echo "   Notion: not set yet (add NOTION_TOKEN=... and NOTION_DB_ID=...)"

echo "==> 2/3 Service"
cat > "$HOME/.config/systemd/user/hermesville-tracker.service" <<'EOF'
[Unit]
Description=Hermesville My Tracking (Google Calendar + Notion)
After=network-online.target

[Service]
ExecStart=/usr/bin/python3 %h/hermesville/tracker.py
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now hermesville-tracker
systemctl --user restart hermesville-tracker
sleep 2
curl -fsS http://127.0.0.1:8650/health && echo

echo "==> 3/3 Publishing at /tracking on your Funnel address"
sudo tailscale funnel --bg --set-path /tracking http://127.0.0.1:8650
tailscale funnel status
echo
echo "Done. In the app open My Tracking and tap Refresh."
echo "After changing GCAL_ICS_URL / NOTION_* later, run: systemctl --user restart hermesville-tracker"
