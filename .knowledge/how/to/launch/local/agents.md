---
verified_at: '2026-09-11T18:43:14+10:00'
verified_by: codex /root
scope: project local
source: 'git show 8edeadd^:AGENTS.md; scripts/opencode_observable.py; scripts/worker_monitors.py; local-opencode-capacity-canonical-test JSONL 2026-09-11'
verification: Reconciled this project refinement with the incident-corrected global
  launch procedure and current manually managed Qwen slot.
review_when: Recheck when the observable launcher, viewer pool, scheduler, or concurrency practice changes.
---

This project-local leaf refines
`~/.knowledge/how/to/launch/local/agents.md`. For now, manually manage the single
local Qwen worker slot and launch through `scripts/opencode_observable.py`; do not
make the unfinished CointOS admission path a prerequisite for authorized local work.
The worker must remain locally attachable with retained JSONL evidence. In an
active driver session, use the canonical tracked viewer pool and publish the exact
session/attach command. Closing or losing a viewer must not stop or restart its
worker. Keep listeners loopback-only and ephemeral.

The global launch and briefing leaves own the remaining procedure.
