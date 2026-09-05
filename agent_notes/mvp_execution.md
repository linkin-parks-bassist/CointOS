# CointOS MVP execution memory

Maintained by Astra (Codex `/root`) from 2026-09-05. This repository is David's
personal orchestration infrastructure. Keep professional and customer material out.

## S0 source boundary

David approved implementation and activation of the complete MVP suite on
2026-09-05. Merge and publication remain separately controlled. The implementation
topic is `docs/cointos-mvp-bringup`; the pre-snapshot parent is
`12b1c19b805c3814038661de3ffd039f7a033d23`.

The coherent source snapshot consists of two explicit commits:

1. `c7ba854152d6220b3f806b17c357aeb5708750f4` (root tree
   `937f449a72034e2c1ab19cfdbac366c47105714f`): the existing dirty runtime,
   resource-control infrastructure, configuration, roles, service descriptions
   and their focused tests;
2. `9f95ee0a7359bf9b0f16e480a9f36492cb733684` (root tree
   `4983eb1ac6ca6cf94786dc87f45f33fd215ad031`): the complete MVP
   plans/specification, decisions, maintained notes and status documentation.

The Git commit and root-tree identifiers are the authoritative path/digest manifest;
the ignored SDD ledger records assignments and review state. S0 used path-specific
staging and never staged ignored runtime or credential trees. The unrelated
`fix/snappy-initial-response` worktree at `/home/david/.worktrees/ecosystem-snappy`
remains untouched.

The live resource record was still latched in `emergency` during S0, with Coin's
4B model and an idle 27B model resident. The coordinator therefore deferred Q1's
optional local inference substep: running ordinary local work through the existing
bypass would violate Sole Survivor exclusivity before R1 supplies the new admission
owner. Q1 remains a Sol-medium TDD task; short Halo work begins only from an admitted
state and remains required for later concrete substeps.

David corrected the stale 64 GiB GTT boundary during R3. Astra observed
`/sys/class/drm/card1/device/mem_info_gtt_total=107374182400`, exactly 100 GiB.
R3 and the checked-in TTM/cgroup policy now expose that deliberate capacity; fresh
host admission still preserves the independent 32 GiB desktop/control reserve and
12 GiB load transient. Large local models and contexts should use the remaining
measured envelope rather than inherit arbitrary small caps.

Baseline evidence before the snapshot: `python3 -m unittest discover -s tests -v`
ran 324 tests with zero failures in 13.154 seconds; `git diff --check` returned zero.
This is offline repository evidence, not live service, Telegram, model-capacity or
OOM evidence.

## Execution invariants

- Coin availability and desktop/OOM reserve dominate worker throughput.
- Context capacity is a lease; durable task identity and destination-sized handoff
  survive model and window changes.
- Every worker and smoke owner is recorded. Smoke starts only after worker,
  process-group, backend request and inference-lease exit are observed.
- One canonical contact route, admission owner and activation route replace the
  rejected parallel semantics at their cutovers.
- Future agents update this note with compact accepted milestones and current
  boundaries; detailed task churn stays in the ignored SDD ledger.

## 2026-09-05 late-day commits, noted at David's request

Recorded by the local opencode agent (Qwen3.8-27B-GGUF):

- `32f1c69` test: supply bounded executor fixture contract (`tests/test_executor.py`)
- `a8d6b3c` test: align control turns with trusted task intake (`tests/test_control_turns.py`)
- `b0d4de7` docs: distinguish user-driven agent leases (topic HEAD; tree clean)
  - R8 operator leases now explicitly cover David's independently launched
    agent sessions, e.g. `lemonade opencode launch`, not only bare inference
    clients.
  - User-driven sessions remain outside CointOS-managed budgets, generations,
    dispatch ownership and handoff state; CointOS observes their resource
    ownership without taking over their task lifecycle. Coin-only preemption
    and survival termination rules are unchanged.
- David's direction (2026-09-05): where the plans name GPT-5.6 Sol worker
  spawning, that is not appropriate for a local agent; a local dispatcher uses
  local agents only. The index global constraints, the swarm worker-selection
  rules and decision 0007 now make worker kind follow the dispatcher: Sol rows
  apply only under a hosted coordinator, and owner/budget lines naming Sol are
  assigned to the largest qualified local model/context under local dispatch.
- David's direction (2026-09-05): the 2-5 minute / hard 300-second framing for
  local build workers was a misread — it was "small, simple tasks that wrap up
  quickly so others can slot in and the big model can routinely check the work",
  not a ticking clock. All externally imposed time limits on build-swarm
  subagents (hard 300s run limits, "2-5 minute" chunk framing, and the negative
  "no wall-time limit" statements) are removed from the index, swarm contract,
  resources, contact, messaging, autonomy, health and approval-release plans and
  the spec. "Small and simple" is the standing wording for local build chunks.
  Unaffected: the scheduler/executor budget machinery (R5 budgets, H3 repair
  dispatch budgets, spec budget fields) governs agents managed by the running
  system, and single-point step estimates in plan steps were left as-is.

## 2026-09-05: R4 repair item 2 — owner-attested spawn failures (`7c36d88`)

Recorded by the local opencode agent (Qwen3.8-27B-GGUF), acting as coordinator:

- Ada/GPT-6 R4 repair-packet item 2 is complete. The R1 prerequisite is gone:
  `workload_control._apply_observations` no longer forces a processless local
  lease back to `starting`, so a released lease can no longer be un-quiesced by
  a bare observation. Owner-attested `never_spawned` / `reaped_spawn`
  observations (strictly validated) give such leases a truthful terminal
  transition: `observed_stopped`, then `quiescent` once the release outcome is
  recorded; an attestation contradicting a registered process is
  `dead_unreconciled`; attested leases do not owe checkpoint evidence.
- `gated_child_launch` now attaches `launch_failure` to every raised error:
  `{"spawned": False}` when no process exists, or spawned facts plus the actual
  bounded `gated_child_cleanup` outcome when one did. `launch_runner_round`
  journals `runner_spawn_failure` (phase, error, spawned, cleanup_state),
  quarantines non-reaped cleanups as `reconciliation_required` with the lease
  and pid/start/pgid persisted, and for unregistered crashes attests
  `reaped_spawn` with the exact reaped identity instead of releasing into
  limbo.
- Contract and rationale: `docs/decisions/0008-owner-attested-spawn-failures.md`.
  10 new tests (6 R1, 4 executor) assert actual lease states and smoke
  refusal; full suite 426/426.
- Follow-ups: no self-healing path for `dead_unreconciled` leases (deliberate;
  operator concern); hosted independent review of `7c36d88` pending GPT quota;
  the live normal-close smoke still needs the real backend observer
  (Lemonade-side, sequence/request correlation).

R8 (operator session leases) complete.
Recorded by the local opencode agent (Qwen3.8-27B-GGUF), acting as coordinator:

- R8 is a separate owner: `ecosystem/operator_session.py` with its own
  `state/operator-sessions.json` (schema v1). Lifecycle: acquire (→ starting;
  idempotent for an identical request; refuses without the `user_driven` band)
  → register (pid + /proc-stat field-19 start ticks, → active; idempotent for
  the same identity on an active session; refused on any other state) →
  release (outcome; idempotent for the same one, raises on mismatch; raises
  "dead session requires reconciliation, not release" on dead_unreconciled) →
  observe (release_requested + dead → quiescent; active dead without release →
  dead_unreconciled) → reconcile (only exit, evidence required). There is no
  observed_stopped state in this lifecycle. Only *active* sessions are
  preemptable, and only Coin preempts, with evidence.
- Scheduling: new `user_driven` band (850) strictly between coin (900) and
  small_health (800); `effective_priority(..., operator_session=True)` resolves
  it; ceilings user_driven→coin−1, small_health→user_driven−1 (aging cap now
  849). The validator fails with explicit band errors, not the generic
  snapshot error. Snapshot docs are digested: tests that mutate values must
  rebuild the digest (see `_snapshot_for` in tests/test_inference_capacity.py).
- `run` CLI: acquire fresh lease, spawn with start_new_session, register the
  kernel identity, wait, release with the child outcome
  (run_finished/spawn_failed, returncode); the exit code propagates. Only a
  fresh starting session may spawn (pre-spawn freshness check — the old
  "preempted between acquire and spawn" window is gone because preemption
  targets active sessions only). scripts/cointos-opencode is the bash wrapper
  (set -euo pipefail; exec python3 -m ecosystem.operator_session).
- Pressure integration: unload_dynamic_models skips models leased by an active
  session (record {model, skipped: True, reason, owner_session});
  enter_pressure preempts the leased session only when no unprotected dynamic
  model remained to be unloaded (a skip record exists and no other unload
  failed), with evidence {kind: coin_reserve, required_bytes, incident_id};
  outcome {state: preempted, returncode: None}; audited as
  pressure_operator_preemptions, cleared with the other emergency fields.
- Import graph: resource_control → operator_session → (function-local)
  executor. operator_session must import executor inside run_command, because
  executor imports resource_control; a top-level import is a load-order-
  dependent cycle.
- David's trust check on the test suite (were failures removed?) resolved by
  git diff: fixture additions and new tests only, one line deleted (the old
  minimal scheduling_values); David approved.
- Follow-ups: a live wrapper smoke against a real model load is a manual
  operator procedure (no state/scheduling-policy.json is published on this
  machine and no code writes it); the Lemonade-side backend observer still
  gates the R4 live normal-close smoke.

A1 (task contracts and durable execution claims) complete.
Recorded by the local opencode agent (Qwen3.8-27B-GGUF), acting as coordinator:

- A1's core was already in the tree (d1834a5..0fbad7a):
  `ecosystem/task_contracts.py` (explicit budget + contract validation,
  `narrow_contract`, trusted intake), data-driven roles under `roles/`
  (janitor, gardener, documenter, innovator, speculator), `cli.enqueue_child`,
  and the 8 acceptance tests in `tests/test_mvp_task_contracts.py`. The
  remaining gap was the durable execution claim: the executor's
  `_runner_worker_request` requires `deadline_monotonic`, `owner_identity`,
  `agent_generation`, and `caller_handle` via `_required_job_field`, but no
  production code wrote them — real enqueued jobs would have failed at claim
  time (test fixtures all injected them manually).
- Fix (commit afcd496): `enqueue_task`/`enqueue_child` write
  `agent_generation=1` and `logical_run_state="active"` at creation.
  `executor._claim_execution` fills missing claim fields only-if-missing —
  record values are authoritative and replay reuses them (R6 continuations
  must not increment the generation on replay). Defaults: `owner_identity`
  `executor:<job id>`, `caller_handle` `executor:local`,
  `deadline_monotonic` = clock() + `remaining_budget["task_seconds"]`, with an
  explicit ValueError when the remaining budget is absent (no fallback). It is
  called at the two existing persistence points in `launch_runner_round`
  (the ready→runner_starting block and the worker-request branch before
  `r1_acquire_intent`). No new `runner_phase` value: the recovery safe-phase
  set replays only `generation_claimed`/`r1_acquire_intent`/`r1_acquired`, and
  any other value quarantines the job to `reconciliation_required`.
- Survivor canonical descriptor: `SURVIVOR_QUEUED_FIELDS` in
  `resource_control.py` and its expected values now include the claim fields;
  the field-set test was updated to match (the descriptor evolves with the job
  record, not the reverse).
- Cautionary tale: `tests/test_mvp_task_contracts.py` has a hand-maintained
  `load_tests` tuple of test functions. A test added to the file but not to
  the tuple is silently uncollected — discovery reports fewer tests with no
  error. `test_resource_control.py` auto-scans module globals and is
  unaffected. When adding tests to the hand-maintained files, verify the run
  count moved.
- R5 (mechanical budgets, stoppability, fairness) is next on the critical
  path and consumes these claim fields plus the budget validators.
  Incrementing `agent_generation` on a genuinely new attempt belongs to R5's
  retry/new-attempt path, not to the claim.

## 2026-09-06: R5 — mechanical budgets, stoppability, fairness (`6f119e7`)

Recorded by the local opencode agent (Qwen3.8-27B-GGUF), acting as coordinator:

- New `ecosystem/execution_budget.py`, the only module that knows budget
  arithmetic. `account_usage` is a pure accumulator (input unchanged) over
  A1's validated budget: `run_started`/`run_stopped` and
  `task_started`/`task_stopped` markers charge only the *observed* running
  intervals; `wait` events (`approval`, `queue`, `drain`, `pause`) are
  explicit zero-cost no-ops; `attempt`/`child`/`output`/`evidence` are
  counters/deltas. Markers are detected by `in`-presence, not truthiness —
  the plan's fixture uses `0.0`. Overlapping intervals, unstarted stops,
  and unknown kinds are ValueError. `budget_outcome` checks in fixed field
  order (task_seconds, run_seconds, attempts, output, evidence, children)
  and returns `checkpoint_required` with the exhausted field; an active
  started-marker interval is counted to `now`. A timer never proves
  completion. `record_budget_handoff` is the only path to
  `partial_handoff_ready` and requires a durable nonempty artifact bound to
  job id and agent generation. `stop_process_group` does SIGINT (wrapup)
  -> SIGTERM (grace) -> SIGKILL; `observe()` returns the process-group
  identity only while the pid matches launch identity, and `None` (gone OR
  reused) is never signalled — the pid-reuse check lives in the caller
  closure, so the module stays dependency-free.
- Executor: the fixed 1800s job timeout is gone (and `max_job_seconds`,
  `queue_age_points_per_minute`, `maximum_starvation_minutes` were removed
  from `config/model-policy.json` as orphans). `_run_preemptibly` accounts
  output-file growth and the running interval against
  `job["remaining_budget"]` (explicit ValueError if absent) each tick.
  On exhaustion it writes `<id>.handoff-request.md` if no handoff exists,
  stops through `stop_process_group` (wrapup 30s / grace 15s from
  `time.cfg [workload]`), and returns the checkpoint outcome + usage.
  `execute_next` persists `checkpoint_required` with
  `logical_run_state="terminal"` FIRST, then attests the on-disk handoff
  (`state/jobs/<id>.handoff.md`, nonempty) into
  `partial_handoff_ready` via `checkpoint_job_state`; there is no
  executor-fabricated degraded handoff — that would be timer-proven
  completion. Audit event: `task.budget_checkpoint`.
- Scope ruling (supersedes the A1 note's forward pointer above): R5 does
  NOT increment `agent_generation`. The plan puts "a genuinely new attempt
  increments agent generation" in R6 (context continuity). Budget
  exhaustion leaves the job terminal at its current generation;
  re-attempt happens through a new task/enqueue, which is a control
  decision, not executor behavior.
- Scheduler: the static role map, raw age-minutes points, and the
  starvation term are deleted. `priority(job, scheduling, now)` calls
  `inference_capacity.effective_priority` with the accepted snapshot
  DOCUMENT (digest re-validated on every use) — role may be None
  (defaults to the role_priorities default), jobs without
  `execution_profile` land in the default band (ceiling 699, so unknown
  work can never cross into large_health). Score =
  priority*100000 + resident bonus − dispatch_count*10000. Within-band
  fairness is entirely the band-bounded aging (1 point/60s), which gives
  oldest-first rotation without starvation.
- Operator dependency (live): `executor.execute_next` admission and
  `cli.prepare_next` now require a published
  `state/scheduling-policy.json` (same document the R8 wrapper smoke
  needs). It is not published on the live root — until an operator runs
  the snapshot procedure, the live scheduler fails explicitly (audit
  `scheduler.admission_deferred`, admission deferred). No code writes that
  file.
- Cautionary tale: a dead process that has not been reaped is a zombie —
  `/proc/<pid>` still exists, so an `observe()` closure that only checks
  `/proc` reports "alive" and `stop_process_group` waits out the full
  wrapup+grace (the preemption tests stalled 90s). The executor closure
  calls `process.poll()` first, which both reaps the zombie and rules out
  pid reuse before any identity read.
- Tests: `tests/test_execution_budget.py` (8, function-based +
  load_tests), `tests/test_scheduler.py` rewritten function-based (4
  fairness tests; the old class-based test was migration debt, converted
  in place), `tests/test_preemption.py` updated for the new
  `_run_preemptibly(process, command, job, output_path, before_stop,
  scheduling)` signature (jobs now need `remaining_budget`,
  `created_at`, `authority_profile`), and `test_intake.py` setUp publishes
  the scheduling snapshot from the repo's `config/scheduling.json` (the
  values source of truth; digest computed canonically). Full suite
  468/468 (457 baseline + 11).
- Next on the critical path: R6 (context continuity; consumes R5's
  checkpoint states and A1's generation semantics).
