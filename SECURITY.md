# Security

Hermesville gives a web app control over an AI agent that can run commands
on your server. Treat your deployment like a remote shell.

## Design

- **Public:** only the static app (GitHub Pages) and the gateway's login endpoint.
  The app contains no data and no keys; without a login it shows a login screen.
- **Private (127.0.0.1 only):** the Hermes API server and the tracker. They are
  never published; the gateway calls them from inside the server.
- **Login:** password stored as a scrypt hash, plus a TOTP code (RFC 6238, codes
  can't be reused). 5 failed attempts per address (30 overall) lock logins for 15 minutes.
- **Sessions:** HMAC-signed tokens, 14 days by default, revocable one by one
  (Log out) or all at once (`gateway.py logout-all`).
- **Agent builder:** only a logged-in session can create, run, pause or delete agents. The gateway calls `hermes cron` with an argument list (no shell), validates names and schedules, and caps the city at 12 agents.
- **Calendar writing:** optional. It uses a Google service account that can only edit calendars you explicitly share with it. Its key stays in `~/hermesville/gcal-sa.json` (mode 600) and is used to sign short-lived tokens with `openssl`.
- **Secrets** (model API key, Telegram token, Hermes key, Notion token, calendar
  address) live only in `~/.hermes/.env` on the server, mode 600.

## Your checklist

- Never commit `.env`, keys, tokens, screenshots of them, or your server address.
- Keep `TELEGRAM_ALLOWED_USERS` set so only you can talk to your bot.
- Use a password of 12+ characters that you don't use anywhere else.
- Save the 2FA setup key somewhere offline (a password manager) in case you lose your phone.
- Keep Hermes's approval mode on for risky commands: `hermes config set approval_mode ask`.
- Set a monthly spend limit with your model provider.
- Lost your phone? On the server: `python3 ~/hermesville/gateway.py logout-all && systemctl --user restart hermesville-gateway`,
  then `python3 ~/hermesville/gateway.py setup-2fa` to issue a new 2FA secret.
- Keep the server updated (`sudo apt upgrade` or `sudo dnf update`) and update Hermes as its docs describe.

## Reporting a vulnerability

Please don't open a public issue. Use GitHub's **Security → Report a vulnerability**
on this repository, with steps to reproduce. I'll reply as soon as I can.
