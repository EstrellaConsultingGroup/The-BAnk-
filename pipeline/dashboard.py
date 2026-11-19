"""Local control panel: `python -m pipeline dashboard` -> http://127.0.0.1:8787

Runs whitelisted pipeline commands, shows the queue/clips/outliers/links, previews media, and lets the
OWNER approve items (prompt 1: post only what I approve). Binds to localhost only; every POST needs the
per-launch token embedded in the page, so other websites can't drive it.
"""
from __future__ import annotations

import json
import mimetypes
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from . import ledger
from .config import HISTORY, OUTLIERS_CSV, REPORTS, ROOT, RULES_MD, STATE, cfg, load_dotenv, secret
from .util import read_csv

TOKEN = secrets.token_urlsafe(24)
SERVE_DIRS = ("out", "review", "refs", "history", "reports", "assets")
JOBS: dict[str, dict] = {}
SAFE_ID = re.compile(r"^[A-Za-z0-9_.\-]{1,80}$")

# action -> function(args) -> argv for `python -m pipeline`
def _id(a):
    v = str(a.get("item", ""))
    if not SAFE_ID.match(v):
        raise ValueError("bad item id")
    return v


ACTIONS = {
    "doctor": lambda a: ["doctor"],
    "connect": lambda a: ["connect", {"youtube": "youtube", "instagram": "instagram", "apify": "apify"}[a["toolkit"]]],
    "channels_discover": lambda a: ["channels", "discover"],
    "outliers": lambda a: ["outliers"],
    "thumbs_refs": lambda a: ["thumbs", "refs"],
    "clips": lambda a: ["clips"],
    "episode_plan": lambda a: ["episode", "plan", "--download"],
    "verticals": lambda a: ["verticals", "--top", str(max(1, min(int(a.get("top", 5)), 20)))],
    "gauntlet": lambda a: ["gauntlet", _id(a)],
    "publish_due": lambda a: ["publish", "--due"],
    "publish_item": lambda a: ["publish", _id(a)],
    "metrics": lambda a: ["metrics"],
    "status": lambda a: ["status"],
    "tests": None,  # special-cased
}


def start_job(action: str, args: dict) -> str:
    if action not in ACTIONS:
        raise ValueError(f"unknown action {action}")
    argv = [sys.executable, "-m", "pytest", "-q", "tests"] if action == "tests" else \
        [sys.executable, "-m", "pipeline", *ACTIONS[action](args)]
    jid = uuid.uuid4().hex[:8]
    job = {"id": jid, "action": action, "cmd": " ".join(argv[1:]).replace("-m pipeline", "pipeline"),
           "out": "", "done": False, "rc": None, "started": time.time()}
    JOBS[jid] = job

    def run():
        p = subprocess.Popen(argv, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                             env={**os.environ, "PYTHONUNBUFFERED": "1"})
        for line in p.stdout:
            job["out"] += line
        job["rc"] = p.wait()
        job["done"] = True

    threading.Thread(target=run, daemon=True).start()
    return jid


# ------------------------------------------------------------------ state for the page
def _media(item: dict) -> dict:
    d = Path(item["path"])
    rel = lambda p: str(Path(p).resolve().relative_to(ROOT)) if Path(p).resolve().is_relative_to(ROOT) else ""
    out = {"video": "", "thumbs": [], "review": ""}
    m = {}
    if (d / "manifest.json").exists():
        m = json.loads((d / "manifest.json").read_text())
        if m.get("file") and Path(m["file"]).exists():
            out["video"] = rel(m["file"])
        if m.get("thumbnail") and Path(m["thumbnail"]).exists():
            out["thumbs"] = [rel(m["thumbnail"])]
        if item["kind"] == "packaging":
            out["thumbs"] = [rel(d / t["file"]) for t in m.get("thumbnails", []) if (d / t["file"]).exists()]
            out["titles"] = m.get("titles", [])
    if not out["video"]:
        v = next(d.glob("*.mp4"), None) if d.exists() else None
        out["video"] = rel(v) if v else ""
    tries = sorted((ROOT / "review" / item.get("id", "")).glob("try*")) if item.get("id") else []
    if tries and (tries[-1] / "contact_sheet.jpg").exists():
        out["review"] = rel(tries[-1] / "contact_sheet.jpg")
    out["caption"] = (m.get("caption") or {}).get("tiktok") if isinstance(m.get("caption"), dict) else ""
    out["duration"] = m.get("duration_s")
    return out


def state() -> dict:
    load_dotenv()
    items = ledger.load()
    rows = []
    for iid, it in sorted(items.items(), key=lambda kv: kv[1].get("created", ""), reverse=True):
        it = {**it, "id": iid}
        last = (it.get("verdicts") or [None])[-1]
        rows.append({"id": iid, "kind": it["kind"], "status": it["status"], "title": it.get("title", ""),
                     "created": it.get("created", ""), "tries": len(it.get("verdicts", [])),
                     "last_verdict": last, "posts": it.get("posts", {}),
                     "can_publish": ledger.can_publish(it), **_media(it)})
    clip_files = sorted(HISTORY.glob("clips-*.csv"))
    clips = read_csv(clip_files[-1]) if clip_files else []
    outliers = sorted(read_csv(OUTLIERS_CSV), key=lambda r: -float(r.get("ratio") or 0))
    subs = read_csv(STATE / "campaign_submissions.csv")
    cands = read_csv(STATE / "channel_candidates.csv")
    from .outliers import approved_channels
    approved = {c["url"] for c in approved_channels()}
    verdict_log = RULES_MD.read_text().split("## Verdict log", 1)[-1].strip().splitlines()[-20:] if RULES_MD.exists() else []
    keys = {k: bool(secret(k, False)) for k in ("COMPOSIO_API_KEY", "APIFY_TOKEN", "UPLOAD_POST_API_KEY",
                                                   "UPLOAD_POST_USER", "OPENAI_API_KEY", "GEMINI_API_KEY", "TWITCH_CLIENT_ID")}
    tools = {t: bool(shutil.which(t)) for t in ("ffmpeg", "yt-dlp", "scenedetect")}
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    posted_links = sum(len(r["posts"]) for r in rows)
    return {
        "channel": cfg()["channel"]["name"], "gates": cfg()["gates"], "schedule": cfg()["publish"]["schedule"],
        "items": rows, "counts": counts, "posted_links": posted_links,
        "clips": {"file": clip_files[-1].name if clip_files else "",
                  "ok": [c for c in clips if c["status"] == "ok"][:25],
                  "needs_permission": [c for c in clips if c["status"] == "needs_permission"][:12],
                  "skipped": sum(c["status"] == "skipped" for c in clips)},
        "outliers": outliers[:30], "outlier_count": len(outliers),
        "candidates": [{**c, "approved": c["url"] in approved} for c in cands[:80]],
        "approved_channels": len(approved),
        "submissions": [{**s, "row": i} for i, s in enumerate(subs)],
        "reports": sorted([p.name for p in REPORTS.glob("*.md")], reverse=True)[:8],
        "verdict_log": [l for l in verdict_log if l.strip()],
        "keys": keys, "tools": tools,
        "jobs": sorted(({k: v for k, v in j.items() if k != "out"} for j in JOBS.values()),
                       key=lambda j: -j["started"])[:10],
    }


def set_submission(row: int, status: str) -> None:
    from .util import write_csv
    path = STATE / "campaign_submissions.csv"
    rows = read_csv(path)
    if status not in ("to_submit", "submitted", "paid", "rejected") or not (0 <= row < len(rows)):
        raise ValueError("bad submission update")
    rows[row]["status"] = status
    write_csv(path, rows, list(rows[0].keys()))


# ------------------------------------------------------------------ HTTP
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code: int, body: bytes, ctype: str = "application/json", extra: dict | None = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, default=str).encode())

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/":
            html = (Path(__file__).parent / "dashboard.html").read_text().replace("__TOKEN__", TOKEN)
            return self._send(200, html.encode(), "text/html; charset=utf-8")
        if u.path == "/api/state":
            return self._json(state())
        if u.path.startswith("/api/jobs/"):
            j = JOBS.get(u.path.rsplit("/", 1)[-1])
            return self._json(j) if j else self._json({"error": "no such job"}, 404)
        if u.path.startswith("/files/"):
            return self._file(unquote(u.path[len("/files/"):]))
        if u.path.startswith("/doc/"):
            name = unquote(u.path[5:])
            allowed = {"RULES.md", "STATUS.md", "THUMBNAILS.md", "CONNECT.md", "README.md"}
            p = ROOT / name if name in allowed else REPORTS / Path(name).name
            if p.exists() and (name in allowed or p.suffix == ".md"):
                return self._send(200, p.read_bytes(), "text/plain; charset=utf-8")
        self._json({"error": "not found"}, 404)

    def _file(self, rel: str):
        p = (ROOT / rel).resolve()
        if not any(p.is_relative_to((ROOT / d).resolve()) for d in SERVE_DIRS) or not p.is_file():
            return self._json({"error": "not allowed"}, 403)
        size = p.stat().st_size
        ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        rng = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range", ""))
        if rng:  # video seeking
            start = int(rng.group(1) or 0)
            end = min(int(rng.group(2) or size - 1), size - 1)
            with p.open("rb") as f:
                f.seek(start)
                body = f.read(end - start + 1)
            return self._send(206, body, ctype, {"Content-Range": f"bytes {start}-{end}/{size}", "Accept-Ranges": "bytes"})
        self._send(200, p.read_bytes(), ctype, {"Accept-Ranges": "bytes"})

    def do_POST(self):
        if self.headers.get("X-Token") != TOKEN:
            return self._json({"error": "bad token"}, 403)
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        u = urlparse(self.path).path
        try:
            if u == "/api/run":
                return self._json({"job": start_job(body["action"], body.get("args") or {})})
            if u == "/api/approve":  # the owner clicking Approve
                ledger.approve(_id(body))
                return self._json({"ok": True})
            if u == "/api/channels/approve":  # prompt 2: the owner's OK on the channel list
                from .outliers import approve_channels
                names = [str(n) for n in body.get("urls", [])]
                return self._json({"approved": len(approve_channels(names))})
            if u == "/api/submission":
                set_submission(int(body["row"]), str(body["status"]))
                return self._json({"ok": True})
        except SystemExit as e:
            return self._json({"error": str(e)}, 400)
        except Exception as e:
            return self._json({"error": f"{type(e).__name__}: {e}"}, 400)
        self._json({"error": "not found"}, 404)


def serve(port: int = 8787, host: str = "127.0.0.1") -> None:
    srv = ThreadingHTTPServer((host, port), Handler)
    print(f"Dashboard: http://{host}:{port}  (Ctrl+C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
