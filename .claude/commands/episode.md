---
description: Prompt 5 — edit today's episode, package it and run it through the gauntlet
---
1. `episode-editor` subagent: plan, label, trim and render today's episode.
2. Gauntlet on the episode (fresh `gauntlet` subagent, folder path only; fix and repeat until YES, max 4).
3. `/thumbnails <episode id>` for titles + thumbnails (also gauntleted).
4. Show me the passed episode (path, length, chosen title, thumbnail path) and ask for approval. Do not approve it yourself.
