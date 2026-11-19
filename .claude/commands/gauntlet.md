---
description: Prompt 8 — run the gauntlet rule on an item
argument-hint: <item id>
---
1. `python -m pipeline gauntlet $ARGUMENTS` — note the review folder it prints.
2. Spawn the `gauntlet` subagent with ONLY that folder path as its prompt. Nothing about the work, no notes.
3. Save its reply to `<folder>/reply.txt` and run `python -m pipeline verdict $ARGUMENTS --reply-file <folder>/reply.txt`.
4. On NO, fix every fault with the right subagent, then repeat from step 1 with a new fresh gauntlet subagent. Stop after 4 NOs and report.
