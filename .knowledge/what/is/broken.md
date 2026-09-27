---
status: green
revised_at: "2026-09-27T17:03:42+10:00"
---

These CointOS defects remain current. what/is/the/plan.md schedules their fixes.

**Oversized worker runs.** In the abandoned JSON-parser exercise, scalar parsing and serialization each ran for about 100 minutes against the 8–15-minute useful-work sizing target. The cause remains undiagnosed: oversized assignments, lane sharing or looping. Their logs and sessions were erased with that exercise; watch the next exercise rather than claiming a diagnosis.

**Cold resume after model reload.** A manager retained its session and worktree, but its checkpoint diverged from the resumed conversation and it reread 27,589 tokens. The differing prefix remains unknown. Persisting a session does not establish warm resume.

**Malformed OpenCode continuation.** A partial continuation during a live restart produced a model-template HTTP 400. The cause remains unknown; daemon adoption alone does not establish that the in-flight reply survived.

**Steward maintenance is not admitted.** maintenance_project is CointOS, while the only configured autonomous project is todo-cli. Adding autonomous source maintenance or choosing another target requires David's direction.

The installation/layout and project-queue defects are resolved. Services run from the installed runtime; Todo is independent; queues are daemon-owned and integrations signal settlement. Unit and paused runtime checks pass, but the revised prompts and handoffs still require an autonomous live acceptance run after David authorizes resumption.
