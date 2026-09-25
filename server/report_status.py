#!/usr/bin/env python3
"""
report_status.py - tell Hermesville what an agent is doing.

Updates status.json in the GitHub repo, so the Hermesville app on your phone
shows the real state of each building.

    python3 report_status.py <job> <running|done|failed> [note]
    python3 report_status.py film running
    python3 report_status.py film done "reel_2026-09-27.mp4"
    python3 report_status.py writer failed "no topic found"

Jobs: writer, film, news  (match the building ids in index.html)

Needs in ~/.hermes/.env:
    GITHUB_TOKEN=github_pat_...   fine-grained token, only the hermesville repo,
                                  permission "Contents: Read and write"
    GITHUB_REPO=<username>/hermesville
    GITHUB_BRANCH=main            (optional)

Uses only the Python standard library. Never fails the calling job: any
error is printed and the script exits 0.
"""
import base64
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

JOBS = {"writer", "film", "news"}
STATES = {"running", "done", "failed"}
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


def load_env():
    env = Path.home() / ".hermes" / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def api(method, url, token, body=None):
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body else None)
    req.add_header("Authorization", "Bearer " + token)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("User-Agent", "hermesville-reporter")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode() or "{}")


def main():
    if len(sys.argv) < 3 or sys.argv[1] not in JOBS or sys.argv[2] not in STATES:
        print(__doc__)
        return
    job, state = sys.argv[1], sys.argv[2]
    note = " ".join(sys.argv[3:])[:120]

    load_env()
    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPO")
    branch = os.environ.get("GITHUB_BRANCH", "main")
    if not token or not repo:
        print("report_status: GITHUB_TOKEN / GITHUB_REPO not set in ~/.hermes/.env - skipping")
        return
    url = "https://api.github.com/repos/%s/contents/status.json" % repo
    now = dt.datetime.now(IST).isoformat(timespec="seconds")

    for attempt in range(4):
        try:
            try:
                cur = api("GET", url + "?ref=" + branch, token)
                sha = cur["sha"]
                data = json.loads(base64.b64decode(cur["content"]).decode() or "{}")
            except urllib.error.HTTPError as e:
                if e.code != 404:
                    raise
                sha, data = None, {}
            data.setdefault("jobs", {})
            data["jobs"][job] = {"state": state, "at": now, "note": note}
            data["updated"] = now
            body = {
                "message": "status: %s %s" % (job, state),
                "content": base64.b64encode((json.dumps(data, indent=2) + "\n").encode()).decode(),
                "branch": branch,
            }
            if sha:
                body["sha"] = sha
            api("PUT", url, token, body)
            print("report_status: %s -> %s" % (job, state))
            return
        except urllib.error.HTTPError as e:
            if e.code in (409, 422) and attempt < 3:   # someone else updated it first - retry
                time.sleep(2 + attempt * 2)
                continue
            print("report_status: GitHub said %s %s" % (e.code, e.read().decode()[:200]))
            return
        except Exception as e:
            print("report_status: %s" % e)
            return


if __name__ == "__main__":
    main()
