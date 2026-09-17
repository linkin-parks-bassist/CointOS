---
status: "unverified"
created_at: "2026-09-17T16:33:46+10:00"
scope: "local"
source: "telegram-999135397 actions.inspect_status and inspect_task_progress; installed job records; Kaelen disposition leaf 2026-09-17"
---

Cointelprofessional repeatedly mentioned Kaelen even after the only current Kaelen queue blocker (`task-5a6a1b3735254ea5`) and its cleanup admin task were cancelled/terminal. Live tool evidence from `telegram-999135397` shows `inspect_status` correctly reported only one active queued steward (`task-443dd9580a4a4756`, agent `steward-68648f`), but its `lifecycle_facts.latest_by_role` simultaneously included historical terminal records: completed auditor Kaelen and the cancelled admin task whose text says “Delete the queued job for agent Kaelen.” The model conflated those historical examples with active work and volunteered the obsolete Kaelen narrative again.

The source of contamination is the status payload, not an active Kaelen job. Current/status-facing facts must distinguish active work from terminal history structurally. Do not include arbitrary latest terminal role records in the default live-status context; expose history only through an explicitly requested historical query or a clearly separate bounded historical field that cannot be mistaken for current work. Existing cancelled/terminal job records remain valid durable history and need not be deleted.
