---
status: green
revised_at: "2026-09-26T06:59:27+10:00"
---

It no longer does in the installed source. `ecosystem.outbox.render` now says ordinary terminal `completed` work “completed” without asserting an independent check. It uses “passed an independent check” only when the target job also has a nonempty `verification_job` and an object `verification` verdict with `accepted: true`, the fields written by `verification.finalize` after an explicit verifier run. A stale `verification_summary` alone no longer appears on an ordinary completion. Rejected verification still reports that the independent check did not accept the work and may include its summary. The prior bug inferred independent verification from `state: completed` alone even though ordinary jobs complete directly without a verifier. Existing focused outbox/notifier checks and a bounded stale-summary/accepted-verdict render check pass. This correction is installed without restarting services; source and installed outbox copies match, standard discovery passes 837 tests, and live notification qualification remains pending.
