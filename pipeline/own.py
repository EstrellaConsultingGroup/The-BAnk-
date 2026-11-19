"""Prompt 7 — the owner's own video: brief -> script.md (written by the scriptwriter agent) -> the owner
records -> register the finished edit so it goes through the gauntlet and the publisher."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from . import ledger
from .config import OUT, OUTLIERS_CSV
from .outliers import winning_length
from .util import fmt_ts, read_csv, slug


def brief(topic: str, fmt: str) -> Path:
    fmts = {"guide": ("guide",), "ranking": ("ranking",), "challenge": ("challenge",)}.get(fmt, (fmt,))
    target = winning_length(fmts, default=winning_length(("guide", "ranking", "challenge"), default=720))
    rows = sorted([r for r in read_csv(OUTLIERS_CSV) if r.get("format") in fmts], key=lambda r: -float(r["ratio"]))[:15]
    item_id = f"own-{datetime.now(timezone.utc):%Y%m%d}-{slug(topic, 24)}"
    d = OUT / "own" / item_id
    d.mkdir(parents=True, exist_ok=True)
    lines = [f"# Brief: {topic}", "", f"- Format: **{fmt}**", f"- Target length: **{fmt_ts(target)}** "
             f"(median of the {fmt} outliers that won)", "- Footage: the owner's own gameplay only", "",
             "## Winning outliers in this format", ""]
    lines += [f"- {r['ratio']}x · {fmt_ts(float(r['duration_s'] or 0))} · \"{r['title']}\" ({r['channel']})" for r in rows] or ["- none yet: run outliers first"]
    (d / "brief.md").write_text("\n".join(lines) + "\n")
    (d / "manifest.json").write_text(json.dumps({"id": item_id, "kind": "script", "topic": topic, "format": fmt,
                                                 "target_length_s": round(target)}, indent=2))
    return d


def register_script(item_id: str) -> dict:
    d = OUT / "own" / item_id
    if not (d / "script.md").exists():
        raise SystemExit(f"{d}/script.md not written yet")
    m = json.loads((d / "manifest.json").read_text())
    return ledger.register(f"{item_id}-script", "script", d, title=m["topic"])


def register_video(item_id: str, video: Path, title: str, description: str) -> dict:
    """Owner recorded + edited the video. Register it for the gauntlet."""
    d = OUT / "own" / item_id
    m = json.loads((d / "manifest.json").read_text())
    m.update(kind="own_video", file=str(Path(video).resolve()), title=title, description=description)
    (d / "manifest.json").write_text(json.dumps(m, indent=2))
    return ledger.register(item_id, "own_video", d, title=title)
