---
status: green
revised_at: "2026-09-26T06:59:25+10:00"
---

Source `ecosystem.verification.enqueue(target)` calls `cli.enqueue_task` with deterministic idempotency key `verification:<target ID>` and `verifies_target_id=<target ID>`. `cli.enqueue_task` validates the target ID, writes `verifies` in the same locked atomic job record as the new verifier, and requires the same target on an idempotent replay. A crash after job publication therefore leaves the watchdog's `reconcile_verifications` with a linked verifier instead of an orphan; a repeated enqueue resolves to the same job ID. This closes the former gap where a random-ID verifier was published first and linked by a second write. A bounded temporary-root check created one linked job across two enqueue calls. This is installed without restarting services; source and installed CLI/verification copies match, standard discovery passes 837 tests, and live qualification remains pending. The generic enqueue wakeup remains a later side effect, so an interruption before that signal can still delay dispatch until its fallback scan; this change does not claim to solve every enqueue wake race.
