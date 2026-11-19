"""Tiny Apify REST client (run actor -> wait -> fetch dataset)."""
from __future__ import annotations

import time
from typing import Any

import requests

from .config import secret

API = "https://api.apify.com/v2"


def _headers() -> dict:
    return {"Authorization": f"Bearer {secret('APIFY_TOKEN')}"}


def run_actor(actor_id: str, run_input: dict, timeout_s: int = 900, max_items: int | None = None) -> list[dict]:
    if not actor_id:
        raise ValueError("No actor id configured")
    act = actor_id.replace("/", "~")
    r = requests.post(f"{API}/acts/{act}/runs", json=run_input, headers=_headers(), timeout=60)
    r.raise_for_status()
    run = r.json()["data"]
    run_id, dataset = run["id"], run["defaultDatasetId"]
    deadline = time.time() + timeout_s
    status = run["status"]
    while status in ("READY", "RUNNING") and time.time() < deadline:
        time.sleep(5)
        status = requests.get(f"{API}/actor-runs/{run_id}", headers=_headers(), timeout=30).json()["data"]["status"]
    if status != "SUCCEEDED":
        raise RuntimeError(f"Apify run {run_id} for {actor_id} ended with status {status}")
    params: dict[str, Any] = {"clean": "true", "format": "json"}
    if max_items:
        params["limit"] = max_items
    items = requests.get(f"{API}/datasets/{dataset}/items", params=params, headers=_headers(), timeout=120)
    items.raise_for_status()
    return items.json()


def pick(d: dict, *paths: str, default=None):
    """Return the first non-empty value among dotted paths. Actors rename fields; this absorbs it."""
    for p in paths:
        cur: Any = d
        for part in p.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                cur = None
                break
        if cur not in (None, "", []):
            return cur
    return default
