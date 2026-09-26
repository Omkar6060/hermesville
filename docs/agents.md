# The starter agents

Hermesville ships with three example agents. Each one is a Hermes scheduled job
(or a small script) plus a building in the city. Create the jobs by messaging
your Hermes bot on Telegram in plain English; Hermes turns them into scheduled
tasks. Times use your server's time zone (`sudo timedatectl set-timezone <Your/Zone>`).

The last lines of each prompt make the job report to Hermesville, so its
building lights up while it runs and fills with smoke if it fails.

## Writers' Studio: daily reel script (07:00)

```bash
mkdir -p ~/reels && touch ~/reels/history.txt
```

Send your bot:

```
Create a scheduled job that runs every day at 7am and delivers to this Telegram chat. First run: python3 ~/hermesville/report_status.py writer running. Then write one Instagram Reel script (30-45 seconds) about a surprising, true fact from technology, mathematics or science. Read ~/reels/history.txt and pick a topic NOT listed there, rotating between tech, maths and science. Only use facts you are confident are accurate. Save the script as JSON to ~/reels/today.json (overwrite it) with exactly this structure: {"topic": "...", "title": "short title", "segments": [{"text": "one spoken sentence", "caption": "max 6 words of on-screen text, no emoji", "keywords": "2-3 word stock video search term for something visual and literal"}], "caption": "Instagram caption with 5 hashtags"}. Use 5 to 7 segments: the first is the hook, the last is the closer. Append today's date and topic as one line to ~/reels/history.txt. Finally run: python3 ~/hermesville/report_status.py writer done "<topic>" and reply with the title and the spoken script. If anything fails, run: python3 ~/hermesville/report_status.py writer failed "<short reason>".
```

## Film Studio: reel video (07:10)

Not an LLM job, just a script: it turns `today.json` into a 1080×1920 video
with a neural voice, stock footage and captions, then sends it to Telegram.

```bash
cd hermesville/automations/reel-video
bash setup.sh                                   # Python venv, ffmpeg, fonts, 07:10 timer
echo 'PEXELS_API_KEY=your_key' >> ~/.hermes/.env # free key from pexels.com/api
bash ../../server/install_reporter.sh           # report film running / done / failed
systemctl --user start reel-video.service       # test it now
```

## Newsroom: AI news digest (08:00)

Needs web search: add `FIRECRAWL_API_KEY=fc-...` (free plan at firecrawl.dev)
to `~/.hermes/.env`, then `systemctl --user restart hermes-gateway`. Send your bot:

```
Create a scheduled job that runs every day at 8am and delivers to this Telegram chat. First run: python3 ~/hermesville/report_status.py news running. Then search the web for the most important AI news from the last 24 hours: model releases, major product launches, research breakthroughs, funding and regulation. Ignore rumours and duplicates. Pick the top 5 stories. For each give a bold headline, a 2-sentence summary in simple English, one line on why it matters, and the source link. Then write a 60-second YouTube Shorts script covering the top 3 stories. Finally run: python3 ~/hermesville/report_status.py news done "5 stories", or if anything fails: python3 ~/hermesville/report_status.py news failed "<short reason>".
```

## Managing jobs

```bash
hermes cron list              # all jobs and their ids
hermes cron run <id>          # run one now
hermes cron pause <id>        # pause / resume <id>
hermes cron runs              # history
```

## Adding your own building

The city and the command center are configured by three lists near the top
of the script in `index.html`:

| List | What it controls |
|---|---|
| `AGENTS` | name, schedule (`start` in minutes after midnight), how long it works, who it delivers to, colours and card text |
| `LM` | where the landmark stands (`block: [col, row]` on the 6×6 grid), height and colours |
| `CC` | the command-center tile: label, suggested questions, and the context Hermes gets for that thread |

Give the new agent an id, add it to all three, add its id to `JOBS` in
`server/report_status.py`, and call `report_status.py <id> running|done|failed`
from its job.
