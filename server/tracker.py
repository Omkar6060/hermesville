#!/usr/bin/env python3
"""
tracker.py - the "My Tracking" backend for Hermesville.

Reads your Google Calendar (private iCal address) and a Notion database,
and serves them to the Hermesville app as JSON. Keys and addresses stay on
this server; the app only gets the data, and only with your API key.

Config (in ~/.hermes/.env):
    API_SERVER_KEY           same key the command center uses
    API_SERVER_CORS_ORIGINS  e.g. https://<username>.github.io
    GCAL_ICS_URL             Google Calendar "Secret address in iCal format"
                             (several calendars: separate with commas)
    NOTION_TOKEN             Notion internal integration secret (ntn_... / secret_...)
    NOTION_DB_ID             the Notion database to show and add notes to
    GCAL_SA_FILE             optional: Google service-account key (JSON) that can write to your calendar
    GCAL_CALENDAR_ID         optional: the calendar it writes plans to (usually your Gmail address)
    TRACKER_PORT             optional, default 8650

Endpoints (also reachable under /tracking/...):
    GET   /api/summary?days=7        calendar events + Notion items
    POST  /api/notion                {"title": "...", "due": "2026-09-30"}  add a note
    PATCH /api/notion/<page_id>      {"done": true}                         tick it off
    POST  /api/plan                  save a plan: Notion page, Notion tasks, calendar events
Standard library only (Python 3.9+).
"""
import base64
import datetime as dt
import json
import os
import re
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


def load_env():
    env = Path.home() / ".hermes" / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_env()
KEY = os.environ.get("API_SERVER_KEY", "")
ORIGINS = [o.strip().rstrip("/") for o in os.environ.get("API_SERVER_CORS_ORIGINS", "").split(",") if o.strip()]
ICS_URLS = [u.strip() for u in os.environ.get("GCAL_ICS_URL", "").split(",") if u.strip()]
NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "")
NOTION_DB = os.environ.get("NOTION_DB_ID", "").replace("-", "")
PORT = int(os.environ.get("TRACKER_PORT", "8650"))
GCAL_SA_FILE = os.path.expanduser(os.environ.get("GCAL_SA_FILE", ""))
GCAL_CALENDAR_ID = os.environ.get("GCAL_CALENDAR_ID", "")
NOTION_API = os.environ.get("NOTION_API", "https://api.notion.com/v1")
GCAL_API = os.environ.get("GCAL_API", "https://www.googleapis.com/calendar/v3")


# ---------------------------------------------------------------- iCal
def _unfold(text):
    out = []
    for line in text.replace("\r\n", "\n").split("\n"):
        if line[:1] in (" ", "\t") and out:
            out[-1] += line[1:]
        else:
            out.append(line)
    return out


def _parse_dt(value, params):
    tzid = params.get("TZID")
    if params.get("VALUE") == "DATE" or re.fullmatch(r"\d{8}", value):
        d = dt.datetime.strptime(value[:8], "%Y%m%d")
        return d.replace(tzinfo=IST), True
    utc = value.endswith("Z")
    d = dt.datetime.strptime(value.rstrip("Z")[:15], "%Y%m%dT%H%M%S")
    if utc:
        d = d.replace(tzinfo=dt.timezone.utc)
    elif tzid and ZoneInfo:
        try:
            d = d.replace(tzinfo=ZoneInfo(tzid))
        except Exception:
            d = d.replace(tzinfo=IST)
    else:
        d = d.replace(tzinfo=IST)
    return d.astimezone(IST), False


WEEKDAYS = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}


def _expand(ev, win0, win1):
    """Yield start times of an event (with simple RRULE support) inside the window."""
    start, rule = ev["start"], ev.get("rrule")
    exdates = ev.get("exdates", set())
    if not rule:
        if start < win1 and ev["end"] > win0:
            yield start
        return
    r = dict(p.split("=", 1) for p in rule.split(";") if "=" in p)
    freq, interval = r.get("FREQ"), int(r.get("INTERVAL", "1"))
    count = int(r["COUNT"]) if "COUNT" in r else None
    until = _parse_dt(r["UNTIL"], {})[0] if "UNTIL" in r else None
    byday = [WEEKDAYS[d[-2:]] for d in r.get("BYDAY", "").split(",") if d[-2:] in WEEKDAYS]
    dur = ev["end"] - start
    n, cur, guard = 0, start, 0
    while guard < 3000:
        guard += 1
        cands = [cur]
        if freq == "WEEKLY" and byday:
            monday = cur - dt.timedelta(days=cur.weekday())
            cands = sorted(monday + dt.timedelta(days=d) for d in byday)
            cands = [c for c in cands if c >= start]
        for c in cands:
            if until and c > until:
                return
            if count is not None and n >= count:
                return
            n += 1
            if c.replace(tzinfo=None) in exdates:
                continue
            if c >= win1:
                return
            if c + dur > win0:
                yield c
        if freq == "DAILY":
            cur += dt.timedelta(days=interval)
        elif freq == "WEEKLY":
            cur += dt.timedelta(weeks=interval)
        elif freq == "MONTHLY":
            m = cur.month - 1 + interval
            try:
                cur = cur.replace(year=cur.year + m // 12, month=m % 12 + 1)
            except ValueError:
                cur = cur.replace(day=28, year=cur.year + m // 12, month=m % 12 + 1)
        elif freq == "YEARLY":
            cur = cur.replace(year=cur.year + interval)
        else:
            return


def parse_ics(text, win0, win1, cal_name=""):
    events, ev, name = [], None, cal_name
    for line in _unfold(text):
        if line.startswith("X-WR-CALNAME:") and not cal_name:
            name = line.split(":", 1)[1]
        if line == "BEGIN:VEVENT":
            ev = {"exdates": set()}
            continue
        if line == "END:VEVENT" and ev is not None:
            if "start" in ev and ev.get("status") != "CANCELLED":
                ev.setdefault("end", ev["start"] + (dt.timedelta(days=1) if ev.get("allday") else dt.timedelta(hours=1)))
                if "recurrence-id" not in ev:
                    for s in _expand(ev, win0, win1):
                        events.append({
                            "title": ev.get("summary", "(no title)"), "start": s.isoformat(),
                            "end": (s + (ev["end"] - ev["start"])).isoformat(), "allDay": ev.get("allday", False),
                            "location": ev.get("location", ""), "calendar": name,
                        })
                else:  # a moved single occurrence of a recurring event
                    if ev["start"] < win1 and ev["end"] > win0:
                        events.append({"title": ev.get("summary", "(no title)"), "start": ev["start"].isoformat(),
                                       "end": ev["end"].isoformat(), "allDay": ev.get("allday", False),
                                       "location": ev.get("location", ""), "calendar": name})
            ev = None
            continue
        if ev is None or ":" not in line:
            continue
        head, value = line.split(":", 1)
        parts = head.split(";")
        prop, params = parts[0].upper(), dict(p.split("=", 1) for p in parts[1:] if "=" in p)
        value = value.replace("\\,", ",").replace("\\;", ";").replace("\\n", " ").replace("\\N", " ")
        if prop == "DTSTART":
            ev["start"], ev["allday"] = _parse_dt(value, params)
        elif prop == "DTEND":
            ev["end"] = _parse_dt(value, params)[0]
        elif prop == "SUMMARY":
            ev["summary"] = value
        elif prop == "LOCATION":
            ev["location"] = value
        elif prop == "RRULE":
            ev["rrule"] = value
        elif prop == "EXDATE":
            for v in value.split(","):
                ev["exdates"].add(_parse_dt(v, params)[0].replace(tzinfo=None))
        elif prop == "RECURRENCE-ID":
            ev["recurrence-id"] = value
        elif prop == "STATUS":
            ev["status"] = value
    return events


_ics_cache = {}


def calendar(days):
    now = dt.datetime.now(IST)
    win0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    win1 = win0 + dt.timedelta(days=days)
    events = []
    for url in ICS_URLS:
        hit = _ics_cache.get(url)
        if not hit or time.time() - hit[0] > 300:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "hermesville"}), timeout=20) as r:
                hit = (time.time(), r.read().decode("utf-8", "replace"))
            _ics_cache[url] = hit
        events += parse_ics(hit[1], win0, win1)
    events.sort(key=lambda e: (e["start"], e["title"]))
    return events


# ---------------------------------------------------------------- Notion
def notion(method, path, body=None):
    req = urllib.request.Request(NOTION_API + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None)
    req.add_header("Authorization", "Bearer " + NOTION_TOKEN)
    req.add_header("Notion-Version", "2022-06-28")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


_schema = {}


def schema():
    if not _schema:
        db = notion("GET", "/databases/" + NOTION_DB)
        props = db.get("properties", {})
        _schema["title"] = next((k for k, v in props.items() if v["type"] == "title"), "Name")
        _schema["date"] = next((k for k, v in props.items() if v["type"] == "date"), None)
        _schema["check"] = next((k for k, v in props.items() if v["type"] == "checkbox"), None)
        st = next(((k, v) for k, v in props.items() if v["type"] == "status"), None)
        if st:
            opts = [o["name"] for o in st[1]["status"].get("options", [])]
            done = next((o for o in opts if o.lower() in ("done", "complete", "completed")), opts[-1] if opts else None)
            _schema["status"], _schema["done"] = st[0], done
        _schema["name"] = "".join(t.get("plain_text", "") for t in db.get("title", [])) or "Notion"
    return _schema


def notion_items():
    s = schema()
    res = notion("POST", "/databases/%s/query" % NOTION_DB,
                 {"page_size": 40, "sorts": [{"timestamp": "last_edited_time", "direction": "descending"}]})
    out = []
    for p in res.get("results", []):
        pr = p.get("properties", {})
        title = "".join(t.get("plain_text", "") for t in pr.get(s["title"], {}).get("title", [])) or "(untitled)"
        due = (pr.get(s["date"], {}).get("date") or {}).get("start") if s.get("date") else None
        done = False
        if s.get("check"):
            done = bool(pr.get(s["check"], {}).get("checkbox"))
        status = None
        if s.get("status"):
            status = (pr.get(s["status"], {}).get("status") or {}).get("name")
            done = done or (status == s.get("done"))
        out.append({"id": p["id"], "title": title, "due": due, "done": done, "status": status,
                    "url": p.get("url"), "edited": p.get("last_edited_time")})
    return out, s["name"]


def notion_add(title, due=None):
    s = schema()
    props = {s["title"]: {"title": [{"text": {"content": title[:1900]}}]}}
    if due and s.get("date"):
        props[s["date"]] = {"date": {"start": due}}
    return notion("POST", "/pages", {"parent": {"database_id": NOTION_DB}, "properties": props})


def notion_done(page_id, done=True):
    s = schema()
    props = {}
    if s.get("check"):
        props[s["check"]] = {"checkbox": bool(done)}
    elif s.get("status") and s.get("done"):
        props[s["status"]] = {"status": {"name": s["done"]}}
    else:
        return {"skipped": "database has no checkbox or status property"}
    return notion("PATCH", "/pages/" + page_id, {"properties": props})


# ---------------------------------------------------------------- Google Calendar (write)
def calendar_writable():
    return bool(GCAL_SA_FILE and GCAL_CALENDAR_ID and os.path.exists(GCAL_SA_FILE))


def _b64u(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


_gtoken = {"value": None, "exp": 0}


def google_token():
    """Service-account OAuth: a JWT signed with the key via the openssl command (no pip packages)."""
    if _gtoken["value"] and time.time() < _gtoken["exp"] - 60:
        return _gtoken["value"]
    sa = json.loads(Path(GCAL_SA_FILE).read_text())
    now = int(time.time())
    head = _b64u(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    claims = _b64u(json.dumps({"iss": sa["client_email"], "scope": "https://www.googleapis.com/auth/calendar.events",
                               "aud": sa["token_uri"], "iat": now, "exp": now + 3600}).encode())
    fd, keyfile = tempfile.mkstemp()
    try:
        os.chmod(keyfile, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(sa["private_key"])
        sig = subprocess.run(["openssl", "dgst", "-sha256", "-sign", keyfile], input=(head + "." + claims).encode(),
                             capture_output=True, check=True).stdout
    finally:
        os.remove(keyfile)
    body = ("grant_type=urn%3Aietf%3Aparams%3Aoauth%3Agrant-type%3Ajwt-bearer&assertion=" + head + "." + claims + "." + _b64u(sig)).encode()
    req = urllib.request.Request(sa["token_uri"], data=body, headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=20) as r:
        tok = json.loads(r.read().decode())
    _gtoken.update(value=tok["access_token"], exp=now + int(tok.get("expires_in", 3600)))
    return _gtoken["value"]


def calendar_add(summary, description, start, end, plan_id):
    from urllib.parse import quote
    ev = {"summary": summary[:200], "description": description[:4000],
          "start": {"dateTime": start.isoformat()}, "end": {"dateTime": end.isoformat()},
          "extendedProperties": {"private": {"hermesville": plan_id}}}
    req = urllib.request.Request("%s/calendars/%s/events" % (GCAL_API, quote(GCAL_CALENDAR_ID, safe="")), method="POST",
                                 data=json.dumps(ev).encode(), headers={"Authorization": "Bearer " + google_token(),
                                                                        "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


# ---------------------------------------------------------------- plans (Notion page + tasks + calendar)
DATE_RE, TIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$"), re.compile(r"^\d{2}:\d{2}$")


def clean_plan(p):
    title = str(p.get("title", "")).strip()[:120]
    if not title:
        raise ValueError("The plan needs a title.")
    out = []
    for x in (p.get("sessions") or [])[:60]:
        d, a, b = str(x.get("date", "")), str(x.get("start", "")), str(x.get("end", ""))
        if not (DATE_RE.match(d) and TIME_RE.match(a) and TIME_RE.match(b)):
            continue
        start = dt.datetime.strptime(d + " " + a, "%Y-%m-%d %H:%M").astimezone()   # server's local time zone
        end = dt.datetime.strptime(d + " " + b, "%Y-%m-%d %H:%M").astimezone()
        if end <= start:
            end = start + dt.timedelta(hours=1)
        out.append({"start": start, "end": end, "title": str(x.get("title", "Session")).strip()[:120] or "Session",
                    "details": str(x.get("details", "")).strip()[:600]})
    if not out:
        raise ValueError("The plan has no valid sessions.")
    out.sort(key=lambda x: x["start"])
    return title, str(p.get("summary", "")).strip()[:1500], out


def _rt(text):
    return [{"type": "text", "text": {"content": text[:1900]}}]


def notion_plan_page(title, summary, sessions):
    s = schema()
    blocks = [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": _rt(summary or "Plan made with Hermes.")}}]
    week = None
    for x in sessions:
        monday = (x["start"] - dt.timedelta(days=x["start"].weekday())).strftime("Week of %d %b")
        if monday != week:
            week = monday
            blocks.append({"object": "block", "type": "heading_3", "heading_3": {"rich_text": _rt(monday)}})
        line = "%s %s-%s · %s" % (x["start"].strftime("%a %d %b"), x["start"].strftime("%H:%M"), x["end"].strftime("%H:%M"), x["title"])
        if x["details"]:
            line += " - " + x["details"]
        blocks.append({"object": "block", "type": "to_do", "to_do": {"rich_text": _rt(line), "checked": False}})
    props = {s["title"]: {"title": [{"text": {"content": title}}]}}
    if s.get("date"):
        props[s["date"]] = {"date": {"start": sessions[0]["start"].date().isoformat(), "end": sessions[-1]["start"].date().isoformat()}}
    page = notion("POST", "/pages", {"parent": {"database_id": NOTION_DB}, "properties": props, "children": blocks[:100]})
    for i in range(100, len(blocks), 100):              # Notion takes 100 blocks per request
        notion("PATCH", "/blocks/%s/children" % page["id"], {"children": blocks[i:i + 100]})
    return page


def notion_plan_tasks(title, sessions):
    s, made = schema(), 0
    for x in sessions:
        props = {s["title"]: {"title": [{"text": {"content": "%s: %s" % (title, x["title"])}}]}}
        if s.get("date"):
            props[s["date"]] = {"date": {"start": x["start"].isoformat(), "end": x["end"].isoformat()}}
        notion("POST", "/pages", {"parent": {"database_id": NOTION_DB}, "properties": props})
        made += 1
        time.sleep(0.34)                                # stay under Notion's 3 requests/second
    return made


def save_plan(body):
    title, summary, sessions = clean_plan(body.get("plan") or {})
    plan_id = "hv-%d" % int(time.time())
    result, errors = {"sessions": len(sessions)}, {}
    if body.get("notionPage") and NOTION_TOKEN and NOTION_DB:
        try:
            page = notion_plan_page(title, summary, sessions)
            result["notionUrl"] = page.get("url")
        except urllib.error.HTTPError as e:
            errors["notionPage"] = "Notion said %s: %s" % (e.code, e.read().decode()[:160])
    if body.get("notionTasks") and NOTION_TOKEN and NOTION_DB:
        try:
            result["tasks"] = notion_plan_tasks(title, sessions)
        except urllib.error.HTTPError as e:
            errors["notionTasks"] = "Notion said %s: %s" % (e.code, e.read().decode()[:160])
    if body.get("calendar") and calendar_writable():
        made = 0
        try:
            for x in sessions:
                calendar_add("%s: %s" % (title, x["title"]), x["details"], x["start"], x["end"], plan_id)
                made += 1
        except urllib.error.HTTPError as e:
            errors["calendar"] = "Google said %s: %s" % (e.code, e.read().decode()[:160])
        except Exception as e:
            errors["calendar"] = str(e)[:200]
        result["events"] = made
    result["errors"] = errors
    return result


# ---------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    server_version = "hermesville-tracker"

    def _cors(self):
        origin = (self.headers.get("Origin") or "").rstrip("/")
        if origin in ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, OPTIONS")
            self.send_header("Access-Control-Max-Age", "600")

    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _path(self):
        p = self.path.split("?", 1)[0]
        return p[len("/tracking"):] if p.startswith("/tracking") else p

    def _authed(self):
        if KEY and self.headers.get("Authorization", "") == "Bearer " + KEY:
            return True
        self._send(401, {"error": "bad or missing key"})
        return False

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}") if n else {}

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        path = self._path()
        if path in ("", "/", "/health"):
            return self._send(200, {"ok": True, "calendar": bool(ICS_URLS), "notion": bool(NOTION_TOKEN and NOTION_DB)})
        if not self._authed():
            return
        if path == "/api/summary":
            q = dict(p.split("=", 1) for p in (self.path.split("?", 1)[1].split("&") if "?" in self.path else []) if "=" in p)
            days = max(1, min(31, int(q.get("days", "7"))))
            out, errors = {"now": dt.datetime.now(IST).isoformat(), "calendar": [], "notion": [], "notionName": None,
                           "sources": {"calendar": bool(ICS_URLS), "notion": bool(NOTION_TOKEN and NOTION_DB),
                                       "calendarWrite": calendar_writable()}}, {}
            if ICS_URLS:
                try:
                    out["calendar"] = calendar(days)
                except Exception as e:
                    errors["calendar"] = str(e)[:200]
            if NOTION_TOKEN and NOTION_DB:
                try:
                    out["notion"], out["notionName"] = notion_items()
                except urllib.error.HTTPError as e:
                    errors["notion"] = "Notion said %s: %s" % (e.code, e.read().decode()[:160])
                except Exception as e:
                    errors["notion"] = str(e)[:200]
            out["errors"] = errors
            return self._send(200, out)
        self._send(404, {"error": "not found"})

    def do_POST(self):
        if self._path() == "/api/plan":
            if not self._authed():
                return
            try:
                return self._send(200, save_plan(self._body()))
            except ValueError as e:
                return self._send(400, {"error": str(e)})
            except Exception as e:
                return self._send(500, {"error": str(e)[:200]})
        if self._path() != "/api/notion" or not self._authed():
            return self._send(404, {"error": "not found"}) if self._path() != "/api/notion" else None
        try:
            b = self._body()
            if not (b.get("title") or "").strip():
                return self._send(400, {"error": "title is required"})
            p = notion_add(b["title"].strip(), b.get("due"))
            self._send(200, {"ok": True, "id": p.get("id"), "url": p.get("url")})
        except urllib.error.HTTPError as e:
            self._send(502, {"error": "Notion said %s: %s" % (e.code, e.read().decode()[:160])})
        except Exception as e:
            self._send(500, {"error": str(e)[:200]})

    def do_PATCH(self):
        m = re.fullmatch(r"/api/notion/([0-9a-fA-F-]{32,36})", self._path())
        if not m:
            return self._send(404, {"error": "not found"})
        if not self._authed():
            return
        try:
            self._send(200, {"ok": True, "result": bool(notion_done(m.group(1), self._body().get("done", True)))})
        except urllib.error.HTTPError as e:
            self._send(502, {"error": "Notion said %s: %s" % (e.code, e.read().decode()[:160])})
        except Exception as e:
            self._send(500, {"error": str(e)[:200]})

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    print("hermesville tracker on 127.0.0.1:%d  calendar=%s notion=%s" % (PORT, bool(ICS_URLS), bool(NOTION_TOKEN and NOTION_DB)), flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
