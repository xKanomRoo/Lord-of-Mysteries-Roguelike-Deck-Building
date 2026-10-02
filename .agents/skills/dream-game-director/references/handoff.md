# Specialist handoff

The coordinator fills this with real task facts before spawning or sending work.
Do not send the player a form to fill in. Link bounded references; exclude credentials,
full novels and unrelated research dumps. Resolve repository paths to the active checkout.

```text
Role and outcome: [specialty; one player-visible result]
Player request: [short quote/paraphrase, latest correction included]
Confirmed preferences: [relevant PLAYER_VISION/DECISIONS items]
Current state: [what exists, artifact type, source/commit if material]
Assumptions: [reversible proposed choices; never label them user approval]
Read: [AGENTS + relevant SKILL.md + small source/evidence files]
Own: [exact files/directories; other agents must not write these]
Do not edit: [shared memory and other owners' files]
Input/interface: [asset IDs, schema, output size/style, dependencies]
Deliver: [actual picture / code / played combination / review / receipt]
Questions: [propose only to coordinator; no independent user questionnaire]
Verify: [behavior or visual criteria; meaningful checks; label unrun checks]
Return: [paths, current outcome, findings, blocker, proposed memory updates]
```

Shared memory is written only by the coordinator. An independent review does not
take ownership of another worker's files. Reassign ownership explicitly before fixes.
If requirements change, notify affected owners with the new outcome and keep completed
compatible work. Do not reset or delete unrelated user work.
