---
status: green
revised_at: "2026-09-17T10:26:18+10:00"
---

It no longer does. The CLI argument layer previously rejected `enqueue` without `--task-contract` even though `enqueue_task()` already constructs `default_task_contract()` for a missing contract. That duplicated gate contradicted the local MVP specification and made an ordinary authorized CLI task fail before durable intake. The CLI now loads a supplied contract when present and otherwise passes `None` to the existing defaulting path. The generated contract has ordinary authority, workspace-contained read/write scope, no capability or minimum-context prerequisite, and unlimited lifetime/output/attempt/evidence dimensions. Nine existing task-contract checks pass, and installed live enqueue without the option created task-f22b744c52a54d68.
