# GTA 6 channel agent

An agent team that runs a GTA 6 channel on YouTube, TikTok and Instagram, built from the nine-prompt
"make money from GTA 6 with AI agents" playbook, plus the guardrails it needs to survive.

```
 clips (Twitch/Kick/TikTok) ─► clip-hunter ─► episode-editor ─► ┐
                                         └─► vertical-cutter ─► ├─► thumbnail-studio ─► gauntlet ─► owner approves ─► publisher
 YouTube channels ─► scout ─► outliers.csv ─► THUMBNAILS.md      │      (fresh agent, YES/NO + faults,             (Composio / Upload-Post,
                                         └─► scriptwriter ─────► ┘       redo until YES, logged in RULES.md)          links → STATUS.md)
```

## Quick start

```bash
./setup.sh                      # prompt 1: ffmpeg, yt-dlp, scenedetect, faster-whisper, .env
# fill .env following CONNECT.md, then in Claude Code:
/setup                          # checks everything, gives you links to click
/scout                          # prompt 2: pick channels (waits for your OK)
/outliers                       # prompt 2: outliers.csv + what changed
/thumbnails study               # prompt 3: THUMBNAILS.md
/daily                          # prompts 4, 5, 6, 8, 9
/script the full gta 6 map | guide   # prompt 7
/approve <id> | all-passed      # you, when you like what passed
/weekly                         # refresh outliers + learnings
```

Run `/daily` and `/weekly` on a schedule (Claude Code scheduled tasks or cron with `claude -p "/daily"`).

## What's here

| Path | What |
|---|---|
| `CLAUDE.md` | orchestrator instructions |
| `RULES.md` | hard rules, standing quality rules, the gauntlet verdict log (read first every run) |
| `STATUS.md` | setup checklist, queue, every posted link (read first every run) |
| `THUMBNAILS.md` | what winning thumbnails/titles have in common |
| `.claude/agents/` | scout, thumbnail-studio, clip-hunter, episode-editor, vertical-cutter, scriptwriter, gauntlet, publisher |
| `.claude/commands/` | one slash command per prompt, plus `/daily`, `/weekly`, `/approve` |
| `pipeline/` | `python -m pipeline …` — scraping, outlier maths, ffmpeg editing, captions, uploads, gates |
| `config.yaml` | thresholds, actors, schedule, gates |
| `streamers.yaml` | who you may clip, their facecam position, their clipping campaign |
| `outliers.csv`, `history/`, `reports/` | data the agents learn from (committed) |

## Additions beyond the infographic

- **Rights gate** — only streamers who run a clipping campaign or gave written permission get clipped;
  the rest are listed so you can ask. This is the difference between "clipping" and copyright strikes.
- **Hard approval + gauntlet gates in code**, not just in a prompt: `publish` refuses anything unjudged,
  judged NO, changed since its pass, or not approved by you. Starts in `dry_run`.
- **Gauntlet that is actually fresh**: a read-only subagent gets only a review folder (frames, feed-size
  thumbnails, metadata, outlier examples, rubric) — never the maker's notes. Recurring faults are surfaced
  so they can become standing rules.
- **Payoff detection** (loudest reaction + nearest scene cut) so verticals open on the payoff automatically.
- **Cutscene heuristics**: keyword blocklist plus letterbox detection.
- **YouTube chapters** and full streamer credits in every episode description.
- **Feed-size thumbnail previews**; text drawn locally so it's always spelled right.
- **No double-posting** of a clip; **campaign submission queue** with every link ready.
- **Weekly diff** of outliers and an **own-channel metrics** loop.
- **Paid-campaign disclosure** appended when a campaign requires it.
- Composio via REST (no fragile SDK install), Twitch via the free official API when keys are present.

## Honest limits

- Apify actor ids and Composio tool slugs change. Both are in `config.yaml`; verify them on first run
  (`python -m pipeline composio-tools youtube --grep upload`).
- Most clipping-campaign dashboards need a manual submit; the pipeline queues them with links.
- YouTube may limit monetisation of compilation channels as "reused content". The labels, curation and
  chapters help, but the owner's own videos (prompt 7) are the durable part of the business.
- Payoff detection and facecam layout are heuristics; the vertical-cutter and gauntlet check them.

## Tests

```bash
python -m pytest -q tests
```
