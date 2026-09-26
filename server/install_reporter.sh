#!/usr/bin/env bash
# install_reporter.sh - make the reel video job report its status to Hermesville.
# Run after server/install.sh and automations/reel-video/setup.sh:
#   bash server/install_reporter.sh
set -euo pipefail

mkdir -p "$HOME/hermesville"
cp "$(dirname "$0")/report_status.py" "$HOME/hermesville/report_status.py"

UNIT="$HOME/.config/systemd/user/reel-video.service"
[ -f "$UNIT" ] || { echo "reel-video.service not found - run automations/reel-video/setup.sh first"; exit 1; }
cat > "$UNIT" <<'EOF'
[Unit]
Description=Build today's reel video and send it to Telegram
After=network-online.target

[Service]
Type=oneshot
Environment=PATH=%h/bin:/usr/local/bin:/usr/bin:/bin
ExecStartPre=-/usr/bin/env python3 %h/hermesville/report_status.py film running
ExecStartPre=%h/reels/venv/bin/pip install -q --upgrade edge-tts
ExecStart=%h/reels/venv/bin/python %h/reels/make_reel.py
ExecStopPost=/bin/sh -c 'if [ "$$SERVICE_RESULT" = success ]; then /usr/bin/env python3 %h/hermesville/report_status.py film done "reel sent to Telegram"; else /usr/bin/env python3 %h/hermesville/report_status.py film failed "exit $$EXIT_STATUS - see journalctl"; fi'
TimeoutStartSec=1200
EOF
systemctl --user daemon-reload
echo "reel-video.service now reports to Hermesville."
echo "Test: python3 ~/hermesville/report_status.py writer done \"test\""
