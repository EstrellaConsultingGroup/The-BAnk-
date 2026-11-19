---
description: Prompt 2b — pull recent videos from approved channels, save outliers.csv, tell me what changed
---
Use the `scout` subagent to run `python -m pipeline outliers` and summarise the weekly report in reports/. Then have `thumbnail-studio` refresh THUMBNAILS.md from the new outliers (`/thumbnails study`). Commit outliers.csv, history/ and reports/.
