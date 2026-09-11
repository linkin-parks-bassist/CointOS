---
verified_at: '2026-09-11T15:03:56+10:00'
verified_by: codex /root
scope: project local
source: 'agent_notes/0024-opencode-live-capacity-contract.md; docs/superpowers/plans/2026-09-10-opencode-live-capacity-contract.md; git status --short --branch'
verification: Confirmed the approved design and plan exist, their implementation is unstarted, and dirty-worktree reconciliation is the immediate prerequisite.
review_when: Recheck after any capacity-plan implementation commit or priority change from David.
---

After the documentation/quarantine reconciliation commit, begin Task 1 of
`docs/superpowers/plans/2026-09-10-opencode-live-capacity-contract.md`: implement
the pure effective-capacity record and focused tests. Do not first edit the user
OpenCode JSON, replace the `opencode` symlink, activate a wrapper, restart services,
or change live model allocation. Those remain later gated actions.
