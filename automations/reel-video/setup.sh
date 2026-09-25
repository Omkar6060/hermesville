#!/usr/bin/env bash
# setup.sh - install the daily reel video pipeline on Oracle Linux (ARM or x86)
# Run as the normal user (opc), NOT with sudo:   bash setup.sh
set -euo pipefail

REELS="$HOME/reels"
mkdir -p "$REELS" "$HOME/bin" "$HOME/.config/systemd/user"
touch "$REELS/history.txt"

echo "==> 1/5 System packages (python 3.11, fonts)"
sudo dnf install -y python3.11 python3.11-pip dejavu-sans-fonts xz tar curl

echo "==> 2/5 Optional offline fallback voice (espeak-ng from EPEL)"
OLVER=$(rpm -E %rhel)
sudo dnf install -y "oracle-epel-release-el${OLVER}" >/dev/null 2>&1 || true
sudo dnf install -y espeak-ng >/dev/null 2>&1 && echo "   espeak-ng installed" \
  || echo "   espeak-ng not available - skipping (only used if Microsoft voice fails)"

echo "==> 3/5 ffmpeg (static build)"
if ! command -v ffmpeg >/dev/null && [ ! -x "$HOME/bin/ffmpeg" ]; then
  case "$(uname -m)" in
    aarch64) FF=ffmpeg-release-arm64-static.tar.xz ;;
    x86_64)  FF=ffmpeg-release-amd64-static.tar.xz ;;
    *) echo "unsupported CPU $(uname -m)"; exit 1 ;;
  esac
  TMP=$(mktemp -d)
  curl -fL "https://johnvansickle.com/ffmpeg/releases/$FF" -o "$TMP/ff.tar.xz"
  tar -xJf "$TMP/ff.tar.xz" -C "$TMP"
  cp "$TMP"/ffmpeg-*-static/ffmpeg "$TMP"/ffmpeg-*-static/ffprobe "$HOME/bin/"
  rm -rf "$TMP"
fi
"$HOME/bin/ffmpeg" -version 2>/dev/null | head -1 || ffmpeg -version | head -1

echo "==> 4/5 Python environment"
python3.11 -m venv "$REELS/venv"
"$REELS/venv/bin/pip" install -q --upgrade pip edge-tts requests pillow
cp "$(dirname "$0")/make_reel.py" "$REELS/make_reel.py"

echo "==> 5/5 Daily timer (07:10 server time)"
cat > "$HOME/.config/systemd/user/reel-video.service" <<EOF
[Unit]
Description=Build today's reel video and send it to Telegram
After=network-online.target

[Service]
Type=oneshot
Environment=PATH=%h/bin:/usr/local/bin:/usr/bin:/bin
ExecStartPre=%h/reels/venv/bin/pip install -q --upgrade edge-tts
ExecStart=%h/reels/venv/bin/python %h/reels/make_reel.py
TimeoutStartSec=1200
EOF

cat > "$HOME/.config/systemd/user/reel-video.timer" <<EOF
[Unit]
Description=Daily reel video at 07:10

[Timer]
OnCalendar=*-*-* 07:10:00
Persistent=true

[Install]
WantedBy=timers.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now reel-video.timer

echo
echo "Done. Server time zone: $(timedatectl show -p Timezone --value)  (should be Asia/Kolkata)"
systemctl --user list-timers reel-video.timer --no-pager
grep -q '^PEXELS_API_KEY=' "$HOME/.hermes/.env" 2>/dev/null \
  || echo "!! Add your free Pexels key:  echo 'PEXELS_API_KEY=xxxx' >> ~/.hermes/.env"
