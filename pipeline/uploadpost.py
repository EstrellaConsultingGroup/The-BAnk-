"""Upload-Post — native TikTok upload (and an Instagram/YouTube fallback)."""
from __future__ import annotations

from pathlib import Path

import requests

from .config import cfg, secret

API = "https://api.upload-post.com/api/upload"


def upload(video: Path, platform: str, title: str, description: str = "") -> dict:
    user = secret("UPLOAD_POST_USER", False) or cfg()["channel"]["name"]
    data = [("user", user), ("title", title), ("platform[]", platform)]
    if description:
        data.append(("description", description))
    with Path(video).open("rb") as f:
        r = requests.post(API, headers={"Authorization": f"Apikey {secret('UPLOAD_POST_API_KEY')}"},
                          data=data, files={"video": (Path(video).name, f, "video/mp4")}, timeout=1800)
    if r.status_code >= 400:
        raise RuntimeError(f"Upload-Post {platform} -> {r.status_code}: {r.text[:500]}")
    return r.json()


def post_url(resp: dict, platform: str) -> str:
    """Dig the public URL out of Upload-Post's response, whatever shape it takes."""
    res = resp.get("results", resp)
    p = res.get(platform, res) if isinstance(res, dict) else {}
    if isinstance(p, dict):
        for k in ("url", "post_url", "video_url", "link", "share_url"):
            if p.get(k):
                return p[k]
    return resp.get("request_id") and f"upload-post request {resp['request_id']}" or "posted (no url returned)"
