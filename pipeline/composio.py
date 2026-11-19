"""Composio over plain REST (v3.1) — connect accounts, inspect tools, execute them, upload files.

Uses REST instead of the SDK so it installs anywhere. Keys come from .env only.
"""
from __future__ import annotations

import hashlib
import mimetypes
from pathlib import Path

import requests

from .config import cfg, secret

BASE = "https://backend.composio.dev/api/v3.1"


def _h() -> dict:
    return {"x-api-key": secret("COMPOSIO_API_KEY"), "Content-Type": "application/json"}


def _user() -> str:
    return cfg()["publish"]["composio_user_id"]


def _get(path: str, **params) -> dict:
    r = requests.get(f"{BASE}{path}", headers=_h(), params=params, timeout=60)
    r.raise_for_status()
    return r.json()


def _post(path: str, body: dict) -> dict:
    r = requests.post(f"{BASE}{path}", headers=_h(), json=body, timeout=600)
    if r.status_code >= 400:
        raise RuntimeError(f"Composio {path} -> {r.status_code}: {r.text[:500]}")
    return r.json()


# ------------------------------------------------------------------ connections
def auth_config_id(toolkit: str) -> str:
    pinned = secret(f"COMPOSIO_AUTH_CONFIG_{toolkit.upper()}", False)
    if pinned:
        return pinned
    items = _get("/auth_configs", toolkit_slug=toolkit.lower()).get("items", [])
    if not items:
        raise SystemExit(
            f"No Composio auth config for {toolkit}. In platform.composio.dev: Auth Configs -> Create -> "
            f"{toolkit} -> 'Use Composio managed auth' -> Create. Then re-run this command.")
    return items[0]["id"]


def connect_link(toolkit: str) -> str:
    """Returns the URL the owner clicks to connect the account. No keys pass through chat."""
    body = {"auth_config_id": auth_config_id(toolkit), "user_id": _user()}
    r = _post("/connected_accounts/link", body)
    return r.get("redirect_url") or r.get("redirectUrl") or str(r)


def connections() -> dict[str, str]:
    items = _get("/connected_accounts", user_ids=_user(), limit=100).get("items", [])
    out = {}
    for it in items:
        slug = (it.get("toolkit") or {}).get("slug") or it.get("toolkit_slug") or "?"
        out[slug.lower()] = it.get("status", "?")
    return out


# ------------------------------------------------------------------ tools
def list_tools(toolkit: str) -> list[dict]:
    return _get("/tools", toolkit_slug=toolkit.lower(), limit=300).get("items", [])


def tool_schema(slug: str) -> dict:
    return _get(f"/tools/{slug}")


def upload_file(path: Path, toolkit: str, tool_slug: str) -> dict:
    path = Path(path)
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    md5 = hashlib.md5(path.read_bytes()).hexdigest()
    req = _post("/files/upload/request", {"toolkit_slug": toolkit.lower(), "tool_slug": tool_slug,
                                         "filename": path.name, "mimetype": mime, "md5": md5})
    url = req.get("new_presigned_url") or req.get("newPresignedUrl")
    headers = {"Content-Type": mime}
    if (req.get("metadata") or {}).get("storage_backend") == "azure_blob_storage":
        headers["x-ms-blob-type"] = "BlockBlob"
    with path.open("rb") as f:
        put = requests.put(url, data=f, headers=headers, timeout=1800)
    put.raise_for_status()
    return {"name": path.name, "mimetype": mime, "s3key": req["key"]}


def execute(slug: str, arguments: dict) -> dict:
    r = _post(f"/tools/execute/{slug}", {"user_id": _user(), "arguments": arguments})
    if r.get("successful") is False or r.get("error"):
        raise RuntimeError(f"{slug} failed: {r.get('error') or r}")
    return r.get("data") or r


def build_args(slug: str, toolkit: str, values: dict, files: dict[str, Path]) -> dict:
    """Map our values onto whatever the tool's schema calls them; upload files the schema marks uploadable."""
    schema = tool_schema(slug)
    props = (schema.get("input_parameters") or schema.get("inputParameters") or {}).get("properties", {})
    norm = {k.lower().replace("_", ""): k for k in props}
    args = {}
    for key, val in values.items():
        k = norm.get(key.lower().replace("_", ""))
        if k and val not in (None, ""):
            args[k] = val
    for key, path in files.items():  # key is e.g. "video" or "thumbnail"
        candidates = [p for p in props if key in p.lower() and p not in args]
        candidates.sort(key=lambda p: not props[p].get("file_uploadable"))  # prefer uploadable params
        if not candidates:
            continue
        pname = candidates[0]
        if props[pname].get("file_uploadable"):
            args[pname] = upload_file(path, toolkit, slug)
        else:
            raise RuntimeError(f"{slug}.{pname} wants a URL/path, not an upload. Route this platform through upload_post instead.")
    missing = [r for r in (schema.get("input_parameters") or {}).get("required", []) if r not in args]
    if missing:
        raise RuntimeError(f"{slug}: could not fill required params {missing}. Check with `python -m pipeline composio-tools {toolkit}`.")
    return args
