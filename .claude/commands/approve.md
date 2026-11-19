---
description: Owner approves items for posting
argument-hint: <item id> [more ids] | all-passed
---
The owner is approving: $ARGUMENTS
If it says `all-passed`, list `python -m pipeline items --status gauntlet_pass` and approve exactly those. Otherwise approve the given ids with `python -m pipeline approve <ids>`. Then show what's now queued and the next schedule slots. Commit.
