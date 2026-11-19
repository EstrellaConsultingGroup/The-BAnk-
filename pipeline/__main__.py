"""python -m pipeline <command> — the deterministic half of the GTA 6 channel agent.

Agents (see .claude/agents) make the judgement calls; these commands do the scraping, maths and rendering.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from .config import ROOT, cfg, ensure_dirs, load_dotenv, secret


def cmd_doctor(_):
    """Prompt 1: check tools + connections. Never prints a secret."""
    ok = True
    for tool in ("ffmpeg", "ffprobe", "yt-dlp", "scenedetect"):
        found = shutil.which(tool)
        print(f"{'✓' if found else '✗'} {tool}")
        ok &= bool(found)
    try:
        import faster_whisper  # noqa: F401
        print("✓ faster-whisper")
    except ImportError:
        print("✗ faster-whisper")
        ok = False
    load_dotenv()
    for key, why in [("COMPOSIO_API_KEY", "YouTube + Instagram"), ("APIFY_TOKEN", "scraping"),
                     ("UPLOAD_POST_API_KEY", "TikTok"), ("UPLOAD_POST_USER", "TikTok profile"),
                     ("OPENAI_API_KEY", "gpt-image thumbnails (optional)"), ("GEMINI_API_KEY", "nano banana thumbnails (optional)"),
                     ("TWITCH_CLIENT_ID", "Twitch clips (optional)")]:
        print(f"{'✓' if secret(key, False) else '·'} {key:22} {why}")
    if secret("COMPOSIO_API_KEY", False):
        try:
            from . import composio
            conns = composio.connections()
            for tk in ("youtube", "instagram", "apify"):
                print(f"  composio/{tk}: {conns.get(tk, 'not connected')}")
        except Exception as e:
            print(f"  composio: could not list connections ({e})")
    print(f"\ngates: {cfg()['gates']}")
    return 0 if ok else 1


def cmd_connect(a):
    from . import composio
    print(f"Open this link and approve access for {a.toolkit}:\n{composio.connect_link(a.toolkit)}")


def cmd_composio_tools(a):
    from . import composio
    for t in composio.list_tools(a.toolkit):
        if a.grep and a.grep.lower() not in (t.get("slug", "") + t.get("name", "")).lower():
            continue
        print(f"{t.get('slug')}: {t.get('description', '')[:110]}")
        if a.schema:
            print(json.dumps(composio.tool_schema(t["slug"]).get("input_parameters", {}), indent=1)[:3000])


def cmd_channels(a):
    from . import outliers
    if a.action == "discover":
        rows = outliers.discover_channels()
        print(f"{len(rows)} active English channels -> state/channel_candidates.csv")
        for r in rows[:60]:
            print(f"- {r['channel']} · {r['subscribers']:,} subs · last upload {r['days_since_upload']}d ago · {r['url']}")
        print("\nShow this list to the owner and WAIT for their OK before `channels approve`.")
    elif a.action == "approve":
        chosen = outliers.approve_channels(a.names.split(",") if a.names else None, a.all)
        print(f"approved {len(chosen)} channels -> channels.yaml")
    else:
        for c in outliers.approved_channels():
            print(f"- {c['channel']} {c['url']}")


def cmd_outliers(_):
    from . import outliers
    rows, report = outliers.run_outliers()
    print(f"{len(rows)} outliers -> outliers.csv\nweekly diff -> {report.relative_to(ROOT)}\n")
    print(report.read_text())


def cmd_thumbs(a):
    from . import thumbnails
    if a.action == "refs":
        print(f"reference sheet -> {thumbnails.fetch_refs()}")
    elif a.action == "make":
        m = thumbnails.make(a.item, a.prompt or [], a.text or [], a.title or [], a.provider,
                            [float(t) for t in a.frame_time] if a.frame_time else None)
        print(json.dumps(m, indent=2))


def cmd_clips(a):
    from . import clips
    keep, path = clips.run_daily()
    print(f"{len(keep)} usable clips -> {path.relative_to(ROOT)}")
    for r in keep[:15]:
        print(f"{r['rank']:>3}. {r['vph']:>9,.0f} v/h · {r['source']:6} · @{r['streamer']} · {r['title'][:60]} · {r['url']}")
    blocked = [r for r in clips.read_csv(path) if r["status"] == "needs_permission"][:10]
    if blocked:
        print("\nTop clips we can't use yet (streamer not cleared in streamers.yaml):")
        for r in blocked:
            print(f"   {r['vph']:>9} v/h · @{r['streamer']} · {r['url']}")


def cmd_episode(a):
    from . import clips, episode
    if a.action == "plan":
        rows = clips.load_ok()
        if a.download:
            rows = clips.download(rows[: a.max])
        print(f"plan -> {episode.plan(rows, a.target).relative_to(ROOT)}")
    else:
        print(json.dumps(episode.render(Path(a.plan)), indent=2)[:3000])


def cmd_verticals(a):
    from . import clips, vertical
    rows = clips.load_ok()[: a.top]
    rows = clips.download(rows)
    for r in rows:
        try:
            m = vertical.render(r)
            print(f"✓ {m['id']}  ({m['duration_s']}s, payoff at {m['payoff_s']}s{' · LETTERBOXED' if m['letterboxed'] else ''})")
        except Exception as e:
            print(f"✗ {r['url']}: {e}")


def cmd_vertical_file(a):
    """Render one vertical from a local file (testing, or clips you were sent directly)."""
    from . import vertical
    row = {"file": a.file, "url": a.url or a.file, "source": a.source, "streamer": a.streamer,
           "title": a.label or "WAIT FOR IT", "clip_id": Path(a.file).stem}
    print(json.dumps(vertical.render(row, a.label), indent=2))


def cmd_own(a):
    from . import own
    if a.action == "brief":
        print(f"brief -> {own.brief(a.topic, a.format).relative_to(ROOT)}/brief.md")
    elif a.action == "script-done":
        print(own.register_script(a.item))
    elif a.action == "video":
        print(own.register_video(a.item, Path(a.file), a.title, Path(a.description).read_text() if a.description else ""))


def cmd_gauntlet(a):
    from . import gauntlet
    p = gauntlet.pack(a.item)
    print(f"review packet -> {p.relative_to(ROOT)}\nHand ONLY this folder to the `gauntlet` subagent.")


def cmd_verdict(a):
    from . import gauntlet, ledger, thumbnails
    if a.reply_file:
        r = gauntlet.parse_reply(Path(a.reply_file).read_text())
        passed, faults, thumb, title = r["passed"], r["faults"], r["thumb"], r["title"]
    else:
        passed, faults, thumb, title = a.verdict == "yes", a.fault or [], a.thumb, a.title
    winner = " | ".join(x for x in (thumb, title) if x)
    item = ledger.record_verdict(a.item, passed, faults, winner)
    if passed and item["kind"] == "packaging":
        thumbnails.apply_winners(a.item, thumb or "", title or "")
    print(f"{a.item}: {'YES' if passed else 'NO'} -> {item['status']} (logged to RULES.md)")
    rec = ledger.recurring_faults()
    if rec:
        print("\nRecurring faults — consider promoting to a standing rule in RULES.md:")
        for f, n in rec[:5]:
            print(f"  {n}x  {f}")


def cmd_approve(a):
    """ONLY when the owner explicitly approves in chat."""
    from . import ledger
    for i in a.items:
        ledger.approve(i)
        print(f"approved {i}")


def cmd_items(a):
    from . import ledger
    for iid, it in sorted(ledger.load().items(), key=lambda kv: kv[1]["created"]):
        if a.status and it["status"] != a.status:
            continue
        print(f"{it['status']:14} {iid:42} {it['kind']:10} {it.get('title', '')[:50]}")


def cmd_publish(a):
    from . import publish
    if a.due:
        print(publish.due(dry_run=a.dry_run))
    else:
        for i in a.items:
            print(publish.publish_item(i, a.platform, dry_run=a.dry_run))


def cmd_metrics(_):
    from . import metrics
    print(metrics.run().read_text())


def cmd_status(_):
    from . import ledger
    ledger.render_status()
    print((ROOT / "STATUS.md").read_text())


def main(argv=None):
    ensure_dirs()
    p = argparse.ArgumentParser(prog="pipeline")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor").set_defaults(f=cmd_doctor)
    s = sub.add_parser("connect"); s.add_argument("toolkit"); s.set_defaults(f=cmd_connect)
    s = sub.add_parser("composio-tools"); s.add_argument("toolkit"); s.add_argument("--grep"); s.add_argument("--schema", action="store_true"); s.set_defaults(f=cmd_composio_tools)
    s = sub.add_parser("channels"); s.add_argument("action", choices=["discover", "approve", "list"]); s.add_argument("--names"); s.add_argument("--all", action="store_true"); s.set_defaults(f=cmd_channels)
    sub.add_parser("outliers").set_defaults(f=cmd_outliers)
    s = sub.add_parser("thumbs"); s.add_argument("action", choices=["refs", "make"]); s.add_argument("--item")
    s.add_argument("--prompt", action="append"); s.add_argument("--text", action="append"); s.add_argument("--title", action="append")
    s.add_argument("--provider", choices=["openai", "gemini", "frame"]); s.add_argument("--frame-time", action="append"); s.set_defaults(f=cmd_thumbs)
    sub.add_parser("clips").set_defaults(f=cmd_clips)
    s = sub.add_parser("episode"); s.add_argument("action", choices=["plan", "render"]); s.add_argument("--download", action="store_true")
    s.add_argument("--max", type=int, default=30); s.add_argument("--target", type=float); s.add_argument("--plan"); s.set_defaults(f=cmd_episode)
    s = sub.add_parser("verticals"); s.add_argument("--top", type=int, default=5); s.set_defaults(f=cmd_verticals)
    s = sub.add_parser("vertical-file"); s.add_argument("file"); s.add_argument("--streamer", required=True)
    s.add_argument("--source", default="twitch"); s.add_argument("--url"); s.add_argument("--label"); s.set_defaults(f=cmd_vertical_file)
    s = sub.add_parser("own"); s.add_argument("action", choices=["brief", "script-done", "video"]); s.add_argument("--topic")
    s.add_argument("--format", default="guide"); s.add_argument("--item"); s.add_argument("--file"); s.add_argument("--title")
    s.add_argument("--description"); s.set_defaults(f=cmd_own)
    s = sub.add_parser("gauntlet"); s.add_argument("item"); s.set_defaults(f=cmd_gauntlet)
    s = sub.add_parser("verdict"); s.add_argument("item"); s.add_argument("verdict", nargs="?", choices=["yes", "no"])
    s.add_argument("--fault", action="append"); s.add_argument("--thumb"); s.add_argument("--title"); s.add_argument("--reply-file"); s.set_defaults(f=cmd_verdict)
    s = sub.add_parser("approve"); s.add_argument("items", nargs="+"); s.set_defaults(f=cmd_approve)
    s = sub.add_parser("items"); s.add_argument("--status"); s.set_defaults(f=cmd_items)
    s = sub.add_parser("publish"); s.add_argument("items", nargs="*"); s.add_argument("--due", action="store_true")
    s.add_argument("--platform", action="append"); s.add_argument("--dry-run", action="store_true", default=None); s.set_defaults(f=cmd_publish)
    sub.add_parser("metrics").set_defaults(f=cmd_metrics)
    sub.add_parser("status").set_defaults(f=cmd_status)
    a = p.parse_args(argv)
    return a.f(a) or 0


if __name__ == "__main__":
    sys.exit(main())
