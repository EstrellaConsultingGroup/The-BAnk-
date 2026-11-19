"""Prompt 2 — find GTA channels, pull their recent videos, keep the outliers, diff weekly."""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import yaml

from . import apify
from .apify import pick
from .config import HISTORY, OUTLIERS_CSV, REPORTS, ROOT, STATE, cfg
from .util import english_score, median, parse_duration, parse_time, read_csv, to_int, write_csv

CHANNELS_YAML = ROOT / "channels.yaml"
CANDIDATES_CSV = STATE / "channel_candidates.csv"

FORMAT_PATTERNS = [
    ("compilation", r"\b(best|funniest|funny|moments|clips|compilation|fails|highlights|wtf)\b"),
    ("ranking", r"\b(top \d+|ranking|ranked|tier list|worst to best|every .* ranked)\b"),
    ("guide", r"\b(how to|guide|tips|tricks|secrets?|locations?|everything|full map|map|explained)\b"),
    ("challenge", r"\b(challenge|but|only|can i|can you|survive|100 days|vs)\b"),
    ("news", r"\b(trailer|leak|news|release|update|rockstar|confirmed)\b"),
]


def classify(title: str) -> str:
    t = title.lower()
    for name, pat in FORMAT_PATTERNS:
        if re.search(pat, t):
            return name
    return "other"


# ------------------------------------------------------------------ channel discovery
def discover_channels(max_per_query: int = 50) -> list[dict]:
    c = cfg()
    items = apify.run_actor(
        c["apify"]["youtube_search_actor"],
        {"searchQueries": c["channel"]["search_terms"], "maxResults": max_per_query,
         "maxResultsShorts": 0, "maxResultStreams": 0, "sortingOrder": "date"},
    )
    by_channel: dict[str, dict] = {}
    titles: dict[str, list[str]] = defaultdict(list)
    for it in items:
        url = pick(it, "channelUrl", "channel.url", "authorUrl")
        name = pick(it, "channelName", "channel.name", "author")
        if not url or not name:
            continue
        ch = by_channel.setdefault(url, {"channel": name, "url": url, "subscribers": 0, "hits": 0, "latest": ""})
        ch["subscribers"] = max(ch["subscribers"], to_int(pick(it, "numberOfSubscribers", "channel.subscribers", default=0)))
        ch["hits"] += 1
        d = parse_time(pick(it, "date", "uploadDate", "publishedAt"))
        if d and d.isoformat() > ch["latest"]:
            ch["latest"] = d.isoformat()
        titles[url].append(str(pick(it, "title", default="")))
    rows = []
    now = datetime.now(timezone.utc)
    for url, ch in by_channel.items():
        latest = parse_time(ch["latest"])
        ch["days_since_upload"] = round((now - latest).total_seconds() / 86400, 1) if latest else ""
        ch["english"] = round(english_score(titles[url]), 2)
        ch["sample_titles"] = " | ".join(titles[url][:3])
        if ch["english"] >= 0.6 and (ch["days_since_upload"] == "" or ch["days_since_upload"] <= 14):
            rows.append(ch)
    rows.sort(key=lambda r: (-r["hits"], -r["subscribers"]))
    write_csv(CANDIDATES_CSV, rows, ["channel", "url", "subscribers", "hits", "days_since_upload", "english", "sample_titles", "latest"])
    return rows


def approved_channels() -> list[dict]:
    if not CHANNELS_YAML.exists():
        return []
    return (yaml.safe_load(CHANNELS_YAML.read_text()) or {}).get("channels") or []


def approve_channels(names: list[str] | None, all_: bool = False) -> list[dict]:
    """Only run after the owner says OK in chat (prompt 2: 'show me the list and wait for my ok')."""
    cands = read_csv(CANDIDATES_CSV)
    wanted = {n.strip().lower() for n in names or []}
    chosen = [r for r in cands if all_ or r["channel"].lower() in wanted or r["url"].lower() in wanted]
    current = {c["url"]: c for c in approved_channels()}
    for r in chosen:
        current[r["url"]] = {"channel": r["channel"], "url": r["url"]}
    CHANNELS_YAML.write_text(yaml.safe_dump({"channels": list(current.values())}, sort_keys=False))
    return chosen


# ------------------------------------------------------------------ outliers
def fetch_videos(channels: list[dict]) -> list[dict]:
    c = cfg()
    raw = apify.run_actor(
        c["apify"]["youtube_channel_actor"],
        {"startUrls": [{"url": ch["url"]} for ch in channels],
         "maxResults": c["outliers"]["videos_per_channel"], "maxResultsShorts": 0, "maxResultStreams": 0},
    )
    vids = []
    for it in raw:
        url = pick(it, "url", "videoUrl")
        dur = parse_duration(pick(it, "duration", "lengthSeconds", "durationSeconds"))
        if not url or "/shorts/" in str(url) or (dur is not None and dur <= 60):
            continue
        vids.append({
            "channel": pick(it, "channelName", "channel.name", "aboutChannelInfo.channelName", default=""),
            "channel_url": pick(it, "channelUrl", "channel.url", "inputChannelUrl", default=""),
            "title": pick(it, "title", default=""),
            "url": url,
            "video_id": pick(it, "id", "videoId", default=""),
            "views": to_int(pick(it, "viewCount", "views", default=0)),
            "published": (parse_time(pick(it, "date", "uploadDate", "publishedAt")) or datetime.now(timezone.utc)).isoformat(),
            "duration_s": dur or "",
            "thumbnail_url": pick(it, "thumbnailUrl", "thumbnail", "thumbnails.0.url", default=""),
        })
    return vids


def compute_outliers(vids: list[dict]) -> list[dict]:
    o = cfg()["outliers"]
    now = datetime.now(timezone.utc)
    by_ch: dict[str, list[dict]] = defaultdict(list)
    for v in vids:
        age_h = (now - parse_time(v["published"])).total_seconds() / 3600
        v["age_days"] = round(age_h / 24, 1)
        if o["min_age_hours"] <= age_h <= o["max_age_days"] * 24:
            by_ch[v["channel_url"] or v["channel"]].append(v)
    out = []
    for vs in by_ch.values():
        if len(vs) < 5:  # not enough history to know the channel's "usual"
            continue
        med = median([v["views"] for v in vs])
        for v in vs:
            ratio = v["views"] / med if med else 0
            if ratio >= o["min_ratio"] and v["views"] >= o["min_views"]:
                out.append({**v, "channel_median": int(med), "ratio": round(ratio, 2), "format": classify(v["title"])})
    out.sort(key=lambda r: -r["ratio"])
    return out


FIELDS = ["channel", "channel_url", "title", "url", "video_id", "views", "channel_median", "ratio",
          "format", "duration_s", "age_days", "published", "thumbnail_url", "scraped_at"]


def run_outliers() -> tuple[list[dict], Path]:
    chans = approved_channels()
    if not chans:
        raise SystemExit("No approved channels. Run `python -m pipeline channels discover`, show the owner, then approve.")
    rows = compute_outliers(fetch_videos(chans))
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for r in rows:
        r["scraped_at"] = stamp
    previous = sorted(HISTORY.glob("outliers-*.csv"))
    write_csv(OUTLIERS_CSV, rows, FIELDS)
    snap = HISTORY / f"outliers-{stamp}.csv"
    write_csv(snap, rows, FIELDS)
    prev = [p for p in previous if p != snap]
    report = weekly_diff(read_csv(prev[-1]) if prev else [], rows, stamp)
    return rows, report


def _words(rows):
    stop = {"the", "a", "in", "of", "to", "and", "is", "i", "gta", "6", "vi", "you", "my", "this", "it", "on", "for", "-", "|"}
    c = Counter()
    for r in rows:
        c.update(w for w in re.findall(r"[a-z0-9']+", r["title"].lower()) if w not in stop and len(w) > 2)
    return c


def weekly_diff(old: list[dict], new: list[dict], stamp: str) -> Path:
    old_urls, new_urls = {r["url"] for r in old}, {r["url"] for r in new}
    added = [r for r in new if r["url"] not in old_urls]
    dropped = [r for r in old if r["url"] not in new_urls]
    w_new, w_old = _words(new), _words(old)
    rising = sorted(((w, n - w_old.get(w, 0)) for w, n in w_new.items()), key=lambda x: -x[1])[:10]
    fmt = Counter(r["format"] for r in new)
    lengths = defaultdict(list)
    for r in new:
        if r.get("duration_s"):
            lengths[r["format"]].append(float(r["duration_s"]))
    lines = [f"# Outliers — {stamp}", "",
             f"{len(new)} outliers this run ({len(added)} new, {len(dropped)} gone since last run).", "",
             "## New this week", ""]
    lines += [f"- **{r['ratio']}x** · {r['channel']} · [{r['title']}]({r['url']}) · {r['views']:,} views" for r in added[:20]] or ["- none"]
    lines += ["", "## Formats that won", ""]
    lines += [f"- {f}: {n} outliers · median length {median(lengths[f]) / 60:.1f} min" for f, n in fmt.most_common()]
    lines += ["", "## Title words rising", "", ", ".join(f"{w} (+{d})" for w, d in rising if d > 0) or "—"]
    lines += ["", "## Dropped out", ""] + ([f"- {r['title']} ({r['channel']})" for r in dropped[:10]] or ["- none"])
    path = REPORTS / f"outliers-{stamp}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")
    return path


def winning_length(formats: tuple[str, ...] = ("compilation",), default: float | None = None) -> float:
    """Median length of the outliers that won, for prompts 5 and 7 ('copy the length')."""
    rows = [r for r in read_csv(OUTLIERS_CSV) if r.get("format") in formats and r.get("duration_s")]
    if len(rows) >= 3:
        return median([float(r["duration_s"]) for r in rows])
    return default if default is not None else float(cfg()["episode"]["default_target_s"])
