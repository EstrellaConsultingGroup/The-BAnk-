"""Added: close the loop. Re-scrape the owner's own channel and see which uploads beat the channel's
usual views, so the next round of titles/thumbnails learns from our own outliers too."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .config import HISTORY, REPORTS, cfg
from .outliers import fetch_videos
from .util import median, write_csv


def run() -> Path:
    url = cfg()["channel"].get("youtube_url")
    if not url:
        raise SystemExit("Set channel.youtube_url in config.yaml first.")
    vids = fetch_videos([{"url": url}])
    med = median([v["views"] for v in vids]) or 1
    for v in vids:
        v["ratio"] = round(v["views"] / med, 2)
    vids.sort(key=lambda v: -v["ratio"])
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    write_csv(HISTORY / f"own-metrics-{stamp}.csv", vids)
    lines = [f"# Own channel — {stamp}", "", f"Median views per long video: {med:,.0f}", "", "## Best vs usual", ""]
    lines += [f"- {v['ratio']}x · {v['views']:,} · {v['title']}" for v in vids[:10]]
    lines += ["", "## Worst vs usual", ""] + [f"- {v['ratio']}x · {v['views']:,} · {v['title']}" for v in vids[-5:]]
    p = REPORTS / f"own-metrics-{stamp}.md"
    p.write_text("\n".join(lines) + "\n")
    return p
