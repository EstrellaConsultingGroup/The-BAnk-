"""Prompt 3 — study the outlier thumbnails, then make titles + thumbnails for every video.

Base art comes from gpt-image, nano banana pro (Gemini), or a real frame of the video. The big
words are drawn locally so they are always crisp and spelled right.
Added: a feed-size preview of every thumbnail so the gauntlet judges it at the size viewers see it.
"""
from __future__ import annotations

import base64
import io
import json
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import ledger
from .config import OUT, REFS, ROOT, cfg, secret
from .media import contact_sheet, find_payoff
from .util import read_csv, write_csv
from .config import OUTLIERS_CSV

W, H = 1280, 720


# ------------------------------------------------------------------ study
def fetch_refs(limit: int = 40) -> Path:
    REFS.mkdir(parents=True, exist_ok=True)
    rows = sorted(read_csv(OUTLIERS_CSV), key=lambda r: -float(r["ratio"] or 0))[:limit]
    got = []
    for r in rows:
        url = r.get("thumbnail_url") or (f"https://i.ytimg.com/vi/{r['video_id']}/maxresdefault.jpg" if r.get("video_id") else "")
        if not url:
            continue
        p = REFS / f"{r['video_id'] or abs(hash(r['url']))}.jpg"
        if not p.exists():
            resp = requests.get(url, timeout=30)
            if resp.status_code != 200 and r.get("video_id"):
                resp = requests.get(f"https://i.ytimg.com/vi/{r['video_id']}/hqdefault.jpg", timeout=30)
            if resp.status_code != 200:
                continue
            Image.open(io.BytesIO(resp.content)).convert("RGB").resize((480, 270)).save(p, quality=88)
        got.append({**r, "ref": str(p.relative_to(ROOT))})
    write_csv(REFS / "index.csv", got, ["ref", "ratio", "views", "format", "title", "channel", "url"])
    sheet = contact_sheet([ROOT / g["ref"] for g in got[:24]], REFS / "sheet.jpg", cols=4)
    return sheet or REFS


# ------------------------------------------------------------------ generate
def gen_openai(prompt: str) -> Image.Image:
    r = requests.post("https://api.openai.com/v1/images/generations", timeout=300,
                      headers={"Authorization": f"Bearer {secret('OPENAI_API_KEY')}"},
                      json={"model": cfg()["thumbnails"]["openai_model"], "prompt": prompt, "size": "1536x1024", "n": 1})
    r.raise_for_status()
    return Image.open(io.BytesIO(base64.b64decode(r.json()["data"][0]["b64_json"]))).convert("RGB")


def gen_gemini(prompt: str) -> Image.Image:
    model = cfg()["thumbnails"]["gemini_model"]
    r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent", timeout=300,
                      headers={"x-goog-api-key": secret("GEMINI_API_KEY")},
                      json={"contents": [{"parts": [{"text": prompt}]}],
                            "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": "16:9"}}})
    r.raise_for_status()
    for part in r.json()["candidates"][0]["content"]["parts"]:
        data = part.get("inlineData") or part.get("inline_data")
        if data:
            return Image.open(io.BytesIO(base64.b64decode(data["data"]))).convert("RGB")
    raise RuntimeError("Gemini returned no image")


def gen_frame(video: Path, t: float | None = None) -> Image.Image:
    import subprocess
    t = find_payoff(video) + 0.5 if t is None else t
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1",
                          "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True).stdout
    im = Image.open(io.BytesIO(raw)).convert("RGB")
    from PIL import ImageEnhance
    return ImageEnhance.Contrast(ImageEnhance.Color(im).enhance(1.35)).enhance(1.12)


def fit_cover(im: Image.Image) -> Image.Image:
    r = max(W / im.width, H / im.height)
    im = im.resize((int(im.width * r + 1), int(im.height * r + 1)), Image.LANCZOS)
    x, y = (im.width - W) // 2, (im.height - H) // 2
    return im.crop((x, y, x + W, y + H))


def draw_words(im: Image.Image, text: str, pos: str = "bottom", accent: str = "#FFE100") -> Image.Image:
    """Short text, a few big words. Last word in the accent colour."""
    font_path = ROOT / cfg()["thumbnails"]["font"]
    font_path = font_path if font_path.exists() else Path("/usr/share/fonts/opentype/inter/Inter-Black.otf")
    words = text.upper().split()
    size = 200
    while size > 60:
        f = ImageFont.truetype(str(font_path), size)
        if f.getlength(" ".join(words)) <= W * 0.86:
            break
        size -= 6
    d = ImageDraw.Draw(im)
    total = f.getlength(" ".join(words))
    x = (W - total) / 2
    y = H - size - 70 if pos == "bottom" else 50
    shadow = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rectangle([0, y - 30, W, y + size + 50], fill=(0, 0, 0, 110))
    im = Image.alpha_composite(im.convert("RGBA"), shadow.filter(ImageFilter.GaussianBlur(30))).convert("RGB")
    d = ImageDraw.Draw(im)
    for i, w in enumerate(words):
        fill = accent if (i == len(words) - 1 and len(words) > 1) else "white"
        d.text((x, y), w, font=f, fill=fill, stroke_width=max(6, size // 14), stroke_fill="black")
        x += f.getlength(w + " ")
    return im


def make(parent_id: str, prompts: list[str], texts: list[str], titles: list[str],
         provider: str | None = None, frame_times: list[float] | None = None) -> dict:
    provider = provider or cfg()["thumbnails"]["provider"]
    parent = ledger.get(parent_id)
    pdir = Path(parent["path"])
    video = next(iter(pdir.glob("*.mp4")), None)
    d = OUT / "thumbnails" / parent_id
    d.mkdir(parents=True, exist_ok=True)
    cands = []
    n = max(len(prompts), len(texts), 1)
    for i in range(n):
        prompt = prompts[i % len(prompts)] if prompts else ""
        text = texts[i % len(texts)] if texts else ""
        if provider == "frame" or not prompt:
            if not video:
                raise SystemExit("No video to take a frame from and no prompt given.")
            base = gen_frame(video, (frame_times or [None])[i % len(frame_times or [None])])
        elif provider == "gemini":
            base = gen_gemini(prompt)
        else:
            base = gen_openai(prompt)
        im = draw_words(fit_cover(base), text) if text else fit_cover(base)
        p = d / f"thumb_{i + 1}.jpg"
        im.save(p, quality=90, optimize=True)
        im.resize((246, 138), Image.LANCZOS).save(d / f"thumb_{i + 1}_feed.jpg", quality=90)
        cands.append({"file": p.name, "text": text, "prompt": prompt, "provider": provider})
    manifest = {"id": f"{parent_id}-pack", "kind": "packaging", "parent": parent_id,
                "thumbnails": cands, "titles": titles}
    (d / "manifest.json").write_text(json.dumps(manifest, indent=2))
    ledger.register(manifest["id"], "packaging", d, title=f"titles+thumbs for {parent_id}", parent=parent_id)
    return manifest


def apply_winners(pack_id: str, thumb: str, title: str) -> None:
    """After the gauntlet picks, write the winners into the parent item's manifest."""
    pack = ledger.get(pack_id)
    parent = ledger.get(pack["parent"])
    mpath = Path(parent["path"]) / "manifest.json"
    m = json.loads(mpath.read_text())
    if thumb:
        m["thumbnail"] = str(Path(pack["path"]) / thumb)
    if title:
        m["title"] = title
        if parent["kind"] == "vertical":
            m["caption"]["youtube_title"] = (title[:90] + " #shorts")[:100]
    mpath.write_text(json.dumps(m, indent=2))
    ledger.update(pack["parent"], title=title or parent.get("title", ""))
