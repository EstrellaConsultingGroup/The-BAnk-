"""ffmpeg / scenedetect / faster-whisper helpers shared by the editors."""
from __future__ import annotations

import json
import re
import subprocess
from functools import lru_cache
from pathlib import Path

import numpy as np


def run(cmd: list[str]) -> str:
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"{cmd[0]} failed:\n{res.stderr[-2000:]}")
    return res.stdout + res.stderr


def probe(path: Path | str) -> dict:
    out = run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)])
    j = json.loads(out[: out.rfind("}") + 1])
    v = next((s for s in j["streams"] if s["codec_type"] == "video"), {})
    has_audio = any(s["codec_type"] == "audio" for s in j["streams"])
    return {"w": int(v.get("width", 0)), "h": int(v.get("height", 0)),
            "duration": float(j["format"].get("duration", 0)), "audio": has_audio}


def audio_energy(path: Path | str, hop: float = 0.1) -> np.ndarray:
    """RMS loudness per `hop` seconds (mono, 8 kHz)."""
    sr = 8000
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"],
                         capture_output=True).stdout
    a = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768
    n = int(sr * hop)
    if len(a) < n:
        return np.zeros(1)
    a = a[: len(a) // n * n].reshape(-1, n)
    return np.sqrt((a ** 2).mean(axis=1) + 1e-12)


def scene_cuts(path: Path | str) -> list[float]:
    try:
        from scenedetect import ContentDetector, detect
        return [s[0].get_seconds() for s in detect(str(path), ContentDetector(threshold=27.0))][1:]
    except Exception:
        return []


def find_payoff(path: Path | str) -> float:
    """Best guess at the clip's payoff: the loudest ~1.5s (streamer reaction), nudged toward a nearby cut.

    Streamer clips peak where the streamer reacts; that is the moment worth showing first.
    """
    hop = 0.1
    e = audio_energy(path, hop)
    if e.size < 5:
        return 0.0
    win = max(1, int(1.5 / hop))
    smooth = np.convolve(e, np.ones(win) / win, mode="same")
    smooth[: int(1.0 / hop)] *= 0.6  # the opening second is rarely the payoff
    peak = float(np.argmax(smooth) * hop)
    cuts = [c for c in scene_cuts(path) if 0 <= peak - c <= 2.5]
    return round(cuts[-1] if cuts else max(0.0, peak - 0.6), 2)


def letterboxed(path: Path | str) -> bool:
    """Cinematic black bars usually mean a cutscene."""
    info = probe(path)
    out = run(["ffmpeg", "-v", "info", "-ss", str(info["duration"] / 2), "-i", str(path), "-t", "4",
               "-vf", "cropdetect=24:2:0", "-f", "null", "-"])
    crops = re.findall(r"crop=(\d+):(\d+):(\d+):(\d+)", out)
    if not crops or not info["h"]:
        return False
    h = int(crops[-1][1])
    return h < info["h"] * 0.88


def extract_frames(video: Path | str, dest: Path, times: list[float], width: int = 720) -> list[Path]:
    dest.mkdir(parents=True, exist_ok=True)
    out = []
    for i, t in enumerate(times):
        p = dest / f"frame_{i:02d}_{t:06.1f}s.jpg"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1",
                        "-vf", f"scale={width}:-2", "-q:v", "3", str(p)], check=False)
        if p.exists():
            out.append(p)
    return out


def contact_sheet(frames: list[Path], dest: Path, cols: int = 4) -> Path | None:
    from PIL import Image, ImageDraw
    if not frames:
        return None
    ims = [Image.open(f).convert("RGB") for f in frames]
    w, h = ims[0].size
    rows = (len(ims) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * w, rows * h), "black")
    d = ImageDraw.Draw(sheet)
    for i, (im, f) in enumerate(zip(ims, frames)):
        x, y = (i % cols) * w, (i // cols) * h
        sheet.paste(im.resize((w, h)), (x, y))
        d.text((x + 8, y + 8), f.stem.split("_")[-1], fill="yellow")
    sheet.save(dest, quality=85)
    return dest


# ------------------------------------------------------------------ captions
@lru_cache
def _whisper(model: str):
    from faster_whisper import WhisperModel
    return WhisperModel(model, device="auto", compute_type="int8")


def transcribe_words(path: Path | str, model: str = "small") -> list[dict]:
    try:
        segments, _ = _whisper(model).transcribe(str(path), word_timestamps=True, vad_filter=True, language="en")
        return [{"start": w.start, "end": w.end, "word": w.word.strip()} for s in segments for w in (s.words or []) if w.word.strip()]
    except Exception as e:
        print(f"transcription unavailable ({e}); rendering without captions")
        return []


def _ass_time(t: float) -> str:
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def words_to_ass(words: list[dict], dest: Path, *, w: int, h: int, y: int, font: str, size: int,
                 margin_lr: int, max_words: int = 1) -> Path:
    """Word-by-word captions, centred at height y, kept inside the side margins (clear of app buttons)."""
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Word,{font},{size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,7,3,5,{margin_lr},{margin_lr},0,1
Style: Hot,{font},{size},&H0000E5FF,&H0000E5FF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,7,3,5,{margin_lr},{margin_lr},0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    hot = {"no", "wait", "what", "bro", "yo", "oh", "dude", "insane", "crazy", "run", "go", "omg", "wow"}
    lines = []
    chunk: list[dict] = []
    for i, wd in enumerate(words):
        chunk.append(wd)
        last = i == len(words) - 1
        if len(chunk) >= max_words or last:
            start = chunk[0]["start"]
            end = words[i + 1]["start"] if not last else chunk[-1]["end"] + 0.3
            end = min(end, chunk[-1]["end"] + 0.6)
            text = " ".join(c["word"] for c in chunk).upper().replace("{", "").replace("}", "")
            style = "Hot" if re.sub(r"[^a-z]", "", text.lower()) in hot else "Word"
            pop = r"{\fscx80\fscy80\t(0,80,\fscx105\fscy105)\t(80,140,\fscx100\fscy100)}"
            lines.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(max(end, start + 0.12))},{style},,0,0,0,,{{\\pos({w // 2},{y})}}{pop}{text}")
            chunk = []
    dest.write_text(header + "\n".join(lines) + "\n")
    return dest


def ff_escape(text: str) -> str:
    """Escape text for ffmpeg drawtext."""
    return text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "’").replace("%", "\\%").replace(",", "\\,")
