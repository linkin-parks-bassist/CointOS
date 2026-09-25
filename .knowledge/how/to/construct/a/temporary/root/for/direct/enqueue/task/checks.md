---
status: green
revised_at: "2026-09-17T13:40:53+10:00"
---

When a direct smoke check patches `ecosystem.cli.ROOT` to an empty temporary directory and then calls `cli.enqueue_task()` with a role, create `roles/_base.md` first. Role resolution reads that file beneath the patched root before persisting the job. The minimal setup used by the existing task-contract checks is: call `cli.initialize()`, create the `roles` directory, and write a nonempty `roles/_base.md`. Missing it raises `FileNotFoundError`; this is incomplete fixture setup, not an intake or scheduler failure.
