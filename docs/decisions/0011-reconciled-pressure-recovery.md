# 0011: Pressure recovery reconciles leases against /proc before reopening

Status: accepted, 2026-09-06. Chosen architecture: the resource controller
closes the R1 work gate before it interrupts anything, reconciles every
interrupted job's durable worker/sequence lease against a direct /proc
process-group observation, and keeps admission closed — through a restricted,
observed, gate-driven path — until every lease is proven quiescent.

## Context

Before R7, `enter_pressure` stopped the model clients and unloaded dynamic
models but never touched the R1 leases the interrupted jobs had held: the
gate stayed `draining` forever with live-looking leases, and nothing drove
the only drain-to-open path (a passed smoke window). Release depended on
resource health alone. Reopen had no notion of lifecycle pause or active
operator sessions, so a healthy machine could resume dispatch while the
operator was mid-intervention. Pressure and actual OOM were distinguished
only by code path, and the emergency side had no gate or lease duties at all.

## Decision

`ecosystem/resource_control.py` composes the existing contracts — R1
drain/gate, R3/R4 sequence leases, R5 checkpoint, R6 continuation state —
without weakening any of them. `WORK_GATE_OWNER` is
`{"owner_identity": "resource-control", "covered_paths": []}`.

1. Gate first. `enter_pressure` calls `workload_control.begin_drain` before
   `checkpoint_running_jobs`; a gate conflict halts with `pressure_error`
   and the checkpoint never runs (`test_pressure_closes_gate_before_checkpoint`).
   Order: close gate → checkpoint → stop clients → reconcile → unload →
   preempt leased models only when nothing unprotected remained (R8 law kept).

2. Direct observation. `_process_group_observed_gone(pgid)` scans `/proc/*/stat`
   (pgid = field 2 after the last `)`, matching the executor's identity law)
   and answers True only when no live process belongs to the group, False
   when a member is alive, None when the observation is unavailable. The
   survival side never infers death from its own records; an unknown pgid
   (possible reuse) is conservatively treated as alive.

3. Reconciliation. `_reconcile_interrupted_leases` walks each interrupted
   job's durable leases. The sequence lease is settled first with an honest
   root release request (`kind: reconciled_absent`,
   `observer_identity: resource-control`), which can only ever yield
   `release_requested` — attesting a sequence end is the R4 backend
   observer's authority alone, so root recovery never depends on R4 and
   never fabricates a `released`. The worker lease is settled only when the
   job record corroborates the lease's registered process identity
   (exact pid + start-tick match); it is released `preempted` and observed
   with matching identity, dead group, no backend activity, and checkpoint
   observed. A lease is `quiescent` only when its process group was
   observed gone and the terminal outcome was recorded; every other case
   (alive group, uncorroborated identity, unreadable record, refused
   release) is quarantined with a reason. The per-job record is persisted
   on the job record (`lease_reconciliation`) and re-runs are idempotent —
   a quiescent lease is never re-observed.

4. Gated reopen. A sustained-healthy release (or `request_recovery`)
   requires, in addition to the healthy window: no independently observed
   restrictions — the `state/PAUSED` lifecycle marker and any active
   operator session (`lifecycle:paused`, `operator:<id>`); and a work-gate
   reopen driven through the only drain-to-open path (a passed smoke window
   entered and ended by the resource controller, which the R1 gate admits
   only when every lease is quiescent). Restrictions are never cleared by
   reopen — the controller defers with reasons (`pressure_reopen_deferred`),
   re-checks on every healthy tick, and starts nothing. `request_recovery`
   keeps its hard gates (emergency mode, sole-survivor identity, observed
   health — `RuntimeError`) but defers with `ok: False` when restrictions
   or an unresolved gate exist. A gate held by another owner, a corrupt
   gate record, or an active smoke window all keep dispatch closed.

5. OOM stays distinct. A boot-bound `oom_kills` increment latches
   emergency immediately and exclusively: the emergency also closes the R1
   gate (a conflict is recorded but survival proceeds), checkpoints, stops
   clients, and reconciles the interrupted leases before the model phases,
   preserving Coin's physical front slot for the emergency model and
   admitting exactly the recorded Sole Survivor. Pre-OOM pressure never
   fabricates OOM (`test_pressure_is_not_oom`); survivor assertions cannot
   reopen; only deterministic host/GTT/swap/PSI, Coin contact, process, and
   lease observations pass the recovery gates.

## Consequences

- Admission stays closed while any lease cannot be proven resolved — there
  is no fallback, and a live process demonstrably keeps the gate closed
  (`test_recovery_reconciles_leases_before_reopen` drives a real
  subprocess to that end).
- R6 continuation fields (`opencode_session`, `context_state`,
  `context_generation`) survive a full pressure interrupt/release cycle
  with `resume_available` intact.
- `resource_control` now imports `workload_control`, `inference_capacity`,
  and `operator_session` at top level — verified cycle-safe because
  `survival/records.py` and `models.py` are stdlib-only — and still does
  not import `executor`, keeping the survival side independent of the
  dispatch side.
- The live root's missing `state/scheduling-policy.json` surfaces as an
  honest sequence-lease quarantine, not a silent release.
