# ADR 0002: Model choice is recorded job state

- Status: accepted
- Date: 2026-09-03

## Decision

No executor chooses a fixed default model for newly created jobs. The control
plane considers the current downloaded model catalog, capability labels, size,
context, residency/busy state, available memory, system load, role, task, and any
explicit model request. Every job records the selected model, the selecting
agent's rationale, and the factual resource snapshot used at enqueue time.

Executors obey the recorded selection. A deterministic role-aware fallback exists
only for control-plane failure and identifies itself as such. Future schedulers
may defer a valid choice when resources change materially before dispatch, but
must record that reconsideration rather than silently substitute a model.

## Consequences

Model routing is inspectable and can improve independently of execution. A model's
free-text rationale is advisory; the attached resource snapshot is authoritative.
Manual choices are accepted only for locally available models.
