"""Prompt 5 — edit the daily episode.

No intro: open on one of the day's best clips. Cut to the length of the compilations that won.
Every clip gets a one-line label and the streamer's handle. Every streamer is credited with a link.
Added: YouTube chapters in the description (one per clip) and loudness normalisation.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from . import ledger
from .config import OUT, cfg
from .media import ff_escape, probe, run
from .outliers import winning_length
from .util import fmt_ts
from .vertical import _font_file


def plan(rows: list[dict], target_s: float | None = None) -> Path:
    """Pick clips (best first, second-best last) until the winning length is reached. Writes plan.json.

    The episode-editor agent then rewrites each `label` to a punchy one-liner before rendering.
    """
    target = target_s or winning_length(("compilation",))
    rows = sorted(rows, key=lambda r: -float(r["vph"]))
    chosen, total = [], 0.0
    for r in rows:
        dur = float(r.get("duration_s") or 30)
        if total >= target and len(chosen) >= cfg()["episode"]["min_clips"]:
            break
        chosen.append(r)
        total += dur
    if len(chosen) >= 3:  # end strong
        chosen.append(chosen.pop(1))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    item_id = f"ep-{stamp}"
    d = OUT / "episodes" / item_id
    d.mkdir(parents=True, exist_ok=True)
    p = {
        "id": item_id, "target_s": round(target), "estimated_s": round(total),
        "title_candidates": [], "thumbnail": "",
        "clips": [{"file": r.get("file", ""), "url": r["url"], "source": r["source"], "streamer": r["streamer"],
                   "streamer_url": r.get("streamer_url", ""), "label": r["title"][:70], "vph": r["vph"],
                   "start": 0, "end": None} for r in chosen],
    }
    (d / "plan.json").write_text(json.dumps(p, indent=2))
    return d / "plan.json"


def _segment(clip: dict, i: int, tmp: Path) -> Path:
    e = cfg()["episode"]
    W, H = e["resolution"]
    font = _font_file()
    info = probe(clip["file"])
    start = float(clip.get("start") or 0)
    end = float(clip["end"]) if clip.get("end") else info["duration"]
    label = ff_escape(clip["label"].upper())
    handle = ff_escape(f"@{clip['streamer']}  ·  {clip['source']}")
    vf = (f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={e['fps']},"
          f"drawtext=fontfile='{font}':text='{label}':fontsize=64:fontcolor=white:borderw=5:bordercolor=black:"
          f"x=60:y=h-200:enable='lt(t,4)',"
          f"drawtext=fontfile='{font}':text='{handle}':fontsize=34:fontcolor=white:box=1:boxcolor=black@0.6:"
          f"boxborderw=12:x=60:y=h-110")
    out = tmp / f"seg{i:02d}.mp4"
    inputs = ["-ss", f"{start:.2f}", "-to", f"{end:.2f}", "-i", clip["file"]]
    amap = ["-map", "0:a:0"]
    if not info["audio"]:
        inputs += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
        amap = ["-map", "1:a", "-shortest"]
    run(["ffmpeg", "-v", "error", "-y", *inputs, "-vf", vf, "-map", "0:v:0", *amap,
         "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-ar", "48000", "-ac", "2", "-b:a", "192k", str(out)])
    return out


def render(plan_path: Path) -> dict:
    p = json.loads(Path(plan_path).read_text())
    d = Path(plan_path).parent
    tmp = d / "tmp"
    tmp.mkdir(exist_ok=True)
    clips = [c for c in p["clips"] if c.get("file")]
    if not clips:
        raise SystemExit("Plan has no downloaded clips. Run `python -m pipeline episode plan --download`.")
    segs, chapters, t = [], [], 0.0
    for i, c in enumerate(clips):
        s = _segment(c, i, tmp)
        segs.append(s)
        seg_len = probe(s)["duration"]
        chapters.append((t, c["label"], c["streamer"], seg_len))
        t += seg_len
    lst = tmp / "concat.txt"
    lst.write_text("".join(f"file '{s.resolve()}'\n" for s in segs))
    final = d / "episode.mp4"
    run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c:v", "copy",
         "-af", f"loudnorm=I={cfg()['episode']['loudness_lufs']}:TP=-1.5:LRA=11", "-c:a", "aac", "-b:a", "192k",
         "-movflags", "+faststart", str(final)])
    for s in segs:
        s.unlink(missing_ok=True)

    desc = description(clips, chapters)
    (d / "description.txt").write_text(desc)
    title = (p.get("title_candidates") or [f"GTA 6 Best Clips of the Day ({datetime.now():%b %d})"])[0]
    manifest = {"id": p["id"], "kind": "episode", "file": str(final), "duration_s": round(t, 1),
                "title": title, "title_candidates": p.get("title_candidates", []), "description": desc,
                "thumbnail": p.get("thumbnail", ""), "chapters": [[fmt_ts(a), b] for a, b, _, _ in chapters],
                "sources": [c["url"] for c in clips], "streamers": sorted({c["streamer"] for c in clips})}
    (d / "manifest.json").write_text(json.dumps(manifest, indent=2))
    ledger.register(p["id"], "episode", d, title=title)
    return manifest


def description(clips: list[dict], chapters: list[tuple]) -> str:
    lines = ["The best GTA 6 moments from today's streams. Every clip belongs to its streamer — go follow them 👇", ""]
    seen = set()
    for c in clips:
        if c["streamer"] in seen:
            continue
        seen.add(c["streamer"])
        link = c.get("streamer_url") or c["url"]
        lines.append(f"🎥 {c['streamer']}: {link}")
    # YouTube only shows chapters when there are 3+, the first is 0:00, and each is 10s+.
    if len(chapters) >= 3 and all(c[3] >= 10 for c in chapters):
        lines += ["", "Chapters"]
        for i, (t, label, who, _) in enumerate(chapters):
            lines.append(f"{fmt_ts(0 if i == 0 else t)} {label} (@{who})")
    lines += ["", "Original clips:"] + [f"- {c['url']}" for c in clips]
    lines += ["", "#gta6 #gtavi #gta6clips"]
    return "\n".join(lines)
