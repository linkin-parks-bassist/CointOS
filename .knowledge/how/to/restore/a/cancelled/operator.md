---
status: green
revised_at: "2026-10-29T07:30:06+11:00"
---

Cancellation settles an ad-hoc Operator as failed/cancelled. cointos resume releases admission holds on waiting tasks; it cannot reopen a cancelled task.

After an explicit user instruction to restore the work, create a new Operator continuation through run-agent with the same intended outcome, scoped to the next finite deliverable. Inspect retained artifacts and current owners so the continuation reuses existing work. Task numbering provides a fresh identity; preserve the cancelled task as evidence. Give the scoped continuation the controls needed to publish its handoff through normal APIs.

Coin completion tracking is separate. Restore or retain the user/chat-bound follow-up for the new task through coin_followups.retain. The registry is privatejson-locked and validated; inspect it again to verify the new task is tracked. Preserve other live follow-ups. Inspect task-state wakes and retained requests for exact cancelled-task references when cleaning or restoring tracking.

Evidence: lifecycle.resume_task accepts only waiting tasks; tasks.request_operator creates numbered ad-hoc tasks; coin_followups.retain keys user/task identity and observes successful settlement. The restored continuation uses a new task identity rather than changing live ledger JSON.
