---
verified_at: '2026-09-11T15:46:24+10:00'
verified_by: codex /root
scope: project local
source: 'what/is/intended/live_capacity_contract.md; git status --short --branch; pre-99318d9 Git history'
verification: Confirmed the approved design and plan exist, the documentation worktree is clean, and implementation remains unstarted after stopped worker attempts produced no edits.
review_when: Recheck after any capacity-plan implementation commit or priority change from David.
---

Implement the pure effective-capacity record described in
`what/is/intended/live_capacity_contract.md` and focused tests. Do not first edit the user
OpenCode JSON, replace the `opencode` symlink, activate a wrapper, restart services,
or change live model allocation. Those remain later gated actions.
