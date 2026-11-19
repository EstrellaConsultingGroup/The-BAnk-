"""Prompt 4 — pull the most viewed GTA 6 clips from Twitch, Kick and TikTok, rank by views/hour.

Every clip keeps its source link. Cutscenes, endings and exploits are skipped.
Added: a rights check against streamers.yaml and a ledger so the same clip is never used twice.
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from . import apify
from .apify import pick
from .config import DATA, HISTORY, STATE, cfg, secret, streamers
from .util import parse_duration, parse_time, read_csv, to_int, write_csv

USED = STATE / "used_clips.json"
FIELDS = ["rank", "source", "clip_id", "streamer", "title", "views", "hours", "vph", "duration_s", "url",
          "streamer_url", "thumbnail", "created", "permission", "status", "reason", "file"]


# ------------------------------------------------------------------ sources
def twitch_helix(since: datetime) -> list[dict]:
    cid, csec = secret("TWITCH_CLIENT_ID", False), secret("TWITCH_CLIENT_SECRET", False)
    if not (cid and csec):
        print("twitch: skipped (no TWITCH_CLIENT_ID/SECRET and no twitch_clips_actor)")
        return []
    tok = requests.post("https://id.twitch.tv/oauth2/token", timeout=30, params={
        "client_id": cid, "client_secret": csec, "grant_type": "client_credentials"}).json()["access_token"]
    h = {"Client-Id": cid, "Authorization": f"Bearer {tok}"}
    game = requests.get("https://api.twitch.tv/helix/games", headers=h, timeout=30,
                        params={"name": cfg()["channel"]["game_name"]}).json()["data"]
    if not game:
        print("twitch: game not found on Twitch")
        return []
    out, cursor = [], None
    for _ in range(3):  # up to 300 clips
        params = {"game_id": game[0]["id"], "started_at": since.isoformat().replace("+00:00", "Z"), "first": 100}
        if cursor:
            params["after"] = cursor
        r = requests.get("https://api.twitch.tv/helix/clips", headers=h, params=params, timeout=30).json()
        for c in r.get("data", []):
            if c.get("language", "en").split("-")[0] != cfg()["channel"]["language"]:
                continue
            out.append({"source": "twitch", "clip_id": c["id"], "streamer": c["broadcaster_name"],
                        "title": c["title"], "views": c["view_count"], "created": c["created_at"],
                        "duration_s": c["duration"], "url": c["url"], "thumbnail": c["thumbnail_url"],
                        "streamer_url": f"https://twitch.tv/{c['broadcaster_name'].lower()}"})
        cursor = r.get("pagination", {}).get("cursor")
        if not cursor:
            break
    return out


def twitch_apify(actor: str, since: datetime, limit: int) -> list[dict]:
    items = apify.run_actor(actor, {"gameName": cfg()["channel"]["game_name"], "period": "day", "maxItems": limit}, max_items=limit)
    return [_norm("twitch", it) for it in items]


def kick_apify(actor: str, limit: int) -> list[dict]:
    items = apify.run_actor(actor, {"category": "grand-theft-auto-vi", "sort": "view", "time": "day", "maxItems": limit}, max_items=limit)
    return [_norm("kick", it) for it in items]


def tiktok_apify(actor: str, limit: int) -> list[dict]:
    items = apify.run_actor(actor, {"hashtags": cfg()["apify"]["tiktok_hashtags"], "resultsPerPage": limit,
                                    "shouldDownloadVideos": False, "shouldDownloadCovers": False}, max_items=limit * 3)
    return [_norm("tiktok", it) for it in items]


def _norm(source: str, it: dict) -> dict:
    streamer = pick(it, "broadcaster_name", "broadcaster.username", "channel.slug", "channel.username",
                    "authorMeta.name", "author.uniqueId", "creator", "streamer", default="")
    return {
        "source": source,
        "clip_id": str(pick(it, "id", "clip_id", "slug", default="")),
        "streamer": streamer,
        "title": pick(it, "title", "text", "desc", default=""),
        "views": to_int(pick(it, "view_count", "views", "viewCount", "playCount", "stats.playCount", default=0)),
        "created": pick(it, "created_at", "createdAt", "createTimeISO", "createTime", default=""),
        "duration_s": parse_duration(pick(it, "duration", "videoMeta.duration", "video.duration", default=0)) or 0,
        "url": pick(it, "url", "clip_url", "webVideoUrl", "video_url", default=""),
        "thumbnail": pick(it, "thumbnail_url", "thumbnailUrl", "covers.default", "videoMeta.coverUrl", default=""),
        "streamer_url": pick(it, "channel.url", "authorMeta.profileUrl", default=""),
    }


# ------------------------------------------------------------------ ranking + filters
def _used() -> set[str]:
    return set(json.loads(USED.read_text())) if USED.exists() else set()


def mark_used(urls: list[str]) -> None:
    USED.parent.mkdir(parents=True, exist_ok=True)
    USED.write_text(json.dumps(sorted(_used() | set(urls)), indent=1))


def rank(clips: list[dict]) -> list[dict]:
    c = cfg()["clips"]
    now = datetime.now(timezone.utc)
    used, rights = _used(), streamers()
    seen, out = set(), []
    for cl in clips:
        if not cl["url"] or cl["url"] in seen:
            continue
        seen.add(cl["url"])
        created = parse_time(cl["created"]) or now
        cl["hours"] = round(max((now - created).total_seconds() / 3600, 1.0), 1)
        cl["vph"] = round(cl["views"] / cl["hours"], 1)
        title = f" {cl['title']} ".lower()
        hit = next((w for w in c["blocklist"] if w in title), None)
        dur = float(cl["duration_s"] or 0)
        s = rights.get(str(cl["streamer"]).lower())
        cl["permission"] = (s or {}).get("permission", "none")
        if s and not cl.get("streamer_url"):
            cl["streamer_url"] = (s.get("links") or {}).get(cl["source"], "")
        if hit:
            cl["status"], cl["reason"] = "skipped", f"blocklist: {hit}"
        elif cl["url"] in used:
            cl["status"], cl["reason"] = "skipped", "already used"
        elif dur and not (c["min_duration_s"] <= dur <= c["max_duration_s"]):
            cl["status"], cl["reason"] = "skipped", f"duration {dur:.0f}s"
        elif cfg()["rights"]["require_permission"] and cl["permission"] not in ("campaign", "written"):
            cl["status"], cl["reason"] = "needs_permission", "streamer not cleared in streamers.yaml"
        else:
            cl["status"], cl["reason"] = "ok", ""
        out.append(cl)
    out.sort(key=lambda r: -r["vph"])
    for i, r in enumerate(out, 1):
        r["rank"] = i
    return out


def run_daily() -> tuple[list[dict], Path]:
    c, a = cfg()["clips"], cfg()["apify"]
    since = datetime.now(timezone.utc) - timedelta(hours=c["lookback_hours"])
    pulled: list[dict] = []
    jobs = [
        ("twitch", lambda: twitch_apify(a["twitch_clips_actor"], since, c["per_source_limit"]) if a.get("twitch_clips_actor") else twitch_helix(since)),
        ("kick", lambda: kick_apify(a["kick_clips_actor"], c["per_source_limit"]) if a.get("kick_clips_actor") else []),
        ("tiktok", lambda: tiktok_apify(a["tiktok_actor"], c["per_source_limit"]) if a.get("tiktok_actor") else []),
    ]
    for name, job in jobs:
        try:
            got = job()
            print(f"{name}: {len(got)} clips")
            pulled += got
        except (Exception, SystemExit) as e:  # one source failing must not kill the day
            print(f"{name}: FAILED — {e}")
    ranked = rank(pulled)
    keep = [r for r in ranked if r["status"] == "ok"][: c["keep_top"]]
    rest = [r for r in ranked if r["status"] != "ok"]
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = HISTORY / f"clips-{stamp}.csv"
    write_csv(path, keep + rest, FIELDS)
    return keep, path


def latest_clips_csv() -> Path:
    files = sorted(HISTORY.glob("clips-*.csv"))
    if not files:
        raise SystemExit("No clips yet. Run `python -m pipeline clips`.")
    return files[-1]


def download(rows: list[dict]) -> list[dict]:
    """yt-dlp each clip to data/clips/. Keeps the source link on every row."""
    dest = DATA / "clips"
    dest.mkdir(parents=True, exist_ok=True)
    for r in rows:
        out = dest / f"{r['source']}-{r['clip_id'] or abs(hash(r['url']))}.mp4"
        if not out.exists():
            res = subprocess.run(["yt-dlp", "-q", "--no-warnings", "-f", "bv*[height<=1080]+ba/b[height<=1080]/b",
                                  "--merge-output-format", "mp4", "-o", str(out), r["url"]], capture_output=True, text=True)
            if res.returncode != 0:
                print(f"download failed: {r['url']}: {res.stderr.strip()[:200]}")
                continue
        r["file"] = str(out)
    return [r for r in rows if r.get("file")]


def load_ok(path: Path | None = None) -> list[dict]:
    return [r for r in read_csv(path or latest_clips_csv()) if r["status"] == "ok"]
