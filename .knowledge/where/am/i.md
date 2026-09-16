---
scope: project local
source: "David canonical KT policy index requirement, routed from project and installed orientations 2026-09-15"
review_when: Recheck when project purpose, runtime layout, service activation,
  current priority, or primary development workflow changes.
status: "unverified"
updated_at: "2026-09-15T09:02:38+10:00"
---

This is `/home/david/Projects/CointOS`, David's personal, local-only CointOS
orchestration repository. It turns local/Telegram requests into durable agent work,
coordinates local inference and survival controls, and stores its implementation,
configuration, tests, plans, specifications, decisions, and agent-facing knowledge.
Do not mix professional, partner, or customer information into it.

Source lives primarily in `ecosystem/` and `survival/`; launch adapters are in
`scripts/` and `services/`; policy/configuration is in `config/`; standard-library
tests are in `tests/`. Start current project work with `what/is/the/spec.md`,
`what/is/the/plan.md`, `what/is/the/state.md`, and `what/is/next.md`; detailed
orientation continues through `what/is/current/project_priority.md`,
`where/is/code/for/cointos.md`, and `what/is/architecture/of/cointos.md`.

Reusable project knowledge belongs in this semantic tree, not an `agent_notes/`
chronology. The reason and disposition are recorded in
[`why/are/agent_notes/deprecated.md`](../../why/are/agent_notes/deprecated.md); Git
retains removed historical notes.

Mutable runtime data is physically under `/home/david/.CointOS`, not this checkout.
There are intentionally no repo compatibility paths for `state/` or `logs/`.
Installed services now run from ~/.CointOS; proxy, Telegram/control, notifier, resource guard and background timers are online. Startup/basic work and control inference pass, while saturation and recovery remain unqualified. Establish live truth through `where/is/runtime_truth.md`; use
`how/to/test/cointos_changes.md` before claiming verification.

The canonical branches cover procedures in `how/` (for example `how/to/operate/cointos.md`), requirements and state in `what/` (`what/is/intended/agent_scheduling.md`), locations in `where/` (`where/is/runtime_truth.md`), and rationale in `why/` (`why/are/agent_notes/deprecated.md`). The `does/` and `is/` branches are currently empty and reserved for behavior and classification yes/no answers.

Agent policy is indexed by `global:how/to/behave.md`; project-specific requirements and operational policy are in this tree’s spec and intended-behavior leaves.
