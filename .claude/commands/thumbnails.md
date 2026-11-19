---
description: Prompt 3 — study outlier thumbnails or make titles + thumbnails for an item, then run the gauntlet
argument-hint: study | <item id>
---
Argument: $ARGUMENTS

- `study`: use the `thumbnail-studio` subagent to run `python -m pipeline thumbs refs`, study the winners and rewrite THUMBNAILS.md.
- `<item id>`: use `thumbnail-studio` to make 5 titles and 3 thumbnails for that item, then run the gauntlet on `<item id>-pack` exactly as CLAUDE.md describes (fresh `gauntlet` subagent, folder path only). Redo until it says YES (max 4 tries), so the best of each is written into the item.
