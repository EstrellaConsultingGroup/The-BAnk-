"""Paths, config and .env loading. Secrets come only from the environment / .env."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "state"
DATA = ROOT / "data"
OUT = ROOT / "out"
REFS = ROOT / "refs"
REVIEW = ROOT / "review"
HISTORY = ROOT / "history"
REPORTS = ROOT / "reports"
OUTLIERS_CSV = ROOT / "outliers.csv"
STATUS_MD = ROOT / "STATUS.md"
RULES_MD = ROOT / "RULES.md"


def load_dotenv(path: Path = ROOT / ".env") -> None:
    """Minimal .env loader (no dependency). Existing env vars win."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        val = val.split(" #", 1)[0].strip().strip('"').strip("'")
        if val and key.strip() not in os.environ:
            os.environ[key.strip()] = val


@lru_cache
def cfg() -> dict:
    return yaml.safe_load((ROOT / "config.yaml").read_text())


@lru_cache
def streamers() -> dict[str, dict]:
    raw = yaml.safe_load((ROOT / "streamers.yaml").read_text()) or {}
    return {s["handle"].lower(): s for s in raw.get("streamers") or [] if s.get("handle")}


def secret(name: str, required: bool = True) -> str | None:
    load_dotenv()
    val = os.environ.get(name) or None
    if required and not val:
        raise SystemExit(
            f"Missing {name}. Add it to .env (see CONNECT.md). Do not paste it into chat."
        )
    return val


def ensure_dirs() -> None:
    for d in (STATE, DATA, OUT, REFS, REVIEW, HISTORY, REPORTS):
        d.mkdir(parents=True, exist_ok=True)
