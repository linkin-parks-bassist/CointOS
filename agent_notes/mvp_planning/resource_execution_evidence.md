# Resource admission and execution evidence for the complete MVP

Recorded by Cairn (`/root/resource_plan_evidence`) on 2026-09-05 for Astra's plan.
Provenance is David's personal orchestration repository. No model, service,
credential, Telegram, Git, or runtime action was taken.

## Binding outcomes

- Coin/GUI responsiveness and OOM prevention outrank worker throughput. Any new
  kernel OOM count latches emergency; ordinary work stays excluded
  (`agent_notes/0010-cointos-survival-invariants.md:7-41`).
- Context exhaustion is independently never terminal: before the active window fills,
  durable state and a sufficient handoff seed a fresh context without task/control-
  plane discontinuity; only Coin availability depends on no-OOM (same source, 16-41).
- Accepted policy pins the 4B control model, permits at most one unpinned work model,
  treats caller choices as hints, and leaves deterministic safety checks authoritative
  (`docs/decisions/0006-survival-first-model-and-context-scheduling.md:18-42`).
- New plan input: Sol 5.6 medium for non-local workers; local workers use the largest
  safely feasible model/context, remain short and stoppable, and all workers finish
  before smoke tests. This is not existing behavior.

## Existing evidence and disposition

### Host facts, pressure and emergency — keep and compose (R7)

- `resource_control.resource_snapshot() -> dict` samples boot/OOM identity, host
  available memory, swap, memory PSI and GTT (`resource_control.py:152-165`).
  `_threshold_state(snapshot: dict) -> str`, `confirmed_threshold(...) -> str`, and
  `tick() -> dict` interpret these into normal/pressure/emergency (`:1172-1274`).
- `job_admitted_in_current_mode(job: dict) -> bool` denies all pressure work and
  admits only the named survivor in emergency (`:205-211`).
- `checkpoint_running_jobs(incident_id: str, reason: str = ...) -> list[str]` records
  interruption/session state and syncs it (`:403-426`). `enter_pressure(...)` stops
  the executor and unloads dynamic models (`:617-640`); OOM increment immediately
  enters emergency (`:1228-1241`). Keep these survival mechanisms and tests.

### Capability, active allocation and envelope — separate and rebuild (R2/R3)

- `models.snapshot() -> dict` mixes registry capability (`context`), live allocation
  (`loaded_context`, `busy`, `pinned`), host/GTT facts, and policy (`models.py:46-83`).
  Preserve collection but explicitly separate host model capability, active context
  per slot, and the current physical resource envelope.
- `admission(model_id: str, inventory: dict) -> tuple[bool, str]` checks model/recipe,
  32 GiB desktop/control reserve, 12 GiB load transient, model size, host availability
  and 64 GiB GTT (`:89-116`). A resident model returns true before present-pressure
  validation (`:95-96`), so loaded-model shortcuts can bypass current safety.
- `context_options(model, inventory) -> list[int]` bounds an unloaded model by
  advertised context and estimated KV bytes against host/normal-GTT limits
  (`:133-159`; `config/resource-policy.json:27-40`). For a loaded model it returns
  only `min(capability, loaded_context)` without resource revalidation (`:137-140`).
- Emergency code has the missing distinction: `emergency_model_allocation(...)`
  returns per-request context, parallel slots, and total backend context, while
  `_model_satisfies_emergency_allocation(...)` divides observed backend context by
  parallelism (`resource_control.py:277-347`). Generalize this invariant.
- `route(job, inventory, infer=chat) -> dict` constrains the model router to
  prevalidated identity/role/residency/context choices (`models.py:181-319`). Keep the
  router only as preference policy; there is no certified capability ranking.
- `realize(decision, inventory) -> dict` rechecks only `admission()` before `/v1/load`
  and passes `ctx_size=context`, `--parallel 1` (`:322-361`). It neither resnapshots nor
  revalidates selected context: a time-of-check/time-of-use seam.
- Delete unused `fallback(...)` and legacy `admitted_or_substitute(...)` after its
  isolated test is replaced (`:364-390`). Explicit deferral must be the sole route
  when evidence is insufficient.

### Execution budgets and context — keep evidence, rebuild ownership (R5/R6)

- `config/model-policy.json:20-35` provides one serialized worker, 1800-second dispatch,
  300-second slice, 15-second stop grace, and 75% rollover. It has no per-task attempt,
  cumulative wall/token/output/evidence-item budget or encoded stopping condition;
  `dispatch_count` is observed but unbounded.
- `_run_preemptibly(command, prompt, output, env, job, path, output_path) -> dict`
  creates a process group, records PID/count, enforces dispatch time, preempts, and
  polls context each second (`executor.py:171-211`). Keep stoppability and polling.
- `opencode_context_usage(output_path: Path, session: str | None = None) -> dict | None`
  parses durable `step_finish` JSONL tokens (`:78-102`). Keep this fingertip and
  normalize every backend's usage to one record.
- At 75%, `execute_next(...)` resumes the old session only to request a semantic
  handoff (`:301-351`), then archives its log and creates a fresh continuation
  (`:370-413`). Missing semantic handoff becomes visibly degraded (`:372-386`).
  Preserve behavior; extract explicit, idempotent state transitions from the monolith.
- `_job_opencode_config(job) -> Path` overwrites static provider context per job
  (`:105-114`). Catalogue limits (`config/executor-opencode.json:8-17`) are capability
  hints, not allocation/safety proof. OpenCode and direct HTTP must share enforcement.
- `scheduler.choose(...)` sees already routed jobs; an executor file lock serializes
  OpenCode (`scheduler.py:28-51`; `executor.py:214-240`). Keep priority/age inputs,
  but schedule only leased work.
### Global smoke exclusion — missing (R1)

No inspected function atomically closes admission and proves local, deep-control,
and non-local workers quiescent. `_active_records()` is only a non-locking snapshot
(`resource_control.py:357-384`); the executor lock does not exclude enqueue or other
worker families. `run_until_idle()` covers only the serialized executor
(`executor.py:438-442`). Smoke can therefore race a newly admitted worker.
## R1..R7 independently testable task boundaries

### R1 — Global work gate, worker leases and smoke fence

```python
workload_control.acquire_worker(root, request, clock) -> dict
workload_control.begin_drain(root, owner, clock) -> dict
workload_control.enter_smoke(root, owner, clock, observed_workers) -> dict
workload_control.release_worker(root, lease_id, outcome, clock) -> dict
workload_control.admission_reasons(resource_state, lifecycle_state, work_state) -> list[str]
```
`request` carries `workload_class=front|repair|work|monitor`, `model_id`,
`context_tokens`, `max_output_tokens`, `deadline_monotonic`, `owner_identity`, and
`request_id`. Drain atomically closes acquisition before observation; enqueue remains
durable but cannot dispatch. Smoke succeeds only after every owned local/Sol lease has
a verified terminal/quiescent observation; timeout names blockers; release is
idempotent. Tests: `test_drain_closes_acquisition_before_snapshot`,
`test_enqueue_during_fence_cannot_dispatch`, `test_smoke_rejects_active_worker`,
`test_drain_waits_for_local_and_sol_leases`, `test_failed_smoke_releases_gate`.
### R2 — Validated model and context candidate selection

```python
models.safe_routes(inventory, policy, request) -> list[dict]
models.choose_route(routes, request) -> dict
models.validate_route(route, fresh_inventory, policy, request) -> dict
```
Routes record advertised maximum context, backend total context, parallel slots,
active context per slot, model/KV/output/tool/prompt/handoff reserves and load transient.
Admit any backend-supported quantum within the fresh envelope; fixed candidate lists
are not architecture. `choose_route` applies declared preferences but invents no ranking. Final
validation is fresh and immediately precedes load/dispatch. Tests:
`test_context_is_divided_across_slots`, `test_loaded_shortcut_rechecks_pressure`,
`test_output_reserve_is_admitted`, `test_fresh_validation_closes_realize_race`,
`test_no_safe_route_defers_without_fallback`.
### R3 — Physical front/work inference reservation

Define `resource_envelope(host, resident_models, active_leases, policy) -> dict`.
It reserves Coin/GUI/front capacity before replaceable work, accounts for simultaneous
load transient plus active KV/output allocations, and limits work-model residency.
Tests: `test_front_reserve_precedes_work`, `test_work_cannot_consume_reserved_front_slot`,
`test_parallel_context_uses_total_bytes`.
### R4 — Route every inference consumer through enforcement

```python
inference.request(request, root, clock) -> dict
inference.cancel(root, lease_id, clock) -> dict
```
Migrate router/chat/control, OpenCode configuration, direct HTTP and loaded-model reuse
through R1-R3. Adapter literals stay at the fingertip. No unmanaged path may reach
`/v1/chat/completions` or `/v1/load`. Tests: `test_direct_http_requires_lease`,
`test_opencode_context_and_output_match_lease`, `test_loaded_model_cannot_bypass_gate`.
### R5 — Enforced worker budgets, stoppability and fairness

Use `validate_execution_budget(raw) -> dict`, `account_execution_usage(...) -> dict`,
and `budget_outcome(...) -> dict`. Enforce dispatch/cumulative wall time, attempts,
observable tokens/output bytes, evidence/items, authority and stopping condition.
Exhaustion safely yields `partial_handoff_ready`, not success or context overflow.
Tests: `test_deadline_stops_process_group`, `test_attempt_limit_blocks_redispatch`,
`test_output_budget_is_mechanical`, `test_budget_preserves_partial_handoff`,
`test_short_jobs_rotate_without_starvation`.
### R6 — Proactive context continuation

Use `observe_context_usage(adapter_event, lease) -> dict`,
`context_transition(job, usage, fraction) -> dict`, and
`prepare_continuation(job, handoff, artifacts) -> dict`. Make
`running -> handoff_requested -> handoff_durable -> continuation_ready` explicit and
idempotent. Preserve task identity across model switches and smaller successor windows;
bound the old-context handoff to the destination lease's prompt budget. Tests:
`test_rollover_precedes_limit`, `test_handoff_fits_destination_prompt_budget`,
`test_task_identity_survives_model_and_window_change`, `test_restart_during_rollover_is_idempotent`.
### R7 — Compose pressure/OOM recovery with R1-R6

Pressure/emergency first closes R1 acquisition, checkpoints leased work, stops clients,
then unloads. Recovery reopens only after independently observed health and durable
lease reconciliation; Sole Survivor stays exclusive. Tests:
`test_pressure_closes_gate_before_checkpoint`, `test_oom_latches_survivor_exclusivity`,
`test_recovery_reconciles_leases_before_reopen`, `test_context_continuation_survives_pressure`.

## Architectural recommendation and uncertainty

Keep telemetry/inference fingertips, durable job/session artifacts, process-group stop,
pressure/emergency transitions and priority inputs. Rebuild one structured resource
envelope, transactional lease route, explicit budgets/rollover, and a semi-permeable
global fence. Delete duplicate fallbacks and scattered context interpretation after
cutover, leaving one coherent route. No live measurements were taken: KV/output
estimates, provider context semantics, Sol lease observability, and the complete worker
registry need bounded probes before fixed numerical policy is accepted.
