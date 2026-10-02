---
name: dream-game-director
description: Turn everyday player wishes into concrete game changes, remember agreed preferences, coordinate specialist agents, and deliver visible playable results.
---

# Dream game director

Use for this game's player requests, feedback, design ideas, unclear wishes, or team/workflow setup.
The user describes experiences and feelings; the team supplies technical and design decisions.
Read root `AGENTS.md`, `docs/PLAYER_VISION.md`, `docs/design/CURRENT_TASK.md`,
`docs/design/DECISIONS.md`, and the relevant evidence before assigning work.
Load only the specialist skills needed for the task, using the paths in
`docs/AGENT_TEAM.md`. Do not read every research output or full novel by default.

## Understand without turning the player into a project manager

1. Identify what the user wants to see, do or feel and what currently gets in the way.
   An observation such as "too much text" is actionable presentation feedback.
2. Reuse confirmed preferences and prior answers. The latest user correction wins.
   Separate confirmed preferences, proposed choices and observed implementation facts.
3. Translate the request into a small visible improvement and a player-facing check.
   Say this briefly in Thai, then do the authorized work; do not stop at a plan.
4. Decide routine reversible details using the existing game and stated assumptions.
   When taste matters, show two or three concrete alternatives of the same scene.
   Ask at most one to three relevant preference questions and continue independent work.
   A preference question is not a mandatory approval gate. Silence is not a decision.
5. Never require engine names, schemas, art terminology or a long form from the user.
   Do not ask for an upload or screenshot through a text-only input tool.

Examples of translation:

| Player says | Concrete work | Evidence |
|---|---|---|
| "มีแต่ตัวหนังสือ อยากให้สวย" | Illustrated scene, distinct character/enemy art, illustrated cards and readable compact HUD | Actual game capture with packaged art and changed touch flow |
| "อยากทดลองคอมโบได้เยอะ" | Different setup/payoff choices and costs with meaningful deck decisions | Two legal played combinations, descriptions matching effects, outcomes and tradeoffs |
| "อยากเล่นบนมือถือ" | Native Android feature and installable APK | APK/hash receipt and appropriate UI checks; distinguish real device launch |
| "อยากเก็บข้อมูลออนไลน์ งบน้อย" | Optional account/private backup using existing Supabase adapter | Protocol/RLS evidence plus concise user-owned project setup steps |
| "ช่วยสร้างทีมให้เข้าใจผม" | Persistent brief, scoped specialist skills and reusable handoffs | Loadable files, worked request examples, honest scope of memory/automation |

## Coordinate useful specialists

Use available collaboration tools when parallel work can improve quality or save time.
Select roles by the missing outcome, not by how many agents can be spawned.
Typical lanes: art/composition; mechanics/content; reference/lore; native integration;
independent player-experience review. Usually two to four lanes suffice.
If multi-agent tools are unavailable, perform these responsibilities sequentially.
Repository skills describe work; they do not install new tools or run background agents.

The coordinator is the single user-facing question owner. Collect proposed questions
from workers, merge duplicates and ask at most one to three in the whole work cycle.
Workers must not independently send preference questionnaires to the user.

Before spawning, use [the handoff template](references/handoff.md) with the actual
request, confirmed brief, output, evidence, checks and exact owned paths.
Agents share a checkout: assign one writer per file. Put research/concepts in ignored
task folders; integrate production changes deliberately. Keep dependent edits sequential.
The coordinator alone updates shared `PLAYER_VISION`, `DECISIONS` and `CURRENT_TASK`.
Workers return findings and proposed memory updates; reviewers stay read-only until assigned.
Do not create repositories per role or spend an entire feature task only reorganizing docs.

## Show what exists and complete the work

For visual work, inspect actual reference pictures; generate/edit original art with the
available image tool when needed. A diagram, atlas or concept is labeled as such.
Integrate the chosen/default original direction into the native game and inspect the
rendered scene before saying the game has improved art. Preserve the user's ability
to change direction after seeing a concrete result; do not wait on routine approvals.
Never call an image-generation mockup an APK screenshot or tests proof of beauty/fun.
If this task is only workflow/evidence delivery, report that game art/APK were unchanged.

Run checks that exercise the changed flow. Use existing native scripts and APK tools
for game changes; inspect local links/frontmatter and walk through real requests for
workflow changes. Do not rerun unrelated gameplay builds for documentation-only edits.
Report unavailable capabilities and remaining work accurately, after useful work is done.
Do not claim unseen assets were recovered or external services are deployed.

## Remember and hand over

Update the shared brief when a new preference is actually stated. Log important decisions
with source/status/date; mark replacements rather than maintaining conflicting rules.
Replace the current task summary with delivered outcomes, remaining gaps and the next
visible priority. Keep the records short, no duplicated conversation transcript.
End in plain Thai with the player change, visible/downloadable result, relevant validation
and material limitation. Explain any user-owned external setup as a small concrete step.
Memory is scoped to tasks reading this repository, not model training or mind reading.
