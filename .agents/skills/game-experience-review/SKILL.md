---
name: game-experience-review
description: Review the actual native player experience against recorded wishes using first-turn comprehension, visible art, meaningful choices and honest device evidence.
---

# Game experience review

Use before reporting a native feature complete, delivering an APK, or responding
to “ดูไม่สนุก”, “ไม่สวย”, “มีแต่ตัวหนังสือ” or “ไม่เหมือนที่อยากได้”.
Review the result the player will see and operate, beyond whether rules pass tests.

## Read and inspect

As a worker, propose questions to the coordinator instead of asking the user directly.
The coordinator merges questions across all roles, at most 1–3 per work cycle.
When working standalone, also fulfill the coordinator's communication/memory role.

Read `AGENTS.md`, `docs/PLAYER_VISION.md`, `docs/design/DECISIONS.md`,
`docs/design/CURRENT_TASK.md`, `docs/CONTENT_DESIGN.md`,
`docs/REFERENCE_VISUAL_RESULTS.md`, `docs/ANDROID_BUILD.md` and
`docs/VALIDATION.md`. Inspect the current native scene and current runtime images,
not a previous version's screenshots or an image-generation concept.

## Review from the player's perspective

1. Turn the recorded wish into a short acceptance checklist. Translate “สวยขึ้น”
   into visible character/stage/card art, readable hierarchy and feedback. Translate
   “สนุกขึ้น” into a new understandable choice, tradeoff and consequence to try.
2. Reuse accepted preferences; do not make the player repeat them. Resolve routine
   reversible details yourself. Ask at most 1–3 short Thai questions only when the
   remaining preference matters, and use inspected visual/gameplay choices where
   useful. The user should not need to know engines, balance theory or UI terminology.
3. Play the first encounter without relying on source code to understand it. Can
   the player find their character, enemy intent, energy/cost, usable cards, target,
   result of a tap and End turn? Does a short description explain a risky choice?
4. Test a normal turn, insufficient-cost/disabled action, enemy hit and status,
   reward/event choice, restart, local save/resume and relevant error states.
   Include the new strategy and an alternative, not a single scripted victory only.

## Inspect the actual native experience

- Render Godot Control UI with a real display backend and save its framebuffer.
  Headless rule/layout checks do not establish visual quality. Use the pinned
  toolchain and writable task-specific XDG directories under `.local/`.
- Run `mobile/tests/test_ui.gd` with a real renderer and
  `--screenshot-dir=<ignored-output-directory>` after Godot's `--` separator.
  Inspect the resulting frames yourself; a saved file or nonzero check count alone
  is insufficient. Treat SCRIPT ERROR/ERROR and failed assertions as unresolved.
- Check at least a compact landscape and the intended phone aspect ratio: cropping,
  overlap, card art/text bounds, touch targets, readable costs and contrast.
  Test actual Control input, including touch where supported; callbacks alone
  do not prove a player can hit the button. Record exactly which input was exercised.
- Assess character distinction, environment depth, illustrative card content,
  animation/action feedback and the balance of pictures versus text. A successful
  engine suite or “54 cards” does not satisfy missing 54 illustrations.
- If artwork remains placeholders in an art-focused task, label it `art incomplete`.
  If generation/render tooling prevents delivery, label it `art blocked` with the
  concrete cause and still finish unaffected checks. Never imply the request is met.

## Checks and evidence limits

Run relevant native engine/content/cloud checks for changed behavior; do not repeat
the entire unrelated browser suite for native art changes. For APK delivery run
`bash tools/build_android.sh`, inspect its verification receipt and confirm the
bundle contains the current assets/content. Preserve package/signing identity.

Distinguish these evidence types explicitly:

| Result | Establishes | Does not establish |
|---|---|---|
| Generated concept | Proposed composition/style | Runtime UI, working touch, APK readiness |
| Native Linux render/input | Current scene draws and tested inputs work | Android hardware launch/performance |
| Export/signature verification | APK built and inspected | Successful installation or play on a phone |
| Actual Android capture | Observed device run on the named device | All-device compatibility or broad player enjoyment |
| Engine/playthrough tests | Checked rules and specific legal runs | Superior fun or balance across every seed |

## Review output and follow-through

Deliver a short plain Thai result with current native images, what the player can
try, observed problems and exact remaining uncertainty. Prefer a few findings
ordered by player impact to a long technical checklist. Ask the implementer to fix
material problems, then recheck the affected experience before marking it complete.
Do not only write a criticism document while presenting the broken feature as done.

Return proposed memory entries for acceptance, results, evidence locations and next
work. Only the coordinator writes `docs/PLAYER_VISION.md`,
`docs/design/DECISIONS.md` and `docs/design/CURRENT_TASK.md`; workers do not edit
these shared files. Do not spawn redundant
reviewers or assign multiple agents the same files.
