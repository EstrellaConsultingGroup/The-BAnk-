"""Unit tests. Everything that touches state uses a temporary directory, never the real ledger."""
from datetime import datetime, timedelta, timezone

import pytest

from pipeline import clips, gauntlet, ledger, outliers
from pipeline.util import parse_duration, to_int


def test_parsers():
    assert parse_duration("1:02:03") == 3723
    assert parse_duration("PT12M3S") == 723
    assert parse_duration(45) == 45
    assert to_int("1.2M") == 1_200_000
    assert to_int("12,345 views") == 12345


def test_outliers_keep_videos_far_above_channel_median():
    now = datetime.now(timezone.utc)
    vids = [{"channel": "c", "channel_url": "u", "title": f"v{i}", "url": f"x{i}", "views": 20_000,
             "published": (now - timedelta(days=5 + i)).isoformat()} for i in range(8)]
    vids.append({"channel": "c", "channel_url": "u", "title": "GTA 6 FUNNIEST moments", "url": "big",
                 "views": 200_000, "published": (now - timedelta(days=4)).isoformat()})
    vids.append({"channel": "c", "channel_url": "u", "title": "too young", "url": "young",
                 "views": 900_000, "published": (now - timedelta(hours=3)).isoformat()})
    out = outliers.compute_outliers(vids)
    assert [o["url"] for o in out] == ["big"]
    assert out[0]["format"] == "compilation" and out[0]["ratio"] == 10.0


def test_clip_ranking_filters(monkeypatch):
    monkeypatch.setattr(clips, "streamers", lambda: {"ok_guy": {"permission": "campaign"}})
    monkeypatch.setattr(clips, "_used", lambda: {"old"})
    now = datetime.now(timezone.utc)
    mk = lambda url, who, title, views, hrs: {"source": "twitch", "clip_id": url, "streamer": who, "title": title,
                                              "views": views, "created": (now - timedelta(hours=hrs)).isoformat(),
                                              "duration_s": 30, "url": url}
    ranked = clips.rank([
        mk("a", "ok_guy", "insane chase", 1000, 2),
        mk("b", "ok_guy", "the ENDING cutscene", 9000, 1),
        mk("c", "stranger", "huge jump", 5000, 1),
        mk("old", "ok_guy", "repeat", 9000, 1),
        mk("d", "ok_guy", "boat flip", 3000, 1),
    ])
    status = {r["url"]: r["status"] for r in ranked}
    assert status == {"a": "ok", "b": "skipped", "c": "needs_permission", "old": "skipped", "d": "ok"}
    ok = [r["url"] for r in ranked if r["status"] == "ok"]
    assert ok == ["d", "a"]  # ranked by views per hour, not raw views


def test_parse_gauntlet_reply():
    r = gauntlet.parse_reply("VERDICT: NO\nWINNER_THUMB: thumb_2.jpg\nWINNER_TITLE: \"Every Secret\"\nFAULTS:\n- caption under buttons\n- slow open")
    assert r == {"passed": False, "faults": ["caption under buttons", "slow open"], "thumb": "thumb_2.jpg", "title": "Every Secret"}
    assert gauntlet.parse_reply("VERDICT: YES\nWINNER_THUMB: -\nFAULTS:\n- none")["faults"] == []


@pytest.fixture
def temp_ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger, "ITEMS", tmp_path / "items.json")
    monkeypatch.setattr(ledger, "STATE", tmp_path)
    monkeypatch.setattr(ledger, "STATUS_MD", tmp_path / "STATUS.md")
    monkeypatch.setattr(ledger, "RULES_MD", tmp_path / "RULES.md")
    return tmp_path


def test_gates_block_until_gauntlet_and_owner(temp_ledger):
    ledger.register("x", "vertical", temp_ledger)
    assert ledger.can_publish(ledger.get("x")) == (False, "no gauntlet verdict")
    with pytest.raises(SystemExit):
        ledger.approve("x")  # cannot approve before a pass
    ledger.record_verdict("x", False, ["slow open"])
    assert ledger.can_publish(ledger.get("x"))[1] == "last gauntlet verdict was NO"
    ledger.record_verdict("x", True, [])
    assert ledger.can_publish(ledger.get("x"))[1] == "not approved by owner"
    ledger.approve("x")
    assert ledger.can_publish(ledger.get("x")) == (True, "")
    rules = (temp_ledger / "RULES.md").read_text()
    assert "try 1 · **NO**" in rules and "try 2 · **YES**" in rules
    ledger.register("x", "vertical", temp_ledger)  # re-render
    assert ledger.get("x")["status"] == "draft" and "approved_at" not in ledger.get("x")
