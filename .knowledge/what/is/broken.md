---
status: green
revised_at: "2026-09-27T16:41:31+10:00"
---

These CointOS defects are current. `what/is/the/plan.md` schedules their fixes.

**Oversized worker runs.** In the abandoned JSON-parser exercise, the `json-parser-parse-scalars` and `json-parser-serialize` workers each ran for about 100 minutes, against the 8–15-minute sizing target in `what/is/the/shape/of/cointos/work.md`. Both shared the single work lane. The cause is undiagnosed: oversized items, lane sharing or looping. The runs' logs and sessions were erased with the exercise, so the next exercise must be watched for it.

**Agents see a misleading filesystem layout.** It diverges from David's intended layout, set out in the plan, in three ways:
- `~/.CointOS` still holds the dead pre-rebuild "Agent Ecosystem" install, 64 MB installed 2026-09-26, along with 20 inactive `agent-*` user units in `~/.config/systemd/user` that point into it.
- Its `.knowledge` is granted in kt as "allowed everywhere". So every agent's `kt_roots` lists it, readable and writable, and its `where/am/i` calls itself "the installed copy of … CointOS".
- The live runtime runs from the dev checkout, and every agent worktree lives under `~/Projects/CointOS/state/worktrees/<project>/<task>`. So an agent working on a project sees CointOS paths throughout.

The Todo CLI is also being built inside the sandbox instead of its own repo.

**Cold resume after a model reload.** After the lane-shape reload, the JSON manager kept its OpenCode session and worktree. Its checkpoints were discarded anyway, as diverged from the resumed conversation, and it re-read its whole 27,589-token prompt (`restored=0`). No role prompt had changed. The token prefix that differs is unknown. So a persisted session does not guarantee a warm resume.

**Malformed OpenCode continuation.** In one live restart, a malformed partial continuation caused a template HTTP 400 from the model server. The cause is unknown. Until it is found, a daemon adopting a run does not show that the in-flight reply survived.

**Steward maintenance is never admitted.** `config/cointos.json` sets `maintenance_project` to `CointOS`, but only the sandbox is in `projects`. So routine steward runs never start.
