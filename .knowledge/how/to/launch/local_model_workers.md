---
verified_at: '2026-09-11T15:47:00+10:00'
verified_by: codex /root
scope: project local
source: 'git show 8edeadd^:AGENTS.md; docs/operations/local-worker-view.md; agent_notes/0022-aster-packet-audit-and-timeout.md; local-opencode-capacity-canonical-test JSONL 2026-09-11'
verification: Checked launch policy and dispatch preference; observed a narrowly briefed worker broaden into a 100-result plan search and consume about 39k context without producing its one-file deliverable.
review_when: Recheck when the admission gate, observable launcher, viewer pool, or concurrency policy changes.
---

Launch local Qwen/OpenCode workers through the existing admission gate with
`scripts/opencode_observable.py`; do not use a naked background inference command.
The worker must remain locally attachable with retained JSONL evidence. In an
active driver session, use the canonical tracked viewer pool and publish the exact
session/attach command. Closing or losing a viewer must not stop or restart its
worker. Keep listeners loopback-only and ephemeral.

Dispatch only 1–3 genuinely independent, bounded jobs by default; eight slots are
capacity, not a utilization target. Bound jobs by a small deliverable, exact write
scope, necessary evidence, authority, and task-derived stopping conditions. Never
give local agents elapsed-time limits or arbitrary time budgets; reduce scope
instead. Read `docs/operations/local-worker-view.md`
before dispatch because driver/AFK window handling and the bounded reusable monitor
pool are operational policy, not general desktop-presence inference.

Orient with the smallest relevant `.knowledge` leaves and exact source excerpts.
Do not point a small worker at an entire large plan or ask it to rediscover field
names across the plan corpus. A forbidden broad glob is still possible under
`--auto`; monitor actual tool use and stop on demonstrated scope expansion. That
stopping condition is tied to authority/scope, not elapsed time.
