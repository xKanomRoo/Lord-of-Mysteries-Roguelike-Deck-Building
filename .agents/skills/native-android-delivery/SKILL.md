---
name: native-android-delivery
description: Build and deliver the native Android game with visible original art, compatible saves, verified APKs, and optional low-cost private cloud backups.
---
# Native Android delivery

Use when implementing a player-facing feature, integrating production art, fixing the
Godot game, delivering an APK, or preparing optional account and save services.
Announce this skill's use once. Read root `AGENTS.md` before assigning or editing files.
Read `docs/START_NEXT_ANDROID.md`, `docs/ANDROID_BUILD.md`, `docs/ONLINE_BACKEND.md`
and `docs/VALIDATION.md`; for visual work also read `docs/REFERENCE_VISUAL_RESULTS.md`.

## Turn a wish into a playable change

As a worker, propose questions to the coordinator instead of asking the user directly.
The coordinator merges questions across all roles, at most 1–3 per work cycle.
When working standalone, also fulfill the coordinator's communication/memory role.

Translate the user's everyday description into what a player will see, do and feel.
Use conversation preferences as persistent requirements; do not require technical terms.
State a small concrete scope and success criteria, then finish the authorized work.
If taste is unclear, offer an optional visual choice while continuing reversible work;
do not make a concept approval a prerequisite for implementing an authorized feature.
Explain progress in Thai through player outcomes, with actual images when relevant.
Keep the game playable and able to save locally without a network or account.

## Assign owners before parallel work

- UI owner: `mobile/scripts/main.gd`, `mobile/main.tscn`, related presentation assets.
- Rules owner: `mobile/scripts/game_engine.gd`, `mobile/data/content.json`, engine tests.
- Cloud owner: `mobile/scripts/cloud_save.gd`, `backend/supabase/`, protocol tests.
- Delivery owner: `tools/build_android.sh`, APK verification and build documentation.
- Art owner: explicitly assigned paths under `mobile/assets/`; agrees IDs with UI owner.
- Reviewer: checks the integrated game and receipts; reports findings before changing
  another owner's files. Assign `mobile/tests/test_ui.gd` to a single owner too.

Agents share one checkout. Give each agent exact paths, expected outputs and interfaces;
never let two agents edit the same file concurrently. Integrate dependencies sequentially.
Source changes belong in this repository; do not create extra repos just for each role.
Only the coordinator writes shared PLAYER_VISION/DECISIONS/CURRENT_TASK memory;
workers return proposed entries and current evidence instead of editing those files.

## Implement the native game

Use the pinned Godot 4.6.3 project in `mobile/`; the legacy browser is in `src/`.
Keep deterministic rules separate from Control rendering. Add supported engine effects
before putting new fields in content; descriptions must match the resulting actions.
Preserve content IDs and save validation. Inspect `SAVE_VERSION` and `ENGINE_ID` before
changing state. If a schema changes, implement a tested migration or an explicit safe
incompatibility result; never silently discard existing player progress.
Coordinate game envelopes with cloud validation; database protocol and game save
versions are distinct. Preserve local saves during failed or conflicting cloud writes.

## Integrate visible art

For a visual request, deliver authored character/environment/card art visible in the
running game and a newly exported APK. A concept sheet or additional definitions alone
does not complete that request. Use generated original art or permitted supplied art.
Keep recovered reference art in ignored research storage unless product use is authorized.
Reference composition and layout with evidence; do not claim an atlas is an animated rig.
Give assets stable paths and IDs; integrate them with the UI owner, import with Godot,
and check texture bounds, aspect ratios, readability, memory and offline availability.
Retain clear costs, enemy intent and touch targets while reducing text overload.
Capture the actual game after integration; label concepts and runtime captures accurately.

## Verify and export

Run `bash tools/setup_android.sh` when the pinned toolchain is missing, then use its
`.local/android-tools/toolchain-paths.json` for the exact Godot executable and XDG paths.
Use task-specific writable XDG directories under `.local/`, never repurpose `HOME`.
Import first (`--headless --path mobile --editor --import --quit`); run relevant native
scripts with `--headless --path mobile --script res://tests/test_engine.gd` and
`res://tests/test_cloud_save.gd`. Check logs as well as exit codes for Godot errors.
For UI changes run `res://tests/test_ui.gd` with a real supported display/render backend,
inspect screenshots and exercise touch, layouts and the changed player flow.
Build using `bash tools/build_android.sh`; it imports, exports and verifies the APK.
Inspect current verification/hash receipts, packaged art and content; historical counts
in `docs/VALIDATION.md` are not evidence for new work. Run meaningful affected checks.
Preserve package identity and the existing private debug keystore for installable updates;
never overwrite it or recommend uninstalling before protecting the player's save.
Keep SDKs, keystores, sessions, private novels, reference art and APKs outside Git.
## Optional account services and delivery

Use the existing Supabase Auth/backup adapter and schema for low-cost player-owned saves.
Preserve owner RLS, restricted grants, revision conflicts and explicit restore. Test the
affected protocol and local SQL fixtures; a live project needs separate integration checks.
Use only public project URL and publishable/anon key in client configuration. Never ask
the user to paste passwords, session tokens, signing keys or service-role keys in chat.
Account creation, Auth settings and project configuration stay with the user's account;
explain remaining dashboard steps briefly and link `docs/START_NEXT_ANDROID.md`.
Check current provider quotas rather than promising free capacity. Backups do not provide
server-authoritative currencies, anti-cheat or realtime multiplayer.
Deliver the new APK link, actual runtime image, player changes and current validation.
Distinguish native Linux playtests, APK signature checks and Android device launch tests;
name any untested hardware or live service plainly. Do not claim this workflow itself
changed or tested the game. Update evidence only after the corresponding work is run.
