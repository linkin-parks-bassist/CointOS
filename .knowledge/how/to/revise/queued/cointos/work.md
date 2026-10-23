---
status: green
revised_at: "2026-10-19T13:00:58+11:00"
---

Queue changes use the daemon API: queue PROJECT NAME BRIEF, hold PROJECT:ITEM and revise PROJECT:ITEM BRIEF --reason WHY. Coin shares the API. The user, owning live manager or scoped control-enabled Operator may revise; Operators cannot clear another owner's hold.

Dependencies contain comma-separated local IDs or same-project PROJECT:ITEM aliases. Creation/revision canonicalize and deduplicate metadata and brief. Foreign/nested/malformed IDs refuse before mutation; prose belongs outside dependency names. Well-formed forward references remain allowed, but unknown prerequisites prevent readiness and trigger repair. Only accepted prerequisites satisfy edges. Stopped-ledger migration repairs coherent aliases without changing versions, sessions, receipts or holds; contradictory metadata refuses.

Revision replaces the complete brief. Omitted stage, effort and budget remain; supplied budget fields merge. Typed calls carry summary, dependencies and test-contract relies_on arrays. Agent implementation/integration revisions cannot discard accepted test dependencies, even through an empty array or stage change. Refusal names the packets before changing version, holds, runs or artifacts. Invalid accepted tests use independent correct-tests author/reviewer acceptance before dependencies change. Explicit user revisions can withdraw dependencies, but tested implementation/integration still requires an accepted test contract before submission. Removing the last edge does not waive the gate.

Changed revisions reset retries and conversation while preserving branches/files and other owners' holds. Only the revising task's own hold ends; user holds require release. The current receipt/review and recovery context clear for the new assignment. The last account remains in result and validation refusal evidence remains in submission_failure. Without a current receipt, default task/launch projections omit the old result and mark historical_fields; task --history retains it unchanged. A current checked receipt remains visible once. This separates prior completion claims from current authority without erasing evidence or archiving every receipt version. Native correction activation retained the 3,266-character previous implementation account and pinned e9dadfd refusal evidence while starting version 5.

Identical requests preserve version, failure, evidence, holds and budget. Accepted/superseded records cannot be revised. Foreign revisions cancel obsolete recovery controllers without withdrawing the item or erasing files; a controller's own correction remains completable. Admission/reconciliation enforce this version relation.

check_work previews drafts or checks reachable handoffs. Manager completion refuses dead authored/revised handoffs; ordinary waits remain valid. Holds stop related execution/recovery, except the controller retaining its own hold. Waiting integrations preserve files and explicit admission holds.

Replacement updates dependency edges/briefs, increments affected live versions and refreshes tasks/review conversations. Branches, uncommitted work, budgets and holds survive; accepted/replaced history stays fixed. Active validation/integration refuses graph changes before mutation. An unchanged revision cannot resurrect a replaced prerequisite. Recovery replace completes its checked handoff atomically; supersede remains nonterminal.

Evidence: queues/lifecycle/API/CLI/Coin and revision/Operator regressions. test_factory_frontier covers restarted views, unchanged explicit history and retained checked receipts. Installed acceptance and native correction owners retain rollout/results.
