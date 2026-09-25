#!/usr/bin/env bash
# install_reporter.sh - connect the server to the Hermesville app.
# Run as opc (not sudo):   bash install_reporter.sh
set -euo pipefail

DIR="$HOME/hermesville"
mkdir -p "$DIR"
cp "$(dirname "$0")/report_status.py" "$DIR/report_status.py"
chmod +x "$DIR/report_status.py"

# Wrap the reel video service: report running -> done / failed
UNIT="$HOME/.config/systemd/user/reel-video.service"
if [ -f "$UNIT" ]; then
  cat > "$UNIT" <<'EOF'
[Unit]
Description=Build today's reel video and send it to Telegram
After=network-online.target

[Service]
Type=oneshot
Environment=PATH=%h/bin:/usr/local/bin:/usr/bin:/bin
ExecStartPre=-/usr/bin/python3 %h/hermesville/report_status.py film running
ExecStartPre=%h/reels/venv/bin/pip install -q --upgrade edge-tts
ExecStart=%h/reels/venv/bin/python %h/reels/make_reel.py
ExecStopPost=/bin/sh -c 'if [ "$$SERVICE_RESULT" = success ]; then /usr/bin/python3 %h/hermesville/report_status.py film done "reel sent to Telegram"; else /usr/bin/python3 %h/hermesville/report_status.py film failed "exit $$EXIT_STATUS - see journalctl"; fi'
TimeoutStartSec=1200
EOF
  systemctl --user daemon-reload
  echo "reel-video.service now reports to Hermesville"
else
  echo "reel-video.service not found - run the reel setup.sh first"
fi

grep -q '^GITHUB_TOKEN=' "$HOME/.hermes/.env" 2>/dev/null || echo "!! Add GITHUB_TOKEN=... to ~/.hermes/.env"
grep -q '^GITHUB_REPO=' "$HOME/.hermes/.env" 2>/dev/null || echo "!! Add GITHUB_REPO=<username>/hermesville to ~/.hermes/.env"
echo "Test:  python3 ~/hermesville/report_status.py writer done \"test from server\""
