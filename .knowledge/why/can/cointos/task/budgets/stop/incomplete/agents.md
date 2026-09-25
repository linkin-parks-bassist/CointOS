---
status: green
revised_at: "2026-09-25T18:00:59+10:00"
---

Ordinary CointOS agent tasks do not have arbitrary run-time, task-time, attempt, output-byte, or evidence ceilings. Task contracts represent an absent ceiling as `None`; verification, scheduled-review, sole-survivor, and authenticated-contact constructors use that form. `deadline_monotonic: None` is carried through worker acquisition, and the executor does not compare elapsed time for unlimited work.

Root `contact_requested` contracts are now normalized at `validate_task_contract`: `run_seconds`, `task_seconds`, `maximum_attempts`, `maximum_output_bytes`, and `maximum_evidence_items` become `None` even if a custom enqueue supplied finite values. `maximum_children` is preserved because it bounds delegated authority rather than the lifetime of the requested work. This closes the generic-intake hole that allowed a hand-built user contract to contradict the ordinary-work policy.

Finite budgets remain supported for deliberately bounded probes and specialized authority profiles such as `bounded_maintenance`, and for properly narrowed child authority. If such a finite budget is exhausted and an exact OpenCode session exists, the executor performs verified runner cleanup and queues the same job as `ready`/`continuing`; without an exact session it records `checkpoint_required` because continuation identity is unproven.

The installed 2026-09-25 repair preserved the exact session of the active AMD-on-Wheels ingestion worker, normalized its live execution ceilings to `None`, retained `maximum_children: 0`, and resumed it with `deadline_monotonic: None`. Source and installed `task_contracts.py` match and compile. Twenty-seven existing task-contract, intake, and control-turn tests pass, and direct checks prove contact-root normalization while specialized finite budgets remain unchanged.
