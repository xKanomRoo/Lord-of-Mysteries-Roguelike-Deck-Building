---
name: game-art-direction
description: Turn ordinary player wishes into original character, stage, card and interface art with visual examples and actual native game screenshots.
---

# Game art direction

Use when the user asks for a prettier game, recognizable characters, atmosphere,
card illustrations, animation, visual references, or says the game is mostly text.
Also use when a feature changes what the player sees; do not wait for art vocabulary.

## Read first

As a worker, propose questions to the coordinator instead of asking the user directly.
The coordinator merges questions across all roles, at most 1–3 per work cycle.
When working standalone, also fulfill the coordinator's communication/memory role.

Read `AGENTS.md`, `docs/PLAYER_VISION.md`, `docs/design/DECISIONS.md`,
`docs/design/CURRENT_TASK.md`, `docs/REFERENCE_VISUAL_RESULTS.md` and
`docs/ANDROID_BUILD.md`. Read `docs/EVIDENCE_STATUS.md` for reference claims.
Inspect the current game screenshot and native scene before proposing a style.
If a memory document is missing, give the coordinator a short proposed entry.

## Work from the player's wish

1. Translate words into an observable change. “ดูไม่น่าเล่น” can mean an empty
   battlefield, anonymous combatants, text-heavy cards, or absent hit feedback.
   Compare the actual frame against the recorded player vision to identify which.
2. Reuse agreed preferences. Make routine, reversible choices yourself. If a new
   preference changes the whole direction, ask at most 1–3 short Thai questions,
   using actual visual choices where helpful. Never require an art style name,
   a wireframe, a palette, a prompt, or a programming explanation from the user.
3. Show a small visual proposal and state the concrete improvement in plain Thai,
   such as “ตัวละครจะยืนอยู่ในฉาก ส่วนการ์ดมีภาพและบอกผลสั้น ๆ”. Mark a default
   as an assumption until accepted; do not record it as a user-approved preference.
   Continue authorized reversible implementation with labeled assumptions; use an
   asynchronous preference question when available, without adding an approval gate.
4. Implement one coherent playable view: original character/enemy silhouettes,
   an illustrated stage with clear foreground/background, a small set of legible
   illustrated cards, a readable HUD and visible feedback for play/hit/status.
   A decorative backdrop behind unchanged text boxes does not satisfy this scope.

## Use references honestly

- Inspect pictures, not only filenames. The current private CZN inventory has
  111 recovered PNGs and 7 SCSP/atlas sets; the sets are not assembled characters.
  The 1,004 card-art filenames and 235 portrait-set names are manifest metadata,
  not received illustrations. Recheck the inventory if more bytes arrive.
- Explain the useful design observation: composition, character scale, contrast,
  hierarchy or feedback. Do not claim to know the original developer's intention.
- Use those observations to design original product imagery. Keep extracted CZN
  art private and out of Git/APK under the repository's source-handling rules.
- An atlas is an image of parts, a rig needs assembly, an animation needs playback,
  and a model must be opened and inspected before reporting its type or usability.

## Produce and integrate art

Use the available image-generation tool for newly generated pictures and edits.
Inspect supplied local images with `view_image` before editing and follow the
tool's reference-image and transparency instructions. Never replace image editing
with Python processing unless the user explicitly requests that approach.

For a game-art task, save original reusable assets under `mobile/assets/`, import
them into Godot, connect them to the actual Control scene, and render the scene.
For a request limited to illustrations, deliver the finished pictures directly;
do not imply that they are integrated into the game. A generated full-screen
concept is a concept, even if it resembles a screenshot or contains fake buttons.
Do not claim APK integration, animation, touch support or readiness from it.

## Acceptance and delivery

- Inspect the actual native framebuffer at the target landscape sizes. Check
  card art crop, readable effects/cost, contrast, character scale and hit targets.
  Play a first turn and inspect action/impact/status feedback, not only a still.
- Run `mobile/tests/test_ui.gd` using a real Godot display renderer for screenshot
  evidence; headless output cannot prove image quality. Run affected checks and
  build/verify a new APK when native files change and the delivery scope is APK.
- Deliver before/after runtime images plus reusable original assets. Label every
  concept, reference picture, Linux native screenshot and Android capture correctly.
  Record `art blocked` or `art incomplete` when requested imagery is absent or
  placeholders remain; successful engine checks cannot make that status complete.
- Return proposed memory entries for accepted visual decisions, sources, checks
  and next work. Only the coordinator writes `docs/PLAYER_VISION.md`,
  `docs/design/DECISIONS.md` and `docs/design/CURRENT_TASK.md`; workers do not
  edit these shared files. Never promote a default assumption into user approval.
- Do not spawn agents just to simulate a team. Delegate only independent work
  with explicit file ownership and a visible deliverable.
