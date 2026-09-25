#!/usr/bin/env python3
"""
make_reel.py - turn today's Hermes reel script (JSON) into a 1080x1920 video
and send it to Telegram.

Pipeline:  today.json -> edge-tts voice per line -> Pexels stock clip per line
           -> ffmpeg (crop to vertical + burned-in caption) -> concat -> Telegram

Usage:
    python make_reel.py                 # uses ~/reels/today.json
    python make_reel.py path/to.json
    python make_reel.py --no-send       # build only, don't send to Telegram

Config (read from ~/.hermes/.env or the environment):
    TELEGRAM_BOT_TOKEN      bot token (already set up for Hermes)
    TELEGRAM_ALLOWED_USERS  your Telegram user id (first one is used as chat id)
    REEL_CHAT_ID            optional: override the chat id
    PEXELS_API_KEY          free key from pexels.com/api (optional: without it,
                            plain gradient backgrounds are used)
    REEL_VOICE              optional edge-tts voice (default en-IN-PrabhatNeural)
    REEL_RATE               optional speaking rate (default +8%)
"""

import asyncio
import datetime as dt
import json
import os
import random
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import requests

HOME = Path.home()
REELS_DIR = HOME / "reels"
WORK_DIR = REELS_DIR / "work"
OUT_DIR = REELS_DIR / "videos"
ENV_FILE = HOME / ".hermes" / ".env"

W, H, FPS = 1080, 1920, 30
PAD = 0.35  # seconds of breathing room after each spoken line

FONT_CANDIDATES = [
    "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf",   # Oracle Linux / RHEL
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",     # Debian / Ubuntu
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
]
FFMPEG = shutil.which("ffmpeg") or str(HOME / "bin" / "ffmpeg")
FFPROBE = shutil.which("ffprobe") or str(HOME / "bin" / "ffprobe")

GRADIENTS = [("0x0f2027", "0x2c5364"), ("0x1a2a6c", "0xb21f1f"),
             ("0x42275a", "0x734b6d"), ("0x134e5e", "0x71b280")]


# ---------------------------------------------------------------- helpers
def log(msg):
    print(f"[{dt.datetime.now():%H:%M:%S}] {msg}", flush=True)


def load_env():
    """Merge ~/.hermes/.env into os.environ (existing env vars win)."""
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(map(str, cmd[:4]))} ...\n{r.stderr[-1500:]}")
    return r.stdout


def duration(path):
    out = run([FFPROBE, "-v", "error", "-show_entries", "format=duration",
               "-of", "default=nw=1:nk=1", str(path)])
    return float(out.strip())


def font_path():
    for f in FONT_CANDIDATES:
        if Path(f).exists():
            return f
    raise RuntimeError("No DejaVu Sans Bold font found - install it: sudo dnf install -y dejavu-sans-fonts")


def chat_id():
    cid = os.environ.get("REEL_CHAT_ID") or os.environ.get("TELEGRAM_ALLOWED_USERS", "")
    return cid.split(",")[0].strip()


def telegram(method, data=None, files=None):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token or not chat_id():
        log("Telegram not configured - skipping send")
        return None
    url = f"https://api.telegram.org/bot{token}/{method}"
    r = requests.post(url, data={"chat_id": chat_id(), **(data or {})}, files=files, timeout=300)
    if not r.ok:
        log(f"Telegram error {r.status_code}: {r.text[:300]}")
    return r


# ---------------------------------------------------------------- script
def load_script(path):
    if not path.exists():
        raise RuntimeError(f"{path} not found - the Hermes reel job didn't write today's script")
    age_h = (dt.datetime.now().timestamp() - path.stat().st_mtime) / 3600
    if age_h > 20:
        raise RuntimeError(f"{path.name} is {age_h:.0f}h old - today's script wasn't generated")
    data = json.loads(path.read_text())
    segs = [s for s in data.get("segments", []) if str(s.get("text", "")).strip()]
    if len(segs) < 2:
        raise RuntimeError("script JSON needs at least 2 segments with 'text'")
    data["segments"] = segs
    return data


# ---------------------------------------------------------------- voice
async def _tts(text, out, voice, rate):
    import edge_tts
    await edge_tts.Communicate(text, voice, rate=rate).save(str(out))


def _espeak(text, out):
    """Robotic offline fallback so the video still gets made."""
    exe = shutil.which("espeak-ng") or shutil.which("espeak")
    if not exe:
        return False
    wav = out.with_suffix(".wav")
    run([exe, "-v", "en-us", "-s", "165", "-w", str(wav), text])
    run([FFMPEG, "-y", "-i", str(wav), "-ar", "44100", str(out)])
    return True


def make_voice(text, out):
    voice = os.environ.get("REEL_VOICE", "en-IN-PrabhatNeural")
    rate = os.environ.get("REEL_RATE", "+8%")
    if os.environ.get("REEL_TTS") != "espeak":
        for attempt in range(3):
            try:
                asyncio.run(_tts(text, out, voice, rate))
                if out.exists() and out.stat().st_size > 1000:
                    return
            except Exception as e:  # network hiccup - retry
                log(f"edge-tts attempt {attempt + 1} failed: {str(e)[:120]}")
    if _espeak(text, out):
        log("using espeak-ng fallback voice")
        return
    raise RuntimeError("edge-tts failed and no espeak-ng fallback installed")


# ---------------------------------------------------------------- footage
def pexels_clip(query, out, used_ids):
    key = os.environ.get("PEXELS_API_KEY")
    if not key or not query:
        return False
    try:
        r = requests.get("https://api.pexels.com/videos/search",
                         headers={"Authorization": key},
                         params={"query": query, "orientation": "portrait",
                                 "size": "medium", "per_page": 15}, timeout=30)
        r.raise_for_status()
        videos = [v for v in r.json().get("videos", []) if v["id"] not in used_ids]
        random.shuffle(videos)
        for v in videos:
            files = [f for f in v.get("video_files", [])
                     if f.get("file_type") == "video/mp4" and (f.get("height") or 0) >= 1280]
            if not files:
                continue
            best = min(files, key=lambda f: f["height"])  # smallest that is still HD
            with requests.get(best["link"], stream=True, timeout=120) as dl:
                dl.raise_for_status()
                with open(out, "wb") as fh:
                    for chunk in dl.iter_content(1 << 20):
                        fh.write(chunk)
            used_ids.add(v["id"])
            return True
    except Exception as e:
        log(f"pexels '{query}' failed: {e}")
    return False


# ---------------------------------------------------------------- render
def caption_png(lines, font, fontsize, out):
    """Draw centred, outlined caption text on a transparent 1080x1920 PNG.
    Done in Python (Pillow) so it works with any ffmpeg build."""
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    f = ImageFont.truetype(font, fontsize)
    step = int(fontsize * 1.25)
    y = int(H * 0.60) - step * len(lines) // 2
    for line in lines:
        w = d.textlength(line, font=f)
        d.text(((W - w) / 2, y), line, font=f, fill="white",
               stroke_width=7, stroke_fill=(0, 0, 0, 235))
        y += step
    img.save(out)


def render_segment(i, seg, work, font, used_ids):
    text = str(seg["text"]).strip()
    caption = str(seg.get("caption") or text).strip()
    keywords = str(seg.get("keywords") or "").strip()

    audio = work / f"a{i:02d}.mp3"
    make_voice(text, audio)
    dur = duration(audio) + PAD

    # drop emoji / symbols the font can't draw, wrap, and centre each line
    caption = "".join(ch for ch in caption if ord(ch) < 0x2190).strip() or text
    lines = textwrap.wrap(caption, 20)[:5]

    clip = work / f"v{i:02d}.mp4"
    has_clip = pexels_clip(keywords, clip, used_ids) or pexels_clip(
        keywords.split()[0] if keywords else "", clip, used_ids)

    fontsize = 76 if i == 0 else 66  # hook a bit bigger
    png = work / f"c{i:02d}.png"
    caption_png(lines, font, fontsize, png)
    out = work / f"s{i:02d}.mp4"

    if has_clip:
        vin = ["-stream_loop", "-1", "-i", str(clip)]
        bg = (f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
              f"setsar=1,fps={FPS},eq=brightness=-0.06[bg]")
    else:
        c1, c2 = random.choice(GRADIENTS)
        vin = ["-f", "lavfi", "-i", f"gradients=s={W}x{H}:c0={c1}:c1={c2}:speed=0.004:type=linear:r={FPS}"]
        bg = "[0:v]setsar=1[bg]"
    # caption PNG is input 2; overlay keeps repeating its single frame
    vf = f"{bg};[bg][2:v]overlay=0:0:format=auto[v]"

    run([FFMPEG, "-y", *vin, "-i", str(audio), "-i", str(png),
         "-filter_complex", f"{vf};[1:a]apad=pad_dur={PAD},aresample=44100[a]",
         "-map", "[v]", "-map", "[a]", "-t", f"{dur:.3f}",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "128k", "-ac", "2", str(out)])
    log(f"segment {i + 1}: {dur:.1f}s {'(pexels)' if has_clip else '(gradient)'} - {caption[:40]}")
    return out


def build(script):
    if WORK_DIR.exists():
        shutil.rmtree(WORK_DIR)
    WORK_DIR.mkdir(parents=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    font = font_path()
    used = set()

    parts = [render_segment(i, s, WORK_DIR, font, used) for i, s in enumerate(script["segments"])]

    listfile = WORK_DIR / "list.txt"
    listfile.write_text("".join(f"file '{p}'\n" for p in parts))
    final = OUT_DIR / f"reel_{dt.date.today():%Y-%m-%d}.mp4"
    run([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(listfile),
         "-c", "copy", "-movflags", "+faststart", str(final)])
    log(f"done: {final} ({duration(final):.1f}s, {final.stat().st_size / 1e6:.1f} MB)")
    return final


# ---------------------------------------------------------------- main
def main():
    load_env()
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    send = "--no-send" not in sys.argv
    path = Path(args[0]).expanduser() if args else REELS_DIR / "today.json"

    try:
        script = load_script(path)
        video = build(script)
    except Exception as e:
        log(f"FAILED: {e}")
        if send:
            telegram("sendMessage", {"text": f"⚠️ Reel video failed today:\n{str(e)[:3500]}"})
        sys.exit(1)

    # keep only the last 7 videos on disk
    for old in sorted(OUT_DIR.glob("reel_*.mp4"))[:-7]:
        old.unlink()

    if send:
        cap = f"🎬 {script.get('title') or script.get('topic', 'Today’s reel')}\n\n{script.get('caption', '')}"
        with open(video, "rb") as fh:
            r = telegram("sendVideo", {"caption": cap[:1024], "supports_streaming": "true",
                                       "width": W, "height": H}, files={"video": fh})
        if r is not None and r.ok:
            log("sent to Telegram")


if __name__ == "__main__":
    main()
