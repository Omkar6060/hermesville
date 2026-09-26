# Hermesville

> **Early project, built while learning.** Hermesville works, but it's still
> changing: expect rough edges, breaking changes between versions, and setup
> steps that may need adjusting for your server. Issues and suggestions are welcome.
>
> **It's a web app, not a native mobile app.** There's nothing to download from
> the Play Store or App Store. It runs in your browser and can be added to your
> home screen, where it opens full screen like an app (a PWA).

**Your AI agents, living in a city.** Hermesville is a private web app for
[Hermes Agent](https://hermes-agent.nousresearch.com/) running on your own
server. Every automation is a building: you watch the workers write, film and
deliver your morning to Telegram, tap a building to chat with that agent, and
keep your Google Calendar and Notion in one screen. Everything sits behind a
password and a 2FA code.

![Hermesville: the city, the command center and My Tracking](docs/screenshot.png)

- **City:** an animated isometric town. Each agent is a landmark that lights up while it works and fills with smoke when a job fails.
- **Command:** a green field terminal. Pick an agent, or tap its building, and message it. Each agent keeps its own thread.
- **Build agents from your phone:** describe one in a sentence and Hermes drafts it, or fill in the name, schedule and instructions yourself. It becomes a Hermes scheduled job, gets its own building, and can be run, paused or deleted from the app.
- **My Tracking:** today, tomorrow or 7 days of Google Calendar, plus a Notion database you can tick off and add to.
- **Plan with Hermes:** ask for something like *"Build me a Dynatrace Associate study schedule"*. Hermes drafts dated sessions; you review them and save the plan as a Notion page with a checklist, as Notion tasks, and as Google Calendar events.
- **Private by design:** the app is public but empty. Your data, keys and agents stay on your server behind a login with 2FA.
- **Free to run:** Oracle Cloud's Always Free server, free Tailscale, GitHub Pages, and free model tiers if you want them.

---

## Contents

1. [How it works](#how-it-works)
2. [What you need](#what-you-need)
3. [Setup](#setup), about 60–90 minutes the first time
   1. [Fork the repo and turn on GitHub Pages](#1-fork-the-repo-and-turn-on-github-pages)
   2. [Get a server](#2-get-a-server)
   3. [Connect with SSH](#3-connect-with-ssh)
   4. [Install Hermes and choose a model](#4-install-hermes-and-choose-a-model)
   5. [Connect Telegram](#5-connect-telegram)
   6. [Install the Hermesville back end (password, 2FA, Tailscale)](#6-install-the-hermesville-back-end)
   7. [Log in and add it to your home screen](#7-log-in-and-add-it-to-your-home-screen)
   8. [Optional: Google Calendar and Notion](#8-optional-google-calendar-and-notion)
      - [8b. Let Hermes add plans to your calendar](#8b-let-hermes-add-plans-to-your-calendar)
   9. [Optional: the starter agents](#9-optional-the-starter-agents)
   10. [Build your own agents from the app](#10-build-your-own-agents-from-the-app)
4. [Security](#security)
5. [Day-to-day commands](#day-to-day-commands)
6. [Troubleshooting](#troubleshooting)
7. [Project layout](#project-layout)
8. [Roadmap](#roadmap) · [Contributing](#contributing) · [License](#license)

---

## How it works

```
 Your browser (Hermesville web app, from GitHub Pages: public, holds no data)
        │  HTTPS
        ▼
 Tailscale Funnel ── https://<name>.<tailnet>.ts.net
        │
        ▼
 ┌──────────────────────── your server ────────────────────────┐
 │  gateway.py   :8600  ← the ONLY public service              │
 │     ├─ /auth/login     password + 2FA code → session token  │
 │     ├─ /api/chat       → Hermes API server   127.0.0.1:8642 │
 │     ├─ /api/tracking/* → tracker.py          127.0.0.1:8650 │
 │     ├─ /api/plan/draft → Hermes drafts a dated schedule      │
 │     ├─ /api/status     → ~/hermesville/status.json          │
 │     └─ /api/agents     → `hermes cron` (build/run/pause)    │
 │                                                             │
 │  Hermes Agent ── Telegram bot, scheduled jobs, your model   │
 └─────────────────────────────────────────────────────────────┘
```

The app is a single static HTML file. Everything private (the model key,
Telegram token, Hermes key, Notion token, calendar address and job status)
stays in `~/.hermes/.env` and `~/hermesville/` on your server. The phone only
keeps a session token that expires.

## What you need

| | Free option | Notes |
|---|---|---|
| **Server** | Oracle Cloud Always Free (Ampere A1, up to 4 CPUs / 24 GB RAM) | Any Linux VM, VPS or spare PC works: Ubuntu 22.04/24.04 or Oracle Linux 8/9, 2 GB+ RAM |
| **AI model** | OpenRouter free models, Google Gemini free tier, Groq, NVIDIA NIM | Or paid: Anthropic, OpenAI, Nous Portal |
| **HTTPS address** | Tailscale (free personal plan) | No domain and no open ports needed |
| **App hosting** | GitHub Pages | Free for public repositories |
| **Messages** | Telegram bot | Free |
| **Browser** | Any modern browser | Chrome, Edge, Safari or Firefox, on a phone or a computer |
| **2FA** | An authenticator app | Google Authenticator, Microsoft Authenticator, Authy, 2FAS, … |

---

## Setup

Commands marked **(server)** run on your server over SSH. Commands marked
**(PC)** run on your own computer.

### 1. Fork the repo and turn on GitHub Pages

1. Click **Fork** at the top of this page.
2. In your fork, go to **Settings → Pages**: **Deploy from a branch**, `main`, `/ (root)`, then **Save**.
3. A minute later your app is at `https://<your-username>.github.io/hermesville/`.
   It shows a login screen; you'll have something to log in to after step 6.

`index.html` must sit at the top level of the repo. If Pages shows a 404, see
[Troubleshooting](#troubleshooting).

### 2. Get a server

**Oracle Cloud Always Free** (recommended if you don't have a server):

1. Sign up at **oracle.com/cloud/free**. Your card is checked, not charged.
   Pick your **home region** carefully, because it can't be changed. Busy regions often run out of free ARM machines.
2. **Menu → Compute → Instances → Create instance**:
   - **Image:** Canonical **Ubuntu 24.04**. This guide also works on Oracle Linux, where the user is `opc` instead of `ubuntu`.
   - **Shape:** Ampere → **VM.Standard.A1.Flex**, **2 OCPU / 12 GB** or up to 4 / 24.
   - **Networking:** create a new VCN and a public subnet, and **Assign a public IPv4 address**.
   - **SSH keys:** **Generate a key pair for me**, then **Save private key**. Don't lose it.
   - **Boot volume:** 50 GB.
3. When it shows **Running**, copy the **public IP address**.

If you see "Out of capacity", try another Availability Domain or try again at
a different time of day. Oracle may reclaim Always Free machines that stay
nearly idle for a week. Upgrading the account to Pay-As-You-Go stops this, and
you still pay nothing within the free limits.

**Any other VM or PC:** use Ubuntu or Oracle Linux, a normal user with `sudo`,
and outbound internet access. No inbound ports are needed.

### 3. Connect with SSH

**(PC) Windows (PowerShell):**

```powershell
mkdir $env:USERPROFILE\.ssh -Force
move $env:USERPROFILE\Downloads\ssh-key-*.key $env:USERPROFILE\.ssh\server.key
icacls $env:USERPROFILE\.ssh\server.key /inheritance:r
icacls $env:USERPROFILE\.ssh\server.key /grant:r "$($env:USERNAME):(R)"
ssh -i $env:USERPROFILE\.ssh\server.key ubuntu@<PUBLIC_IP>
```

In Command Prompt instead of PowerShell, use `%USERPROFILE%` and `%USERNAME%`.

**(PC) macOS or Linux:**

```bash
chmod 600 ~/Downloads/ssh-key-*.key
ssh -i ~/Downloads/ssh-key-*.key ubuntu@<PUBLIC_IP>
```

**(server)** Update it and set your time zone. Your agents' schedules use it.

```bash
sudo apt update && sudo apt upgrade -y                   # Oracle Linux: sudo dnf update -y
sudo apt install -y git curl openssl python3             # Oracle Linux: sudo dnf install -y git curl openssl python3
sudo timedatectl set-timezone Asia/Kolkata               # use your own zone, e.g. Europe/Berlin
```

### 4. Install Hermes and choose a model

**(server)**

```bash
curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash
source ~/.bashrc
hermes setup
```

The setup wizard asks for a **model provider** and key. Pick one:

| Provider | Cost | How to get a key | Good to know |
|---|---|---|---|
| **OpenRouter** | Free models (tagged `:free`) or pay per use | openrouter.ai → Keys | Free models have daily limits; agents use many calls per task |
| **Google Gemini** | Free tier | aistudio.google.com → Get API key | Use the custom OpenAI-compatible endpoint `https://generativelanguage.googleapis.com/v1beta/openai/` |
| **Groq** / **NVIDIA NIM** | Free tiers | console.groq.com · build.nvidia.com | Custom OpenAI-compatible endpoint; pick a model that supports tool calling |
| **Anthropic (Claude)** | Paid | console.anthropic.com → API Keys | Strong at tool use; set a monthly spend limit |
| **OpenAI**, **Nous Portal** | Paid | their consoles | Supported directly by Hermes |

Agents need a model that handles **tool calling** well. If a free model keeps
describing what it would do instead of doing it, try another. Model names must
be exact: the easiest way is to run `hermes`, type `/model` and pick from the
list.

Test it:

```bash
hermes            # type a question, then /exit
hermes config set approval_mode ask   # asks before running risky commands
```

### 5. Connect Telegram

1. In Telegram, message **@BotFather** → `/newbot` and copy the **token**.
2. Message **@userinfobot** and copy your numeric **user id**.
3. **(server)**

```bash
hermes gateway setup                      # choose Telegram, paste the token and your user id
chmod 600 ~/.hermes/.env
hermes gateway install
sudo loginctl enable-linger $USER         # keeps it running after you close SSH
systemctl --user enable --now hermes-gateway
```

Message your bot. It should answer. `TELEGRAM_ALLOWED_USERS` makes sure it
only answers you.

### 6. Install the Hermesville back end

This step sets your **password**, turns on **2FA**, and publishes the private
back end through **Tailscale**.

**(server)**

```bash
git clone https://github.com/<your-username>/hermesville.git
cd hermesville
bash server/install.sh https://<your-username>.github.io
```

The script walks you through it:

1. **Hermes API server** is turned on for `127.0.0.1` only, with a random key.
2. **Tracker** (Calendar + Notion) is installed, also on `127.0.0.1` only.
3. **Password:** choose one with 12+ characters. Only a scrypt hash is stored.
4. **2FA:** open your authenticator app, tap **+ → Enter a setup key**, name it
   `Hermesville`, type the key the script shows (time-based), then type the
   6-digit code back into the server to confirm.
   **Save that setup key in a password manager**, because it's your backup if you lose your phone.
5. **Tailscale:** open the link it prints and sign in (free). If it prints a
   second link to **enable Funnel**, approve it and run the script again.
6. **Checks from the internet side.** You should see:

```
/health                    200 (want 200)
/api/status                401 (want 401)
/api/tracking/summary      401 (want 401)
/v1/models                 404 (want 404)
All private parts are private.
```

At the end it prints your **server address**, e.g. `https://hermesville.tailXXXX.ts.net`.
Keep it to yourself.

To change your password or 2FA later:

```bash
python3 ~/hermesville/gateway.py set-password
python3 ~/hermesville/gateway.py setup-2fa
systemctl --user restart hermesville-gateway
```

### 7. Log in and add it to your home screen

1. Open `https://<your-username>.github.io/hermesville/` in your browser, on a phone or a computer.
2. Enter your **server address**, **password** and the current **2FA code**.
3. Optional: add it to your home screen so it opens full screen like an app.
   This is a shortcut to the web app, not an app-store install.
   - **Android (Chrome):** ⋮ → **Install app** or **Add to Home screen**. Make sure **Desktop site** is unticked.
   - **iPhone (Safari):** Share → **Add to Home Screen**.
   - **Desktop (Chrome/Edge):** the install icon in the address bar.

Because it's a web app, it needs a network connection to your server,
it can't send push notifications (Telegram does that job), and updates arrive
automatically when you push to GitHub.

Sessions last 14 days. **Command → POWER → Log out** ends yours.

### 8. Optional: Google Calendar and Notion

**Google Calendar:** open calendar.google.com, then ⚙ **Settings** → your calendar →
**Integrate calendar** → copy **Secret address in iCal format**. It must contain
`private-` and end in `/basic.ics`; the *public* address gives a 404.

**Notion:**

1. Go to notion.so/profile/integrations → **New integration** and copy the secret (`ntn_…`).
2. Open your notes database → **•••** → **Connections** → add your integration.
3. Copy the 32-character database id from its link (the part before `?v=`).

The database needs a **Checkbox** or **Status** column for ticking. A **Date**
column is optional and is used for due dates.

**(server)**

```bash
nano ~/.hermes/.env      # add these lines:
# GCAL_ICS_URL=https://calendar.google.com/calendar/ical/.../basic.ics
# NOTION_TOKEN=ntn_...
# NOTION_DB_ID=...
systemctl --user restart hermesville-tracker
```

Tap **Refresh** in **My Tracking**. For several calendars, separate their
addresses with commas.

**Plan with Hermes:** in **My Tracking**, describe what you want to plan, e.g.
*"Build me a 4-week Dynatrace Associate study schedule"* or *"A beginner 5k running
plan"*. Then pick a start date, time, session length and days, and tap **Draft plan**.
Hermes returns dated sessions, each with a topic and what to do. Remove any you
don't want, then choose where to save it:

- **Create a Notion page with a checklist:** one page in your database, grouped by week.
- **Add each session as a Notion task:** each one has its date, so it appears in the notes list.
- **Add every session to Google Calendar:** needs step 8b.

#### 8b. Let Hermes add plans to your calendar

The secret iCal address is read-only. To create events, give the server a Google
**service account**, a robot account that can edit only the calendars you share
with it. It's free.

1. Go to **console.cloud.google.com** → create a project (e.g. `hermesville`) →
   **APIs & Services → Library** → enable **Google Calendar API**.
2. **IAM & Admin → Service Accounts → Create service account** (name it `hermesville`,
   skip the roles) → open it → **Keys → Add key → Create new key → JSON**. A `.json` file downloads.
3. In **Google Calendar → Settings →** your calendar **→ Share with specific people**,
   add the service account's email (`hermesville@<project>.iam.gserviceaccount.com`)
   with **Make changes to events**.
4. Copy the key to your server and lock it down:

```bash
# (PC)
scp -i <your-ssh-key> hermesville-*.json <user>@<server-ip>:~/hermesville/gcal-sa.json
# (server)
chmod 600 ~/hermesville/gcal-sa.json
echo "GCAL_SA_FILE=$HOME/hermesville/gcal-sa.json" >> ~/.hermes/.env
echo 'GCAL_CALENDAR_ID=you@gmail.com' >> ~/.hermes/.env     # Settings → Integrate calendar → Calendar ID
systemctl --user restart hermesville-tracker
```

The **Add every session to Google Calendar** box becomes active. Events are
tagged `hermesville` so you can find them. Google can take a few hours to show
new events through the iCal address, so they may appear in the app later than
in Google Calendar itself.

### 9. Optional: the starter agents

[`docs/agents.md`](docs/agents.md) has copy-paste prompts and scripts for the
three agents in the demo:

- **Writers' Studio** writes a daily reel script (07:00).
- **Film Studio** turns it into a 1080×1920 video with voice, stock clips and captions, and sends it to Telegram (07:10).
- **Newsroom** sends an AI news digest (08:00).

It also explains how to add your own buildings in code.

### 10. Build your own agents from the app

Open **Command → + Build an agent**. There are two ways:

- **Describe it:** write what it should do and when, e.g. *"Every weekday at 9am,
  check the weather in my city and tell me if I need an umbrella"*. Hermes drafts a
  name, a schedule and full instructions. Nothing is created until you review the
  draft and tap **Create agent**.
- **Build it yourself:** fill in the name, when it runs (`every day at 8am`,
  `weekdays at 9:30am`, `every 2h`, `every monday at 10am`, or a cron expression)
  and its instructions.

On **Create agent**, the gateway runs `hermes cron create … --name hv-<id> --deliver telegram`
on your server. The job reports to the city automatically: its building lights up
while it runs and fills with smoke if it fails. You can then:

- **Talk to it** from its Command tile. The thread knows its schedule and instructions.
- **Run now, Pause/Resume or Delete** it from the **Agents** tab.
- Manage it on the server too: `hermes cron list` shows it as `hv-<id>`.

Write instructions as if the agent has no memory: say exactly what to check and
how the Telegram message should look. The city has room for 12 app-built agents.
Anything an agent does runs on your server with Hermes's permissions, so only
create agents you understand, and keep `approval_mode` on.

---

## Security

The app is public but holds nothing. Everything that matters stays on your server.

| | Where it lives | Who can reach it |
|---|---|---|
| App code (`index.html`) | GitHub Pages | Everyone; it shows a login screen and contains no keys |
| Gateway (`:8600`) | Your server, published via Tailscale Funnel | Everyone can reach the login; everything else needs a session |
| Hermes API (`:8642`), tracker (`:8650`) | Your server, `127.0.0.1` only | Only the gateway |
| Keys, tokens, calendar address | `~/.hermes/.env` (mode 600) | Only your server user |
| Job status | `~/hermesville/status.json` | Only after login |

- **Login:** password (scrypt) plus TOTP 2FA. A code can't be reused, and 5 wrong tries lock logins for 15 minutes.
- **Sessions:** signed, expire after 14 days, revocable.
- **Lost your phone?** Run `python3 ~/hermesville/gateway.py logout-all && systemctl --user restart hermesville-gateway` to sign out every device, then `setup-2fa` for a new code.
- **Never commit** `~/.hermes/.env`, keys, screenshots of keys, or your server address. The `.gitignore` blocks the common file names, but check before you push.
- **Check your git history** before making a fork public: `git log -p | grep -iE "sk-ant|sk-or|ntn_|github_pat|API_SERVER_KEY|BOT_TOKEN"` should print nothing.

See [SECURITY.md](SECURITY.md) for the full checklist and how to report a vulnerability.

---

## Day-to-day commands

```bash
# status of everything
systemctl --user status hermes-gateway hermesville-gateway hermesville-tracker

# live logs
journalctl --user -u hermes-gateway -f
journalctl --user -u hermesville-gateway -f

# after editing ~/.hermes/.env
systemctl --user restart hermes-gateway hermesville-tracker hermesville-gateway

# scheduled jobs
hermes cron list            # app-built agents show up as hv-<name>
hermes cron run <id>

# what the internet can see
tailscale funnel status

# report a job's state to the city (from any script)
python3 ~/hermesville/report_status.py writer running|done|failed "note"
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| SSH: `Permission denied (publickey)` | Wrong user. Ubuntu images use `ubuntu`, Oracle Linux uses `opc`. Check the key file too |
| SSH: `UNPROTECTED PRIVATE KEY FILE` (Windows) | Run the two `icacls` lines from step 3 again |
| Hermes: `HTTP 404: model: …` | The model name is wrong. Pick it with `/model` inside `hermes`, then `systemctl --user restart hermes-gateway` |
| Telegram: `Unknown command /cron` | Ask for schedules in plain English ("Create a scheduled job that runs every day at 7am…"), or use `hermes cron` on the server |
| Bot stops after you close SSH | `sudo loginctl enable-linger $USER` |
| GitHub Pages 404 | `index.html` must be at the top level of the repo, not inside a folder. Check **Actions** for a green deploy |
| Phone shows the desktop layout | In Chrome, untick ⋮ → **Desktop site** |
| App looks like an old version | Close it fully and reopen it twice. The version number is under **Command → POWER** |
| Login: "Can't reach that server" | Use the exact `https://…ts.net` address from step 6; check `systemctl --user status hermesville-gateway` and `tailscale funnel status` |
| Login: "Too many attempts" | Wait 15 minutes. Check the clock on your phone and server: 2FA codes depend on the time |
| Calendar: 404 | You copied the public address. Use **Secret address in iCal format** (contains `private-`) |
| Notion error | Share the database with your integration (**••• → Connections**) and check `NOTION_DB_ID` |
| Reel video: `No such filter: drawtext` | Already handled: captions are drawn with Pillow. Update `make_reel.py` |
| Build an agent: "hermes command not found" | The gateway can't find the `hermes` binary. Add `HERMES_BIN=/full/path/to/hermes` (from `which hermes`) to `~/.hermes/.env` and restart `hermesville-gateway` |
| Build an agent: "not in the expected format" | The model didn't return clean JSON. Try again, pick a stronger model, or use **Build it yourself** |
| Plan: "Add to Google Calendar (not set up yet)" | Finish step 8b and restart `hermesville-tracker` |
| Plan: `Google said 403` / `404` | Share the calendar with the service account (**Make changes to events**) and check `GCAL_CALENDAR_ID` |
| Plan events missing in the app | They're in Google Calendar already; the iCal address can lag a few hours |

---

## Project layout

```
index.html              the whole web app: city, command center, My Tracking, login
manifest.webmanifest    "add to home screen" metadata
sw.js                   service worker: loads the newest version, works offline
icons/                  app icons
server/
  install.sh            one-shot private back end: Hermes API, tracker, password, 2FA, Tailscale
  gateway.py            login + 2FA + sessions; the only public service
  tracker.py            Google Calendar (iCal) + Notion, 127.0.0.1 only
  report_status.py      jobs call this to update their building
  install_reporter.sh   hooks the reel video job into report_status
automations/reel-video/ the Film Studio pipeline (edge-tts, Pexels, Pillow, ffmpeg)
docs/agents.md          starter agent prompts and how to add buildings
docs/env.example        every setting explained (the real file stays on your server)
```

The server code uses only Python's standard library, with nothing to `pip install`.

## Known limitations

- **Web app only.** No Play Store or App Store version, and no push notifications; Telegram delivers alerts.
- **One user.** One password and one 2FA secret per server; there are no separate accounts.
- **Needs your server online.** Without it, the app shows the login screen or an offline badge.
- **Simulated city.** Buildings show real job status only for jobs that call `report_status.py` (app-built agents do this automatically); the starter agents otherwise follow their schedule.
- **Tested setups:** Oracle Cloud Ampere A1 with Oracle Linux 9 and Ubuntu 24.04, Chrome on Android and desktop. Other setups may need small changes.
- **Early software.** Written while learning. Review the code before trusting it with anything important.

## Roadmap

- [x] Isometric city with live job status
- [x] Command center: tap a building to message that agent
- [x] My Tracking: Google Calendar + Notion
- [x] Private back end with password + 2FA
- [x] Build agents from the app (describe it or build it yourself)
- [x] Plan with Hermes: schedules saved to Notion and Google Calendar
- [ ] Undo a saved plan (remove its events and tasks)
- [ ] Click a building to see its last output
- [ ] Night shift: workers go home after the last job
- [ ] Passkey login
- [ ] More starter agents (job search helper is next)

## Contributing

Issues and pull requests are welcome. Please keep the server code
dependency-free, never add anything that publishes the Hermes API directly,
and report security problems privately (see [SECURITY.md](SECURITY.md)).

## License

MIT, see [LICENSE](LICENSE). Hermes Agent is a separate project by
[Nous Research](https://nousresearch.com/) with its own license.
