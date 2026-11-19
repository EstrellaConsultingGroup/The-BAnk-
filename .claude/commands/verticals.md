---
description: Prompt 6 — cut today's strongest clips into verticals and run each through the gauntlet
argument-hint: [how many, default 5]
---
1. `vertical-cutter` subagent: `python -m pipeline verticals --top N` where N = $ARGUMENTS (default 5), check payoff-first frames, fix labels/captions.
2. Gauntlet each vertical with a fresh `gauntlet` subagent (folder path only). Fix and repeat until YES, max 4 tries each.
3. List the passed verticals for my approval with their file paths and captions. Do not approve them yourself.
