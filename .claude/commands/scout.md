---
description: Prompt 2a — find active English GTA YouTube channels and wait for my OK
---
Use the `scout` subagent to discover channels (`python -m pipeline channels discover`). Show me the grouped list and stop. Only after I reply with which ones to keep, run `python -m pipeline channels approve --names "..."` (or `--all` if I say all), then commit.
