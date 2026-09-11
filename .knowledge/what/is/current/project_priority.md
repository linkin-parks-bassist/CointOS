---
verified_at: '2026-09-11T15:46:24+10:00'
verified_by: codex /root
scope: project local
source: 'agent_notes/0024-opencode-live-capacity-contract.md; docs/plans/2026-09-10-opencode-live-capacity-contract.md; git status --short --branch'
verification: Confirmed the approved design and plan exist, the documentation worktree is clean, and implementation remains unstarted after stopped worker attempts produced no edits.
review_when: Recheck after any capacity-plan implementation commit or priority change from David.
---

Begin Task 1 of
`docs/plans/2026-09-10-opencode-live-capacity-contract.md`: implement
the pure effective-capacity record and focused tests. Do not first edit the user
OpenCode JSON, replace the `opencode` symlink, activate a wrapper, restart services,
or change live model allocation. Those remain later gated actions.
