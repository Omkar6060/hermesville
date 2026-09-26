#!/usr/bin/env python3
"""
gateway.py - the only part of Hermesville the internet can reach.

    phone app ──HTTPS──► Tailscale Funnel ──► gateway (127.0.0.1:8600)
                                                 ├── /auth/*          login: password + 2FA code
                                                 ├── /api/chat        ─► Hermes API   127.0.0.1:8642 (never public)
                                                 ├── /api/tracking/*  ─► tracker      127.0.0.1:8650 (never public)
                                                 └── /api/status      ─► ~/hermesville/status.json

Every /api/* call needs a session token from /auth/login. The Hermes master
key, Notion token and calendar address never leave this server.

One-time setup (run on the server):
    python3 gateway.py set-password     # choose your app password
    python3 gateway.py setup-2fa        # add the code to Google Authenticator
    python3 gateway.py logout-all       # sign out every device (rotates the session secret)
    python3 gateway.py                  # run (normally via systemd)

Settings live in ~/.hermes/.env:
    HV_PASSWORD_HASH, HV_TOTP_SECRET, HV_SESSION_SECRET   (written by the commands above)
    API_SERVER_KEY            Hermes API key (already there)
    API_SERVER_CORS_ORIGINS   your app's origin, e.g. https://<username>.github.io
    HV_SESSION_DAYS           optional, default 14
Standard library only (Python 3.9+).
"""
import base64
import getpass
import hashlib
import hmac
import json
import os
import re
import secrets
import struct
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ENV = Path.home() / ".hermes" / ".env"
HOME_DIR = Path.home() / "hermesville"
STATUS_FILE = HOME_DIR / "status.json"
REVOKED_FILE = HOME_DIR / "revoked_sessions.json"
PORT = 8600
HERMES = "http://127.0.0.1:8642"
TRACKER = "http://127.0.0.1:8650"
MAX_BODY = 256 * 1024


# ---------------------------------------------------------------- settings
def read_env():
    out = {}
    if ENV.exists():
        for line in ENV.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def set_env(name, value):
    ENV.parent.mkdir(parents=True, exist_ok=True)
    lines = ENV.read_text().splitlines() if ENV.exists() else []
    lines = [l for l in lines if not l.startswith(name + "=")] + [name + "=" + value]
    ENV.write_text("\n".join(lines) + "\n")
    os.chmod(ENV, 0o600)


# ---------------------------------------------------------------- crypto helpers
def b64u(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def unb64u(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def hash_password(pw):
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return "scrypt$%s$%s" % (b64u(salt), b64u(h))


def check_password(pw, stored):
    try:
        kind, salt, h = stored.split("$")
        if kind != "scrypt":
            return False
        test = hashlib.scrypt(pw.encode(), salt=unb64u(salt), n=2 ** 14, r=8, p=1, dklen=32)
        return hmac.compare_digest(test, unb64u(h))
    except Exception:
        return False


def totp(secret_b32, counter):
    key = base64.b32decode(secret_b32.upper() + "=" * (-len(secret_b32) % 8))
    mac = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    o = mac[-1] & 0x0F
    return "%06d" % ((struct.unpack(">I", mac[o:o + 4])[0] & 0x7FFFFFFF) % 1000000)


_last_totp = {"counter": -1}


def check_totp(secret_b32, code):
    code = re.sub(r"\s", "", code or "")
    if not re.fullmatch(r"\d{6}", code):
        return False
    now = int(time.time() // 30)
    for c in (now - 1, now, now + 1):
        if c > _last_totp["counter"] and hmac.compare_digest(totp(secret_b32, c), code):
            _last_totp["counter"] = c          # a code can't be reused
            return True
    return False


# ---------------------------------------------------------------- sessions
def load_revoked():
    try:
        return set(json.loads(REVOKED_FILE.read_text()))
    except Exception:
        return set()


REVOKED = load_revoked()


def make_token(secret, days):
    payload = b64u(json.dumps({"jti": secrets.token_urlsafe(12), "exp": int(time.time() + days * 86400)}).encode())
    sig = b64u(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())
    return payload + "." + sig


def read_token(secret, token):
    try:
        payload, sig = token.split(".")
        good = b64u(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(good, sig):
            return None
        data = json.loads(unb64u(payload))
        if data["exp"] < time.time() or data["jti"] in REVOKED:
            return None
        return data
    except Exception:
        return None


# ---------------------------------------------------------------- login rate limiting
FAILS, LOCK = {}, threading.Lock()


def too_many(ip):
    now = time.time()
    with LOCK:
        for k in list(FAILS):
            FAILS[k] = [t for t in FAILS[k] if now - t < 900]
            if not FAILS[k]:
                del FAILS[k]
        total = sum(len(v) for v in FAILS.values())
        return len(FAILS.get(ip, [])) >= 5 or total >= 30


def add_fail(ip):
    with LOCK:
        FAILS.setdefault(ip, []).append(time.time())


# ---------------------------------------------------------------- HTTP
class Gateway(BaseHTTPRequestHandler):
    server_version = "hermesville"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    # -- plumbing
    def cfg(self):
        return self.server.cfg

    def ip(self):
        return (self.headers.get("X-Forwarded-For") or self.client_address[0]).split(",")[0].strip()

    def cors(self):
        origin = (self.headers.get("Origin") or "").rstrip("/")
        allowed = [o.strip().rstrip("/") for o in self.cfg().get("API_SERVER_CORS_ORIGINS", "").split(",") if o.strip()]
        if origin and origin in allowed:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, OPTIONS")
            self.send_header("Access-Control-Max-Age", "600")

    def send(self, code, obj, raw=None):
        body = raw if raw is not None else json.dumps(obj).encode()
        self.send_response(code)
        self.cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            raise ValueError("request too large")
        return self.rfile.read(n) if n else b""

    def session(self):
        auth = self.headers.get("Authorization", "")
        tok = auth[7:] if auth.startswith("Bearer ") else ""
        data = read_token(self.cfg().get("HV_SESSION_SECRET", ""), tok) if tok else None
        if not data:
            self.send(401, {"error": "Please log in again."})
        return data

    def upstream(self, method, url, data=None, headers=None, timeout=30):
        req = urllib.request.Request(url, method=method, data=data)
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()
        except Exception as e:
            return 502, json.dumps({"error": "Service unavailable: %s" % type(e).__name__}).encode()

    # -- routes
    def do_OPTIONS(self):
        self.send_response(204)
        self.cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/health":
            return self.send(200, {"ok": True})
        if path == "/auth/check":
            s = self.session()
            return s and self.send(200, {"ok": True, "exp": s["exp"]})
        if path == "/api/status":
            if not self.session():
                return
            try:
                return self.send(200, None, raw=STATUS_FILE.read_bytes())
            except FileNotFoundError:
                return self.send(200, {"updated": None, "jobs": {}})
        if path.startswith("/api/tracking/"):
            if not self.session():
                return
            q = ("?" + self.path.split("?", 1)[1]) if "?" in self.path else ""
            code, raw = self.upstream("GET", TRACKER + "/api/" + path[len("/api/tracking/"):] + q,
                                      headers={"Authorization": "Bearer " + self.cfg().get("API_SERVER_KEY", "")})
            return self.send(code, None, raw=raw)
        self.send(404, {"error": "not found"})

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        try:
            raw = self.body()
        except ValueError as e:
            return self.send(413, {"error": str(e)})

        if path == "/auth/login":
            ip = self.ip()
            if too_many(ip):
                return self.send(429, {"error": "Too many attempts. Wait 15 minutes."})
            try:
                b = json.loads(raw or b"{}")
            except Exception:
                b = {}
            cfg = self.cfg()
            ok = check_password(str(b.get("password", "")), cfg.get("HV_PASSWORD_HASH", "")) and \
                check_totp(cfg.get("HV_TOTP_SECRET", ""), str(b.get("code", "")))
            if not ok:
                add_fail(ip)
                time.sleep(0.8)
                return self.send(401, {"error": "Wrong password or code."})
            days = float(cfg.get("HV_SESSION_DAYS", "14"))
            tok = make_token(cfg["HV_SESSION_SECRET"], days)
            return self.send(200, {"token": tok, "expires": int(time.time() + days * 86400)})

        if path == "/auth/logout":
            s = self.session()
            if s:
                REVOKED.add(s["jti"])
                HOME_DIR.mkdir(exist_ok=True)
                REVOKED_FILE.write_text(json.dumps(sorted(REVOKED)))
                self.send(200, {"ok": True})
            return

        if path == "/api/chat":
            if not self.session():
                return
            try:
                b = json.loads(raw)
                msgs = b.get("messages")
                assert isinstance(msgs, list) and 0 < len(msgs) <= 40
            except Exception:
                return self.send(400, {"error": "Send {\"messages\": [...]}"})
            body = json.dumps({"model": b.get("model") or "hermes-agent", "messages": msgs}).encode()
            code, out = self.upstream("POST", HERMES + "/v1/chat/completions", body, {
                "Authorization": "Bearer " + self.cfg().get("API_SERVER_KEY", ""), "Content-Type": "application/json"}, timeout=300)
            return self.send(code, None, raw=out)

        if path.startswith("/api/tracking/"):
            if not self.session():
                return
            code, out = self.upstream("POST", TRACKER + "/api/" + path[len("/api/tracking/"):], raw, {
                "Authorization": "Bearer " + self.cfg().get("API_SERVER_KEY", ""), "Content-Type": "application/json"})
            return self.send(code, None, raw=out)
        self.send(404, {"error": "not found"})

    def do_PATCH(self):
        path = self.path.split("?", 1)[0]
        if not path.startswith("/api/tracking/"):
            return self.send(404, {"error": "not found"})
        if not self.session():
            return
        code, out = self.upstream("PATCH", TRACKER + "/api/" + path[len("/api/tracking/"):], self.body(), {
            "Authorization": "Bearer " + self.cfg().get("API_SERVER_KEY", ""), "Content-Type": "application/json"})
        self.send(code, None, raw=out)

    def log_message(self, fmt, *args):
        if args and str(args[1] if len(args) > 1 else "").startswith(("4", "5")):
            sys.stderr.write("%s %s\n" % (self.ip(), fmt % args))


# ---------------------------------------------------------------- CLI
def cmd_set_password():
    while True:
        a = getpass.getpass("New app password (12+ characters): ")
        if len(a) < 12:
            print("Too short, use at least 12 characters.")
            continue
        if a != getpass.getpass("Repeat it: "):
            print("They don't match, try again.")
            continue
        break
    set_env("HV_PASSWORD_HASH", hash_password(a))
    print("Password saved (only a scrypt hash is stored).")


def cmd_setup_2fa():
    secret = base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")
    print("\nIn Google Authenticator: + → Enter a setup key")
    print("  Account : Hermesville")
    print("  Key     : %s" % " ".join(secret[i:i + 4] for i in range(0, len(secret), 4)))
    print("  Type    : Time based\n")
    print("(or open this link on the phone: otpauth://totp/Hermesville?secret=%s&issuer=Hermesville)\n" % secret)
    for _ in range(3):
        code = input("Type the 6-digit code the app shows now: ").strip()
        now = int(time.time() // 30)
        if any(totp(secret, c) == code for c in (now - 1, now, now + 1)):
            set_env("HV_TOTP_SECRET", secret)
            print("2FA is on.")
            return
        print("That code didn't match, try the next one.")
    print("2FA not saved. Run setup-2fa again.")
    sys.exit(1)


def cmd_logout_all():
    set_env("HV_SESSION_SECRET", secrets.token_urlsafe(32))
    print("Every device is signed out. Restart: systemctl --user restart hermesville-gateway")


def main():
    if len(sys.argv) > 1:
        {"set-password": cmd_set_password, "setup-2fa": cmd_setup_2fa, "logout-all": cmd_logout_all}.get(
            sys.argv[1], lambda: print(__doc__))()
        return
    cfg = read_env()
    missing = [k for k in ("HV_PASSWORD_HASH", "HV_TOTP_SECRET", "API_SERVER_KEY", "API_SERVER_CORS_ORIGINS") if not cfg.get(k)]
    if missing:
        sys.exit("Missing in ~/.hermes/.env: %s  (run set-password / setup-2fa first)" % ", ".join(missing))
    if not cfg.get("HV_SESSION_SECRET"):
        set_env("HV_SESSION_SECRET", secrets.token_urlsafe(32))
        cfg = read_env()
    srv = ThreadingHTTPServer(("127.0.0.1", int(cfg.get("HV_GATEWAY_PORT", PORT))), Gateway)
    srv.cfg = cfg
    print("Hermesville gateway on 127.0.0.1:%d" % srv.server_address[1], flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
