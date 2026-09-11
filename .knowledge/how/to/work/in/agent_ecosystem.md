---
verified_at: '2026-09-11T15:47:59+10:00'
verified_by: codex /root
scope: project local
source: 'git show 8edeadd^:AGENTS.md; docs/status.md; agent_notes/README.md; David policy clarifications 2026-09-11; ~/.knowledge/how/to/use/git/for/agent_work.md'
verification: Compared quarantined repository guidance with current status and agent-note policy; applied David's non-work Git-policy reversal and repository-copy invariant.
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

Never enable remote access, install credentials, program hardware, enable services,
or activate runtime changes without David's explicit approval. This is a personal,
non-work repository, so ordinary topic-branch pushes to its verified configured
personal remote are allowed under the global Git policy; merging and force-pushing
are not implied. Keep only `max(1, genuinely parallel open workstreams)` working
copies of this repository and retire extra worktrees when their workstream closes.
