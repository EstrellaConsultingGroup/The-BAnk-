"""Item registry + STATUS.md / RULES.md writers.

Every piece of content (episode, vertical, own video, thumbnail set) is an *item* with a lifecycle:

    draft -> gauntlet_fail -> (fix) -> draft -> gauntlet_pass -> approved -> posted

Nothing can be approved without a gauntlet pass, and nothing can be posted without approval
(while gates.require_human_approval is true).
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from .config import RULES_MD, STATE, STATUS_MD, cfg

ITEMS = STATE / "items.json"
AUTO_START, AUTO_END = "<!-- AUTO:START -->", "<!-- AUTO:END -->"


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load() -> dict:
    if ITEMS.exists():
        return json.loads(ITEMS.read_text())
    return {}


def save(items: dict) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    ITEMS.write_text(json.dumps(items, indent=2, sort_keys=True))
    render_status(items)


def get(item_id: str) -> dict:
    items = load()
    if item_id not in items:
        raise SystemExit(f"Unknown item {item_id}. Run: python -m pipeline items")
    return items[item_id]


def register(item_id: str, kind: str, path: Path, title: str = "", **extra) -> dict:
    items = load()
    item = items.get(item_id, {"created": now(), "verdicts": [], "posts": {}})
    item.update(kind=kind, path=str(path), title=title or item.get("title", ""), status="draft", **extra)
    item.pop("approved_at", None)  # a re-render invalidates earlier approval
    items[item_id] = item
    save(items)
    return item


def update(item_id: str, **fields) -> dict:
    items = load()
    items[item_id].update(fields)
    save(items)
    return items[item_id]


# ---------------------------------------------------------------- gauntlet + approval
def record_verdict(item_id: str, passed: bool, faults: list[str], winner: str = "") -> dict:
    items = load()
    item = items[item_id]
    v = {"at": now(), "verdict": "YES" if passed else "NO", "faults": faults, "winner": winner}
    item.setdefault("verdicts", []).append(v)
    item["status"] = "gauntlet_pass" if passed else "gauntlet_fail"
    if winner:
        item["winner"] = winner
    save(items)
    append_verdict_to_rules(item_id, item["kind"], v, attempt=len(item["verdicts"]))
    return item


def approve(item_id: str) -> dict:
    items = load()
    item = items[item_id]
    if cfg()["gates"]["require_gauntlet_pass"] and item["status"] != "gauntlet_pass":
        raise SystemExit(f"{item_id} has not passed the gauntlet (status={item['status']}).")
    item["status"] = "approved"
    item["approved_at"] = now()
    save(items)
    return item


def can_publish(item: dict) -> tuple[bool, str]:
    gates = cfg()["gates"]
    if gates["require_gauntlet_pass"] and not item.get("verdicts"):
        return False, "no gauntlet verdict"
    if gates["require_gauntlet_pass"] and item["verdicts"][-1]["verdict"] != "YES":
        return False, "last gauntlet verdict was NO"
    if gates["require_gauntlet_pass"] and item["status"] not in ("gauntlet_pass", "approved"):
        return False, "changed since its last gauntlet pass — judge it again"
    if gates["require_human_approval"] and item["status"] != "approved":
        return False, "not approved by owner"
    if item["status"] == "posted":
        return False, "already posted"
    return True, ""


def record_post(item_id: str, platform: str, url: str) -> None:
    items = load()
    item = items[item_id]
    item.setdefault("posts", {})[platform] = {"url": url, "at": now()}
    save(items)


# ---------------------------------------------------------------- markdown files
def _replace_auto(path: Path, body: str) -> None:
    text = path.read_text() if path.exists() else f"{AUTO_START}\n{AUTO_END}\n"
    if AUTO_START not in text:
        text = text.rstrip() + f"\n\n{AUTO_START}\n{AUTO_END}\n"
    pre, rest = text.split(AUTO_START, 1)
    _, post = rest.split(AUTO_END, 1)
    path.write_text(f"{pre}{AUTO_START}\n{body.rstrip()}\n{AUTO_END}{post}")


def render_status(items: dict | None = None) -> None:
    items = load() if items is None else items
    gates = cfg()["gates"]
    lines = [
        f"_Auto-generated {now()} — edit notes outside this block._",
        "",
        f"**Gates:** gauntlet={'on' if gates['require_gauntlet_pass'] else 'OFF'} · "
        f"owner approval={'on' if gates['require_human_approval'] else 'OFF'} · "
        f"dry_run={'on' if gates['dry_run'] else 'off'}",
        "",
    ]
    groups = {"approved": [], "gauntlet_pass": [], "gauntlet_fail": [], "draft": [], "posted": []}
    for iid, it in sorted(items.items(), key=lambda kv: kv[1].get("created", ""), reverse=True):
        groups.setdefault(it["status"], []).append((iid, it))

    def row(iid, it):
        last = it["verdicts"][-1] if it.get("verdicts") else None
        v = f"{last['verdict']} ({len(it['verdicts'])} tries)" if last else "—"
        return f"| `{iid}` | {it['kind']} | {it.get('title','')[:60]} | {v} |"

    titles = {
        "approved": "Approved, waiting for a slot",
        "gauntlet_pass": "Passed the gauntlet — waiting for owner approval",
        "gauntlet_fail": "Failed the gauntlet — needs fixing",
        "draft": "Drafts — not judged yet",
    }
    for key, title in titles.items():
        if groups.get(key):
            lines += [f"### {title}", "", "| id | kind | title | gauntlet |", "|---|---|---|---|"]
            lines += [row(i, it) for i, it in groups[key]]
            lines.append("")

    posted = [(i, it) for i, it in items.items() if it.get("posts")]
    lines += ["### Posted links", ""]
    if posted:
        lines += ["| id | platform | link | when |", "|---|---|---|---|"]
        for iid, it in posted:
            for plat, p in it.get("posts", {}).items():
                lines.append(f"| `{iid}` | {plat} | {p['url']} | {p['at'][:16]} |")
    else:
        lines.append("_Nothing posted yet._")
    _replace_auto(STATUS_MD, "\n".join(lines))


def append_verdict_to_rules(item_id: str, kind: str, v: dict, attempt: int) -> None:
    text = RULES_MD.read_text() if RULES_MD.exists() else "# RULES\n"
    if "## Verdict log" not in text:
        text = text.rstrip() + "\n\n## Verdict log\n\n"
    faults = "; ".join(v["faults"]) if v["faults"] else "none"
    win = f" · winner: {v['winner']}" if v.get("winner") else ""
    entry = f"- {v['at'][:16]} · `{item_id}` ({kind}) · try {attempt} · **{v['verdict']}**{win} · faults: {faults}\n"
    RULES_MD.write_text(text.rstrip("\n") + "\n" + entry)


def recurring_faults(min_count: int = 3) -> list[tuple[str, int]]:
    """Faults the gauntlet keeps finding — candidates to promote into a standing rule."""
    counts: dict[str, int] = {}
    for it in load().values():
        for v in it.get("verdicts", []):
            for f in v["faults"]:
                key = re.sub(r"\s+", " ", f.lower()).strip(" .")
                counts[key] = counts.get(key, 0) + 1
    return sorted([(f, n) for f, n in counts.items() if n >= min_count], key=lambda x: -x[1])
