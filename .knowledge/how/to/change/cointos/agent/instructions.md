---
status: green
revised_at: "2026-10-29T07:20:00+11:00"
---

Write affirmative instructions stating the intended input, action, result and handoff. Use concrete descriptions of the desired workflow for local models.

Edit roles/<role>.md for role behavior and roles/_base.md for shared guidance. cointos/prompts.py reads these files when assembling a new session's system prefixes; assignment facts belong in prompts.py rather than role guidance. Existing conversations retain their supplied instructions.

Test authors and integrators pair promised properties with assertions rejecting plausible wrong results; Operators reuse checked evidence and identify the authorized repair owner before retrying. The validation and recovery owners explain these instructions and their limits.

Source files are distinct from installed ~/.CointOS/roles. Follow how/to/install/cointos.md for deployment. Instruction-only refresh can preserve the daemon and live sessions. When the source checkout contains unrelated pending changes, do not deploy them accidentally: a scoped refresh must preserve surrounding installed text, serialize with installation/repair ownership and verify each changed block. It does not update existing sessions or prove improved agent performance. Evidence: prompts.shared_launch_prefix, scripts/install and the source/installed role files.
