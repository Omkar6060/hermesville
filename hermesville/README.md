# Hermesville

A cartoon town where my AI agents live and work. Every automation I run with [Hermes Agent](https://hermes-agent.nousresearch.com/) on an Oracle Cloud free-tier server gets its own building, and the workers act out what the agent is doing: writing, filming, reporting the news, and flying finished work to Telegram as paper planes.

![Hermesville showing the morning run](docs/screenshot.png)

## The town

| Building | Agent | Runs (IST) | What it does |
|---|---|---|---|
| Writers' Studio | Reel script writer | Daily 07:00 | Picks a fresh tech, maths or science fact and writes an Instagram Reel script |
| Film Studio | Reel video factory | Daily 07:10 | Turns the script into a 1080×1920 video with voiceover, stock footage and captions |
| Newsroom | AI news digest | Daily 08:00 | Scans the last 24 hours of AI news and writes a top-5 digest plus a Shorts script |
| Post Office | Telegram delivery | Always open | Sends everything finished to my phone |
| Empty lot | Next agent | Planned | A crane waits for the job search helper |

## How the morning works

```
07:00  Hermes (cron)  ──► writes script ──► ~/reels/today.json
07:10  make_reel.py   ──► edge-tts voice + Pexels clips + captions ──► ffmpeg ──► reel.mp4
                      ──► Telegram Bot API ──► my phone
08:00  Hermes (cron)  ──► web search ──► AI news digest ──► Telegram
```

## Run the town

The page is a single HTML file with no build step.

- **Locally:** open `index.html` in a browser.
- **GitHub Pages:** Settings → Pages → Deploy from branch → `main` / root. The town is then live at `https://<username>.github.io/hermesville/`.

**Replay this morning** plays 06:55 to 08:15 in about a minute. **Live now** follows the real IST clock, with day and night in the sky. Click the timeline to jump to any moment.

Right now each building's status is simulated from its schedule.

## The reel video factory

`automations/reel-video/` holds the pipeline behind the Film Studio.

| File | Purpose |
|---|---|
| `make_reel.py` | Reads the day's script JSON, generates the voice (edge-tts), downloads matching stock clips (Pexels API), draws captions, cuts the vertical video with ffmpeg and sends it to Telegram |
| `setup.sh` | One-shot installer for Oracle Linux (ARM or x86): Python venv, static ffmpeg, fonts and a systemd timer at 07:10 |

Secrets are read from `~/.hermes/.env` on the server and are never stored in this repo:

```
TELEGRAM_BOT_TOKEN=...
TELEGRAM_ALLOWED_USERS=...
PEXELS_API_KEY=...
```

## Stack

- **Agent:** Hermes Agent by Nous Research, using Claude Sonnet 5
- **Server:** Oracle Cloud Always Free, Ampere A1 (ARM), Oracle Linux
- **Video:** edge-tts, Pexels API, Pillow, ffmpeg
- **Delivery:** Telegram Bot API
- **Town:** plain HTML, CSS and Canvas 2D, with no framework

## Roadmap

- [ ] Live status: the server reports each run, so a failed job shows smoke over its building
- [ ] Job search helper moves into the empty lot
- [ ] Better voice and word-by-word animated captions for the reels
- [ ] Night shift: workers go home and lights switch off after the last job
- [ ] Click a building to see its last output

## License

MIT, see [LICENSE](LICENSE).
