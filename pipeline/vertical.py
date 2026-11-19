"""Prompt 6 — cut the strongest clips into short verticals.

Facecam on top, gameplay below. The first frame is the payoff. Word-by-word captions sit clear of
the apps' buttons. The streamer is tagged on screen and in the caption.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from . import ledger
from .config import OUT, cfg, streamers
from .media import ff_escape, find_payoff, letterboxed, probe, run, transcribe_words, words_to_ass
from .util import slug

FONT_FILE = "/usr/share/fonts/opentype/inter/Inter-Black.otf"


def _font_file() -> str:
    from .config import ROOT
    p = ROOT / cfg()["episode"]["label_font"]
    return str(p) if p.exists() else FONT_FILE


def layout_filter(W: int, H: int, facecam: dict | None) -> tuple[str, int]:
    """Return (filtergraph from [0:v] to [lay], caption_y)."""
    vw, vh = cfg()["vertical"]["size"]
    if facecam:
        cx, cy = int(facecam["x"] * W), int(facecam["y"] * H)
        cw, ch = max(16, int(facecam["w"] * W)), max(16, int(facecam["h"] * H))
        top_h = int(min(max(vw * ch / cw, 560), 760)) // 2 * 2
        bot_h = vh - top_h
        gw = min(W, int(H * vw / bot_h)) // 2 * 2
        gx = (W - gw) // 2
        g = (f"[0:v]split=2[fa][ga];"
             f"[fa]crop={cw}:{ch}:{cx}:{cy},scale={vw}:{top_h}:force_original_aspect_ratio=increase,crop={vw}:{top_h}[top];"
             f"[ga]crop={gw}:{H}:{gx}:0,scale={vw}:{bot_h}:force_original_aspect_ratio=increase,crop={vw}:{bot_h}[bot];"
             f"[top][bot]vstack=inputs=2,setsar=1[lay]")
        return g, top_h
    fg_h = int(vw * 3 / 4) // 2 * 2  # 4:3 centre crop of the gameplay, zoomed for phones
    gw = min(W, int(H * 4 / 3)) // 2 * 2
    g = (f"[0:v]split=2[bga][fga];"
         f"[bga]scale={vw}:{vh}:force_original_aspect_ratio=increase,crop={vw}:{vh},boxblur=24:2,eq=brightness=-0.12[bg];"
         f"[fga]crop={gw}:{H}:{(W - gw) // 2}:0,scale={vw}:{fg_h}[fg];"
         f"[bg][fg]overlay=0:(H-h)/2,setsar=1[lay]")
    return g, (vh - fg_h) // 2 - 40


def render(row: dict, label: str | None = None) -> dict:
    v = cfg()["vertical"]
    vw, vh = v["size"]
    src = Path(row["file"])
    info = probe(src)
    handle = str(row["streamer"])
    s = streamers().get(handle.lower(), {})
    payoff = find_payoff(src)
    item_id = f"v-{datetime.now(timezone.utc):%Y%m%d}-{slug(handle, 16)}-{slug(row.get('clip_id') or src.stem, 12)}"
    d = OUT / "verticals" / item_id
    tmp = d / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)

    lay, cap_y = layout_filter(info["w"], info["h"], s.get("facecam"))
    cap_y = min(max(cap_y, v["safe_top_px"] + v["caption_size"]), vh - v["safe_bottom_px"] - v["caption_size"])
    max_len = float(v["max_duration_s"])

    # ---- timeline: payoff first
    if v["hook_mode"] == "teaser" and payoff > 1.5:
        t0 = max(0.0, payoff - 0.3)
        tz = min(float(v["teaser_s"]), info["duration"] - t0)
        body = min(info["duration"], max_len - tz)
        segs = [(t0, t0 + tz), (0.0, body)]
    else:
        start = max(0.0, payoff - 1.0) if payoff > 1.5 else 0.0
        segs = [(start, min(info["duration"], start + max_len))]

    font = _font_file()
    tag = ff_escape(f"@{handle}")
    tag_y = cap_y + v["caption_size"]  # just under the caption line, left side, clear of the right-hand buttons
    parts, labels = [], []
    for i, (a, b) in enumerate(segs):
        parts.append(f"[lay]trim={a:.2f}:{b:.2f},setpts=PTS-STARTPTS[v{i}]" if len(segs) == 1 else
                     f"[l{i}]trim={a:.2f}:{b:.2f},setpts=PTS-STARTPTS[v{i}]")
        parts.append(f"[0:a]atrim={a:.2f}:{b:.2f},asetpts=PTS-STARTPTS[a{i}]")
        labels.append(f"[v{i}][a{i}]")
    split = "" if len(segs) == 1 else f";[lay]split={len(segs)}" + "".join(f"[l{i}]" for i in range(len(segs)))
    graph = (lay + split + ";" + ";".join(parts) + ";" + "".join(labels) +
             f"concat=n={len(segs)}:v=1:a=1[cv][ca];"
             f"[cv]drawtext=fontfile='{font}':text='{tag}':fontsize=40:fontcolor=white:"
             f"box=1:boxcolor=black@0.55:boxborderw=14:x=40:y={tag_y}[outv]")
    pass1 = tmp / "pass1.mp4"
    inputs = ["-i", str(src)]
    if not info["audio"]:
        inputs += ["-f", "lavfi", "-t", str(info["duration"]), "-i", "anullsrc=r=48000:cl=stereo"]
        graph = graph.replace("[0:a]", "[1:a]")
    run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", graph, "-map", "[outv]", "-map", "[ca]",
         "-r", "30", "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-c:a", "aac", "-b:a", "192k", str(pass1)])

    # ---- captions on the final timeline
    words = transcribe_words(pass1, v["whisper_model"])
    final = d / "vertical.mp4"
    vf = "null"
    if words:
        ass = words_to_ass(words, tmp / "captions.ass", w=vw, h=vh, y=cap_y, font=v["caption_font"],
                           size=v["caption_size"], margin_lr=v["safe_right_px"])
        vf = f"subtitles='{ass}':fontsdir='{Path(font).parent}'"
    run(["ffmpeg", "-v", "error", "-y", "-i", str(pass1), "-vf", vf,
         "-af", f"loudnorm=I={cfg()['episode']['loudness_lufs']}:TP=-1.5:LRA=11",
         "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(final)])
    pass1.unlink(missing_ok=True)

    label = label or hook_label(row["title"])
    camp = s.get("campaign") or {}
    manifest = {
        "id": item_id, "kind": "vertical", "file": str(final), "source_url": row["url"], "source": row["source"],
        "streamer": handle, "streamer_url": row.get("streamer_url") or (s.get("links") or {}).get(row["source"], ""),
        "permission": s.get("permission", "none"), "payoff_s": payoff, "segments": segs,
        "letterboxed": letterboxed(src) if cfg()["clips"]["letterbox_check"] else None,
        "label": label, "transcript": " ".join(w["word"] for w in words),
        "caption": vertical_caption(label, handle, row, s),
        "campaign": camp, "duration_s": round(probe(final)["duration"], 2),
    }
    (d / "manifest.json").write_text(json.dumps(manifest, indent=2))
    ledger.register(item_id, "vertical", d, title=label, source_url=row["url"], streamer=handle)
    return manifest


def hook_label(title: str) -> str:
    t = " ".join(title.split())
    return (t[:60] + "…") if len(t) > 60 else (t or "WAIT FOR IT")


def vertical_caption(label: str, handle: str, row: dict, s: dict) -> dict:
    link = row.get("streamer_url") or (s.get("links") or {}).get(row["source"], "")
    disclosure = ((s.get("campaign") or {}).get("disclosure") or "").strip()
    tags = "#gta6 #gtavi #gaming"
    base = f"{label}\n\n🎥 @{handle}" + (f" — {link}" if link else "") + f"\nClip: {row['url']}"
    if disclosure:
        base += f"\n{disclosure}"
    return {
        "tiktok": f"{label} 🎥 @{handle} {tags} {disclosure}".strip(),
        "instagram": f"{base}\n\n{tags}",
        "youtube_title": (label[:90] + " #shorts")[:100],
        "youtube_description": f"{base}\n\n{tags} #shorts",
    }
