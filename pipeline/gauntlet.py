"""Prompt 8 — the gauntlet rule.

`pack` builds a self-contained review packet: frames from the cut, a few winning outliers to compare
against, the metadata viewers will see, and a rubric. A *fresh* agent (the `gauntlet` subagent) that
has never seen the maker's notes reads ONLY that folder and answers YES or NO with the faults found.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from . import ledger
from .config import OUTLIERS_CSV, REFS, REVIEW, ROOT, RULES_MD
from .media import contact_sheet, extract_frames, probe
from .util import read_csv

RUBRICS = {
    "vertical": """You are judging a short vertical video (TikTok / Reels / Shorts) built from a streamer's GTA 6 clip.
Answer NO if ANY of these fail:
1. The very first frame (frame_00) already shows the payoff or the most exciting moment — not a calm setup.
2. Facecam (if present) is on top and the gameplay below; nothing important is cropped out of either.
3. Captions are big, readable, word-by-word, and NOT under the right-side buttons or the bottom ~20% of the screen.
4. The streamer's @handle is visible on screen and credited in the caption text.
5. No story cutscene, ending, spoiler, exploit/glitch abuse, or mod menu is shown (see letterboxed flag too).
6. Permission is `campaign` or `written`.
7. It would stop your thumb in a feed next to the outlier examples. If it is boring, say NO.""",
    "episode": """You are judging a daily GTA 6 best-clips compilation for YouTube.
Answer NO if ANY of these fail:
1. No intro: the first frames are already a strong clip, not a logo, title card or slow setup.
2. Every clip has a short one-line label and the streamer's @handle on screen.
3. The description credits every streamer with a link, and chapters start at 0:00.
4. Length is close to the target length of the winning compilations (see metadata).
5. No story cutscenes, endings, spoilers or exploits.
6. Pacing: no dead air or repeated/near-identical clips across the contact sheet.
7. Against the outlier examples, this looks like something people would click and keep watching.""",
    "packaging": """You are judging titles and thumbnails for one video. Compare against the winning outlier thumbnails.
Pick the single best thumbnail and the single best title. Then answer NO if the best of each still fails ANY of:
1. Readable at feed size (*_feed.jpg): a few big words, high contrast, one clear subject.
2. Text on the thumbnail does not just repeat the title; together they create curiosity.
3. Honest: the thumbnail and title match what the video actually shows (see the video's frames).
4. Title under ~60 characters, front-loads the hook, no clickbait the video can't pay off.
5. Stands out next to the outlier examples rather than blending in.""",
    "own_video": """You are judging the owner's own GTA 6 video (guide / ranking / challenge).
Answer NO if ANY of these fail:
1. The payoff comes first: the opening frames show the best result or promise, not an intro.
2. Gameplay is the owner's own footage only.
3. Length is close to the winning outliers for this format (see metadata).
4. No spoilers of story endings, no exploits.
5. Against the outlier examples, this would earn the click and keep the viewer.""",
    "script": """You are judging a script for the owner's own GTA 6 video, before anything is recorded.
Answer NO if ANY of these fail:
1. The first 15 seconds deliver or show the payoff (not "hey guys, welcome back").
2. Structure matches the format of the winning outliers and fits their length.
3. The shot list is specific enough to record without guessing.
4. Titles are short, curiosity-driven and honest; the description is complete.
5. Nothing relies on other people's footage, spoilers of endings, or exploits.""",
}

ANSWER_FORMAT = """
Reply in exactly this format and nothing else:

VERDICT: YES or NO
WINNER_THUMB: <file name, packaging only, else ->
WINNER_TITLE: <exact title, packaging only, else ->
FAULTS:
- <each specific fault, with frame/file names; write "- none" if YES>
"""


def standing_rules() -> str:
    """The owner's quality rules, without the verdict log or anyone's notes."""
    if not RULES_MD.exists():
        return ""
    text = RULES_MD.read_text()
    m = re.search(r"## Standing rules\n(.*?)(\n## |\Z)", text, re.S)
    return m.group(1).strip() if m else ""


def _outlier_examples(dest: Path, n: int = 6) -> list[str]:
    rows = sorted(read_csv(REFS / "index.csv"), key=lambda r: -float(r.get("ratio") or 0))[:n]
    ex = dest / "outlier_examples"
    ex.mkdir(exist_ok=True)
    lines = []
    for r in rows:
        src = ROOT / r["ref"]
        if src.exists():
            shutil.copy(src, ex / src.name)
            lines.append(f"- {src.name}: \"{r['title']}\" ({r['ratio']}x the channel's usual views, {r['format']})")
    if not lines:
        for r in sorted(read_csv(OUTLIERS_CSV), key=lambda r: -float(r.get("ratio") or 0))[:n]:
            lines.append(f"- \"{r['title']}\" ({r['ratio']}x usual views, {r['format']}, {float(r.get('duration_s') or 0) / 60:.1f} min)")
    return lines


def pack(item_id: str) -> Path:
    item = ledger.get(item_id)
    kind = item["kind"]
    src = Path(item["path"])
    attempt = len(item.get("verdicts", [])) + 1
    dest = REVIEW / item_id / f"try{attempt}"
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    m = json.loads((src / "manifest.json").read_text()) if (src / "manifest.json").exists() else {}
    meta: dict = {}

    if kind in ("vertical", "episode", "own_video"):
        video = Path(m.get("file") or next(src.glob("*.mp4")))
        dur = probe(video)["duration"]
        hook = [0.0, 0.5, 1.0, 2.0, 3.0]
        spread = [dur * k / 13 for k in range(1, 13)]
        frames = extract_frames(video, dest / "frames", hook + spread, width=540 if kind == "vertical" else 960)
        contact_sheet(frames, dest / "contact_sheet.jpg", cols=6 if kind == "vertical" else 4)
        keep = ("title", "label", "caption", "description", "duration_s", "permission", "letterboxed",
                "streamer", "source_url", "chapters", "transcript", "streamers")
        meta = {k: m[k] for k in keep if k in m}
        if kind == "episode":
            from .outliers import winning_length
            meta["target_length_s"] = round(winning_length(("compilation",)))
    elif kind == "packaging":
        for t in m["thumbnails"]:
            shutil.copy(src / t["file"], dest / t["file"])
            feed = t["file"].replace(".jpg", "_feed.jpg")
            if (src / feed).exists():
                shutil.copy(src / feed, dest / feed)
        meta = {"titles": m["titles"], "thumbnails": [t["file"] for t in m["thumbnails"]]}
        parent = ledger.get(m["parent"])
        pv = next(Path(parent["path"]).glob("*.mp4"), None)
        if pv:
            d = probe(pv)["duration"]
            fr = extract_frames(pv, dest / "video_frames", [d * k / 9 for k in range(1, 9)], width=480)
            contact_sheet(fr, dest / "video_frames.jpg", cols=4)
    elif kind == "script":
        shutil.copy(src / "script.md", dest / "script.md")
        meta = {k: m[k] for k in ("format", "target_length_s", "topic") if k in m}

    (dest / "metadata.json").write_text(json.dumps(meta, indent=2))
    examples = _outlier_examples(dest)
    rules = standing_rules()
    rubric = [f"# Gauntlet review: {item_id} ({kind}), attempt {attempt}", "",
              "You have NOT seen this work before and you have no notes from whoever made it. Judge only what is in this folder.",
              "Be strict. A YES means you would bet the channel's reputation on posting it.", "",
              "## What to check", RUBRICS.get(kind, RUBRICS["episode"]), ""]
    if rules:
        rubric += ["## The owner's standing rules (also mandatory)", rules, ""]
    rubric += ["## Winning outliers to compare against", *(examples or ["- (none collected yet)"]), "",
               "## Files", "- metadata.json — what viewers will read", "- contact_sheet.jpg / frames/ — the cut (frame_00 is the first frame)",
               "- outlier_examples/ — thumbnails of videos that beat their channel's usual views", "", "## Answer", ANSWER_FORMAT]
    (dest / "RUBRIC.md").write_text("\n".join(rubric))
    return dest


def parse_reply(text: str) -> dict:
    """Parse the gauntlet agent's reply."""
    verdict = re.search(r"VERDICT:\s*(YES|NO)", text, re.I)
    thumb = re.search(r"WINNER_THUMB:\s*(\S+)", text)
    title = re.search(r"WINNER_TITLE:\s*(.+)", text)
    faults_block = text.split("FAULTS:", 1)[1] if "FAULTS:" in text else ""
    faults = [f.strip("-• ").strip() for f in faults_block.splitlines() if f.strip().startswith(("-", "•"))]
    faults = [f for f in faults if f and f.lower() != "none"]
    clean = lambda v: None if not v or v.group(1).strip() in ("-", "") else v.group(1).strip().strip('"')
    return {"passed": bool(verdict and verdict.group(1).upper() == "YES"), "faults": faults,
            "thumb": clean(thumb), "title": clean(title)}
