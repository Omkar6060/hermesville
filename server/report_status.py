#!/usr/bin/env python3
"""
report_status.py - tell Hermesville what an agent is doing.

Writes ~/hermesville/status.json on this server. The app reads it through the
gateway (after you log in), so nothing about your jobs is published anywhere.

    python3 report_status.py <job> <running|done|failed> [note]
    python3 report_status.py film running
    python3 report_status.py film done "reel sent"
    python3 report_status.py writer failed "no topic found"

Jobs: writer, film, news, or the id of an agent built in the app. Never fails the calling job: errors are printed and
the script exits 0.
"""
import datetime as dt
import json
import os
import re
import sys
import tempfile
from pathlib import Path

JOB_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,39}$")   # writer, film, news, or an agent built in the app
STATES = {"running", "done", "failed"}
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
FILE = Path.home() / "hermesville" / "status.json"


def main():
    if len(sys.argv) < 3 or not JOB_RE.match(sys.argv[1]) or sys.argv[2] not in STATES:
        print(__doc__)
        return
    job, state, note = sys.argv[1], sys.argv[2], " ".join(sys.argv[3:])[:120]
    try:
        FILE.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = json.loads(FILE.read_text())
        except Exception:
            data = {}
        now = dt.datetime.now(IST).isoformat(timespec="seconds")
        data.setdefault("jobs", {})[job] = {"state": state, "at": now, "note": note}
        data["updated"] = now
        fd, tmp = tempfile.mkstemp(dir=str(FILE.parent))
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, FILE)          # atomic, so the gateway never reads half a file
        print("report_status: %s -> %s" % (job, state))
    except Exception as e:
        print("report_status: %s" % e)


if __name__ == "__main__":
    main()
