---
description: Prompt 1 — set up tools and connections (setup only, nothing gets posted)
---
Today is setup only. Read RULES.md and STATUS.md first.

1. Run `./setup.sh` (installs ffmpeg, yt-dlp, scenedetect, faster-whisper and Python deps), then `python -m pipeline doctor`.
2. For every ✗ or missing key, tell me exactly what to click, using CONNECT.md. Never ask me for a key in chat — tell me which line of `.env` to fill.
3. Once `COMPOSIO_API_KEY` is in `.env`, run `python -m pipeline connect youtube` and `python -m pipeline connect instagram` (and `apify` if I want it through Composio) and give me the links to click.
4. TikTok goes through Upload-Post: walk me through connecting TikTok there and filling `UPLOAD_POST_API_KEY` / `UPLOAD_POST_USER`.
5. Verify the Composio upload tool names: `python -m pipeline composio-tools youtube --grep upload` and `... instagram --grep reel`; fix `publish.composio_tools` in config.yaml if they differ.
6. Confirm RULES.md contains the gauntlet rule and "post only what I approve". Tick the setup checklist in STATUS.md, commit, and summarise what's left for me to do.
