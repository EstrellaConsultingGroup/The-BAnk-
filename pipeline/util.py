from __future__ import annotations

import csv
import re
import statistics
from datetime import datetime, timezone
from pathlib import Path


def parse_time(v) -> datetime | None:
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        ts = v / 1000 if v > 1e12 else v
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    s = str(v).strip().replace("Z", "+00:00")
    for fmt in (None, "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S.%f%z"):
        try:
            dt = datetime.fromisoformat(s) if fmt is None else datetime.strptime(s, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def parse_duration(v) -> float | None:
    """'1:02:03', '12:34', 'PT12M3S', 754, '754' -> seconds."""
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if re.fullmatch(r"\d+(\.\d+)?", s):
        return float(s)
    m = re.fullmatch(r"P?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?", s.upper())
    if m and any(m.groups()):
        h, mi, se = (float(x or 0) for x in m.groups())
        return h * 3600 + mi * 60 + se
    parts = s.split(":")
    if all(p.isdigit() for p in parts):
        total = 0.0
        for p in parts:
            total = total * 60 + int(p)
        return total
    return None


def to_int(v) -> int:
    if v in (None, ""):
        return 0
    if isinstance(v, (int, float)):
        return int(v)
    s = str(v).replace(",", "").strip().upper()
    mult = 1
    for suf, m in (("K", 1e3), ("M", 1e6), ("B", 1e9)):
        if s.endswith(suf):
            s, mult = s[:-1], m
    try:
        return int(float(s) * mult)
    except ValueError:
        digits = re.sub(r"\D", "", s)
        return int(digits) if digits else 0


def median(xs) -> float:
    xs = [x for x in xs if x is not None]
    return float(statistics.median(xs)) if xs else 0.0


def write_csv(path: Path, rows: list[dict], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = fields or (list(rows[0].keys()) if rows else [])
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def slug(s: str, n: int = 40) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:n] or "item"


def fmt_ts(sec: float) -> str:
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def english_score(texts: list[str]) -> float:
    """Cheap language check: share of titles that look English."""
    if not texts:
        return 0.0
    common = {"the", "a", "i", "in", "to", "of", "and", "is", "this", "you", "my", "how", "every",
              "new", "best", "all", "on", "with", "for", "it", "was", "what", "we", "are", "gta"}
    ok = 0
    for t in texts:
        letters = [c for c in t if c.isalpha()]
        ascii_ratio = sum(c.isascii() for c in letters) / max(len(letters), 1)
        words = set(re.findall(r"[a-z']+", t.lower()))
        if ascii_ratio > 0.9 and (words & common):
            ok += 1
    return ok / len(texts)
