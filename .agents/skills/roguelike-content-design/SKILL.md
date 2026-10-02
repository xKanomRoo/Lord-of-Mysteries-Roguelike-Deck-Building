---
name: roguelike-content-design
description: Build original deckbuilding content around distinct decisions, synergies and playable encounters rather than increasing definition counts alone.
---

# Roguelike content design

Use when the player asks for more things to do, better replayability, powers,
characters, varied enemies, routes, events, rewards, or a more enjoyable run.
Apply without requiring the player to specify rules or balance numbers.

## Read first

As a worker, propose questions to the coordinator instead of asking the user directly.
The coordinator merges questions across all roles, at most 1–3 per work cycle.
When working standalone, also fulfill the coordinator's communication/memory role.

Read `AGENTS.md`, `docs/PLAYER_VISION.md`, `docs/design/DECISIONS.md`,
`docs/design/CURRENT_TASK.md`, `docs/CONTENT_DESIGN.md`, `docs/EVIDENCE_STATUS.md`
and `docs/ANDROID_BUILD.md`. Inspect `mobile/data/content.json`,
`mobile/scripts/game_engine.gd`, `mobile/scripts/main.gd` and relevant tests.
For novel-derived themes use the `lore-reference-research` skill.

## Define the experience

1. Convert the player's words into something they will do and notice. “คอมโบ
   เยอะขึ้น” means different setup/payoff choices with understandable effects,
   not many cards differing only in damage. “เล่นได้เรื่อย ๆ” means varied runs
   and ways to build a deck; do not promise infinite authored content.
2. Read existing preferences before asking anything. Choose low-impact defaults
   and state assumptions. Ask at most 1–3 meaningful Thai questions only if a
   preference changes the result, using gameplay or visual examples instead of
   asking for schemas, effect names or balancing expertise.
3. Describe one small content set in plain Thai: player fantasy, two different
   strategies, their tradeoff, the enemy that challenges them and the reward.
   Make it playable from the first encounter, not a future-design document only.

## Design and implement

- Give each new card an identifiable job, cost, payoff, drawback and illustration
  need. Link setups to payoffs without making the payoff mandatory for survival.
  Prefer meaningfully different actions to renamed or higher-number duplicates.
- Include an encounter or event where the new mechanic changes a decision.
  Let enemy intent teach a response; give routes/rewards a visible tradeoff.
- Reuse supported effects only when they express the design. New effects require
  engine rules, save compatibility, UI explanations, visuals and behavior checks
  before JSON definitions can claim to work. Keep IDs stable and seeds deterministic.
- Ensure descriptions match timing, status expiry, cost and actual effects. Explain
  keywords in a short player-facing sentence and show costs before a choice.
- Check zero-cost draw/energy loops, duplicate relic rewards, unavailable choices,
  dead-end decks, invalid saves and paths that are much easier without a reason.
  Current free-draw cards use Exhaust; understand that guard before changing it.
- Use CZN's verified cost/effect/condition separation as structural inspiration.
  Its 278 card rows include variants; coefficients 100/220/500 are not confirmed
  flat damage. Do not label our invented rules recovered CZN rules or novel canon.
- Coordinate with `game-art-direction` for card art, character/stage changes and
  feedback. New definitions alone cannot fulfill a request for a better-looking game.

## Meaningful checks

Run `python -m unittest discover -s tests -p 'test_mobile_content.py' -v` for
definition integrity and the native `mobile/tests/test_engine.gd` suite for rules.
Add a behavioral regression only for a real new rule or observed failure; do not
mirror JSON entries with redundant assertions or weaken existing checks.

Play the new set through legal actions: demonstrate setup/payoff and an alternative
line, enemy counterplay, a meaningful reward decision and a recoverable failure.
Replay the seed to verify deterministic state and test save/resume where state
changes. Inspect the actual native UI and first-turn comprehension; rule tests
cannot show whether effects are visible or interesting. Build/verify the APK when
shipping changed native content. Record the seed, choices, outcomes and limits.

## Delivery and memory

Deliver a playable slice with representative runtime images and a plain Thai
explanation of what the player can try. Report counts only after showing the
different decisions they enable. Separate machine validation, designer playthrough
and user feedback; never claim that tests prove greater fun or all-seed balance.

Return proposed memory entries for agreed goals, original-rule decisions, evidence,
results and next work. Only the coordinator writes `docs/PLAYER_VISION.md`,
`docs/design/DECISIONS.md` and `docs/design/CURRENT_TASK.md`; workers do not edit
these shared files. Delegate only
independent tasks with explicit ownership; do not create more repositories or
agents merely to increase the apparent size of the team.
