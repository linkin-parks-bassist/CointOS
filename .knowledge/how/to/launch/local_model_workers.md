---
verified_at: '2026-09-11T15:03:56+10:00'
verified_by: codex /root
scope: project local
source: 'git show HEAD:AGENTS.md; docs/operations/local-worker-view.md; agent_notes/0022-aster-packet-audit-and-timeout.md'
verification: Checked the quarantined launch policy against the current operational guide and latest dispatch preference.
review_when: Recheck when the admission gate, observable launcher, viewer pool, or concurrency policy changes.
---

Launch local Qwen/OpenCode workers through the existing admission gate with
`scripts/opencode_observable.py`; do not use a naked background inference command.
The worker must remain locally attachable with retained JSONL evidence. In an
active driver session, use the canonical tracked viewer pool and publish the exact
session/attach command. Closing or losing a viewer must not stop or restart its
worker. Keep listeners loopback-only and ephemeral.

Dispatch only 1–3 genuinely independent, bounded jobs by default; eight slots are
capacity, not a utilization target. Read `docs/operations/local-worker-view.md`
before dispatch because driver/AFK window handling and the bounded reusable monitor
pool are operational policy, not general desktop-presence inference.
