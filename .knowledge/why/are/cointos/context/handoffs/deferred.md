---
status: "unverified"
created_at: "2026-09-14T22:32:29+10:00"
scope: "local"
source: "David explicit conversation direction 2026-09-14; inspected and changed executor, prompts, policy, capacity derivation; focused test results"
---

CointOS context handoffs and forced fresh-session continuation are deferred by David's explicit direction on 2026-09-14. David reports OpenCode compaction is satisfactory and long-running agents are working well. OpenCode should own context compaction within retained sessions pending future review; handoff development is not a current priority.

The active executor no longer preempts at 75% context use, requests semantic context handoffs, builds fresh-context rollover prompts, archives logs for rollover or detaches OpenCode sessions to reconstruct work from handoffs. Scheduler/resource preemption still resumes the retained OpenCode session. Task budgets remain enforced, but budget stops preserve session identity and do not generate or attest semantic handoff files. Session identity is persisted before runner cleanup/reconciliation. Old handoff-marked jobs with a retained session resume it; detached legacy contexts are queued for explicit recovery review.

`ecosystem/continuation.py` and budget-handoff helpers remain documented deferred experiments, with tests, but are disconnected from active executor calls. The worker 75% policy was removed; legacy capacity-record rollover fields remain compatibility metadata and no longer reject a prompt merely for crossing the legacy rollover threshold. Legacy handoff token reservation fields remain in admission schemas/policy; their removal is a separate schema cleanup, not a functioning handoff mechanism. Base/worker/lead prompts now request progress/results evidence instead of mandatory handoffs.

This deferral is distinct from preserving native inference state for coarse-grained scheduling. David's OS context-switch analogy did not imply microsecond swapping or repeated disk paging during generation. Streaming/scanning live swap is an exploratory future idea, not today's required implementation.

Validation: focused preemption, cumulative usage, capacity and new compaction integration tests passed before the final session-persistence adjustment; final surrounding/full-suite results are recorded in the repository state leaf. No installed client, running backend allocation, service or live job was changed.
