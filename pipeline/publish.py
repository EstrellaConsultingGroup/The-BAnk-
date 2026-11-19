"""Prompt 9 — publish the episode, own video and verticals on schedule; log every link; queue
clipping-campaign submissions. Refuses anything that has not passed the gates.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from . import composio, ledger, uploadpost
from .clips import mark_used
from .config import STATE, cfg
from .util import read_csv, write_csv

SUBMISSIONS = STATE / "campaign_submissions.csv"
SLOTS = STATE / "slots.json"
PLATFORMS = {"episode": ["youtube"], "own_video": ["youtube"], "vertical": ["tiktok", "instagram", "youtube"]}


def _manifest(item: dict) -> dict:
    return json.loads((Path(item["path"]) / "manifest.json").read_text())


def _post_youtube(m: dict, kind: str) -> str:
    tools = cfg()["publish"]["composio_tools"]
    p = cfg()["publish"]
    if kind == "vertical":
        title, desc = m["caption"]["youtube_title"], m["caption"]["youtube_description"]
    else:
        title, desc = m["title"], m["description"]
    slug = tools["youtube_upload"]
    args = composio.build_args(slug, "youtube", {
        "title": title[:100], "description": desc[:4900], "tags": ["gta 6", "gta vi", "gta 6 clips"],
        "categoryId": p["youtube_category_id"], "privacyStatus": p["youtube_privacy"],
    }, {"video": Path(m["file"])})
    data = composio.execute(slug, args)
    vid = (data.get("id") or (data.get("response_data") or {}).get("id") or data.get("video_id") or "")
    url = f"https://youtu.be/{vid}" if vid else json.dumps(data)[:200]
    if m.get("thumbnail") and vid and kind != "vertical":
        try:
            ts = tools["youtube_thumbnail"]
            composio.execute(ts, composio.build_args(ts, "youtube", {"videoId": vid, "video_id": vid},
                                                     {"thumbnail": Path(m["thumbnail"])}))
        except Exception as e:
            print(f"thumbnail upload failed ({e}); set it by hand in YouTube Studio")
    return url


def _post_instagram_composio(m: dict) -> str:
    slug = cfg()["publish"]["composio_tools"]["instagram_reel"]
    args = composio.build_args(slug, "instagram", {"caption": m["caption"]["instagram"], "media_type": "REELS"},
                               {"video": Path(m["file"])})
    data = composio.execute(slug, args)
    return data.get("permalink") or data.get("id") and f"instagram media {data['id']}" or json.dumps(data)[:200]


def _post_upload_post(m: dict, platform: str) -> str:
    cap = m["caption"]
    title = {"tiktok": cap["tiktok"], "instagram": cap["instagram"], "youtube": cap["youtube_title"]}[platform]
    resp = uploadpost.upload(Path(m["file"]), platform, title,
                             cap.get("youtube_description", "") if platform == "youtube" else "")
    return uploadpost.post_url(resp, platform)


def publish_item(item_id: str, platforms: list[str] | None = None, dry_run: bool | None = None) -> dict:
    item = ledger.get(item_id)
    ok, why = ledger.can_publish(item)
    if not ok:
        raise SystemExit(f"Refusing to publish {item_id}: {why}.")
    dry = cfg()["gates"]["dry_run"] if dry_run is None else dry_run
    m = _manifest(item)
    routes = cfg()["publish"]["routes"]
    results = {}
    for plat in platforms or PLATFORMS.get(item["kind"], []):
        if plat in item.get("posts", {}):
            continue
        route = routes.get(plat, "upload_post")
        if dry:
            print(f"[dry run] would post {item_id} -> {plat} via {route}: {m['file']}")
            continue
        try:
            if plat == "youtube" and route == "composio":
                url = _post_youtube(m, item["kind"])
            elif plat == "instagram" and route == "composio":
                url = _post_instagram_composio(m)
            elif item["kind"] == "vertical" or plat == "tiktok":
                url = _post_upload_post(m, plat)
            else:
                raise RuntimeError(f"no route for {item['kind']} on {plat}")
            ledger.record_post(item_id, plat, url)
            results[plat] = url
            print(f"posted {item_id} -> {plat}: {url}")
        except Exception as e:
            print(f"FAILED {item_id} -> {plat}: {e}")
            results[plat] = f"FAILED: {e}"
    if not dry and any(not str(v).startswith("FAILED") for v in results.values()):
        mark_used(m.get("sources") or ([m["source_url"]] if m.get("source_url") else []))
        if item["kind"] == "vertical" and (m.get("campaign") or {}).get("url"):
            queue_submission(item_id, m, results)
    if not dry:
        posts = ledger.get(item_id).get("posts", {})
        if all(p in posts for p in (platforms or PLATFORMS.get(item["kind"], []))):
            ledger.update(item_id, status="posted")
    return results


def queue_submission(item_id: str, m: dict, results: dict) -> None:
    """Prompt 9: submit every vertical to a matching clipping campaign. Most campaign dashboards
    (Whop Content Rewards etc.) take submissions by hand, so we queue them with every link ready."""
    rows = read_csv(SUBMISSIONS)
    for plat, url in results.items():
        if str(url).startswith("FAILED"):
            continue
        rows.append({"item": item_id, "streamer": m["streamer"], "campaign": m["campaign"].get("name", ""),
                     "submit_at": m["campaign"]["url"], "platform": plat, "post_url": url,
                     "status": "to_submit", "queued": ledger.now()})
    write_csv(SUBMISSIONS, rows, ["item", "streamer", "campaign", "submit_at", "platform", "post_url", "status", "queued"])


def due(dry_run: bool | None = None) -> list[str]:
    """Post approved items into today's open schedule slots."""
    sch = cfg()["publish"]["schedule"]
    tz = ZoneInfo(sch["timezone"])
    now = datetime.now(tz)
    used = json.loads(SLOTS.read_text()) if SLOTS.exists() else {}
    items = ledger.load()
    posted = []
    for kind in ("episode", "own_video", "vertical"):
        for slot in sch.get(kind, []):
            key = f"{now:%Y-%m-%d}/{kind}/{slot}"
            h, mi = map(int, slot.split(":"))
            if key in used or now < now.replace(hour=h, minute=mi, second=0, microsecond=0):
                continue
            ready = sorted([(i, it) for i, it in items.items() if it["kind"] == kind and ledger.can_publish(it)[0]],
                           key=lambda kv: kv[1].get("approved_at") or kv[1]["created"])
            if not ready:
                continue
            iid = ready[0][0]
            publish_item(iid, dry_run=dry_run)
            if not (cfg()["gates"]["dry_run"] if dry_run is None else dry_run):
                used[key] = iid
                items = ledger.load()
            posted.append(iid)
    SLOTS.parent.mkdir(parents=True, exist_ok=True)
    SLOTS.write_text(json.dumps(used, indent=1))
    return posted


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()
