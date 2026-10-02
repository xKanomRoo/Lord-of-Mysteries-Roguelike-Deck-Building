# Game skills

These are repository-local skills, not a separately installed plugin or model training.
Start with [dream-game-director](dream-game-director/SKILL.md); load only the relevant
specialist skill. Root `AGENTS.md` and the saved cloud startup instructions provide a
file-reading fallback when a runtime does not expose these names in its skill catalog.

See [the role map](../../docs/AGENT_TEAM.md) and [the player's brief](../../docs/PLAYER_VISION.md).
Workers share one checkout; the coordinator assigns paths and alone writes shared memory.
Runtime collaboration tools enable actual sub-agents; without them use sequential lanes.
