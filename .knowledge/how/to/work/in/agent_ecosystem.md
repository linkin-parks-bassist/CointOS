---
verified_at: '2026-09-11T15:03:56+10:00'
verified_by: codex /root
scope: project local
source: 'git show HEAD:AGENTS.md; docs/status.md; agent_notes/README.md; David clarification 2026-09-11'
verification: Compared the quarantined repository instructions with the current status and agent-note policy.
review_when: Recheck when repository policy, activation authority, or project scope changes.
---

Treat this repository as personal, local-only orchestration infrastructure. Do not
mix in professional, partner, or customer information. Before changing behaviour,
read `docs/status.md`, the relevant agent notes, and applicable decisions. Preserve
append-only runtime JSONL; keep generated runtime state out of Git; record
consequential design changes in `docs/decisions/`.

Use small functions, plain data, explicit state transitions, and narrow module
interfaces. Object-oriented implementation is forbidden, including classes and
hidden mutable object state. Scope every run to one deliverable with bounded
evidence, authority, resources, and a stopping condition; record adjacent findings
as follow-ups.

Never enable remote access, install credentials, program hardware, push code,
enable services, or activate runtime changes without David's explicit approval.
