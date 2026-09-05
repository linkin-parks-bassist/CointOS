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

## 2026-09-06: R6 — context continuation state machine (`41308d3`)

Recorded by the local opencode agent (Qwen3.8-27B-GGUF), acting as coordinator:

- New `ecosystem/continuation.py`: pure functions, plain data, no I/O. The
  job record gains `context_state` (running / handoff_requested /
  handoff_durable / continuation_ready / paused_for_resources) and
  `context_generation`. `observe_context_usage(adapter_event, lease)`
  normalizes a backend usage event against the lease `context_tokens`
  (overflow >1.0 is a fact, not an error). `context_transition(job, usage,
  rollover_fraction)` moves running→handoff_requested at the fraction,
  which is validated 0 < f < 1 (rollover must precede the backend limit);
  a requested context stays requested at any overflow — overflow is never
  terminal. `attest_handoff` (non-empty summary + integer token_count),
  `handoff_budget` (the destination prompt/handoff/tool/output partition
  must fit its context; infeasible destinations are rejected, never
  trimmed), `prepare_continuation` (advances ONLY context_generation,
  binds the destination lease and budget, carries evidence by reference;
  null handoff stays visibly continuable via `handoff_missing`; over-budget
  handoff and double continuation fail explicitly), and `new_attempt` (the
  ONLY path that increments agent_generation; resets context_generation to
  1). Identity law by construction: transition fragments never carry
  agent_generation or context_generation. Contract:
  `docs/decisions/0010-context-continuation-state-machine.md`.
- Executor (clean break): `handoff_pending`, `fresh_context_after_handoff`
  and `context_rollover_usage` are deleted. Rollover detection runs in
  `_run_preemptibly` (via the module; the outcome contract `context_rollover`
  / `context_usage` / "total/limit" reason is unchanged — the preemption
  tests pass untouched) AND at clean run end: a run finishing past the
  threshold now rolls over instead of resuming a near-full session (a gap
  that previously existed only on the preemption path). On a
  handoff_requested run finishing, the executor reads the handoff artifact,
  attests it (or writes the degraded artifact), archives the old context
  log by reference, pops the session, and returns the job to the scheduler.
  The continuation launches at ROUTING time with the freshly admitted lease
  as `destination_lease` — a model change between handoff and relaunch is
  honoured, and the rollover prompt (with degraded note when the handoff was
  missing) is written there, not pre-prepared. A deferred job with a live
  session and a plain running context enters paused_for_resources;
  continuation-in-flight states are never clobbered by deferral. Launch
  consumes continuation_ready/paused_for_resources back to running and
  initializes context_generation to 1 on first launch. The handoff token
  count is estimated at the adapter boundary (~1 token / 3 chars,
  conservative); the gate is admission, not accounting.
- Scope ruling: `new_attempt` is module-level. Wiring a control-plane
  re-attempt of a R5 checkpointed job through it (e.g. amend/re-enqueue of
  checkpoint_required) is a separate follow-up, not R6.
- Tests: `tests/test_continuation.py` (10, function-based + load_tests;
  Step-1 identity test verbatim from the plan plus the plan's named tests
  and an explicit state-machine-advance test). Full suite 478/478
  (468 baseline + 10). `tests/test_executor.py` needed no changes — the
  existing harness exercises launch_runner_round with real children, and a
  fake execute_next rollover cycle would need the opencode binary; the live
  rollover smoke remains a manual operator procedure like R8's.
- Next on the critical path: A2 (needs A1+R5). R7 landed 2026-09-06, see
  below.

## 2026-09-06: R7 — reconciled pressure recovery (`6fe89eb`)

Recorded by the local opencode agent (Qwen3.8-27B-GGUF), acting as
coordinator:

- `ecosystem/resource_control.py` only (plus its test file). New
  `WORK_GATE_OWNER = {"owner_identity": "resource-control",
  "covered_paths": []}`. `enter_pressure` order is gate-first:
  `begin_drain` (a conflict halts with `pressure_error` and the checkpoint
  never runs — proven by the plan's verbatim ordering test) →
  `checkpoint_running_jobs` → `_stop_user_units` →
  `_reconcile_interrupted_leases` → `unload_dynamic_models` → R8 leased-model
  preemption (unchanged law: Coin takes leased capacity only when nothing
  unprotected remained).
- `_process_group_observed_gone(pgid)` reads `/proc/*/stat` directly (pgid =
  field 2 after the last `)`, same identity law as the executor). True only
  when no live process belongs to the group; False when a member is alive;
  None when unreadable. A pgid that could be reused is conservatively
  alive. The survival side never infers death from its own records.
- Reconciliation per interrupted job: the sequence lease is settled first
  with an honest root release request (`kind: reconciled_absent`,
  `observer_identity: resource-control`) that can only ever yield
  `release_requested` — attesting a sequence end is the R4 observer's
  authority alone, so root recovery never depends on R4 and never
  fabricates a release; a missing `state/scheduling-policy.json` or unknown
  lease quarantines honestly. The worker lease is settled only when the job
  record corroborates the exact registered pid/start_ticks, released
  `preempted` and observed with matching identity, dead group, no backend
  activity, checkpoint observed → `quiescent`. A quiescent lease is never
  re-observed (idempotent re-runs); anything else is quarantined with a
  reason and persisted on the job record as `lease_reconciliation`.
- Gated reopen: a sustained-healthy release (or `request_recovery`)
  requires the healthy window AND no independently observed restrictions —
  `state/PAUSED` (`lifecycle:paused`) and active operator sessions
  (`operator:<id>`) — AND a work-gate reopen driven through the only
  drain-to-open path (`enter_smoke`/`end_smoke` passed; any non-quiescent
  lease blocks admission per R1). Restrictions are never cleared by
  reopen: the controller defers with reasons, re-checks on every healthy
  tick, and starts nothing. A foreign gate owner, a corrupt gate record, or
  an active smoke window all keep dispatch closed. `request_recovery`
  keeps its hard `RuntimeError` gates (emergency mode, sole-survivor
  identity, observed health — a survivor claim cannot replace observed
  health) but defers with `ok: False` when restricted.
- Emergency side: `advance_emergency` "recorded" closes the gate
  best-effort (a conflict is recorded but survival proceeds), then
  checkpoint → client stop → reconcile before the model phases. OOM stays
  distinct: a boot-bound `oom_kills` increment latches emergency
  immediately and exclusively; pre-OOM pressure never fabricates OOM.
- Contract: `docs/decisions/0011-reconciled-pressure-recovery.md`.
- Tests: Step-1 ordering test verbatim plus the plan's seven named recovery
  tests. Fixtures are real: `acquire_worker` + `register_process` create
  live gate leases, `dead_process_identity` spawns and kills a real session
  leader for the quiescent path, and the deferred-reopen case drives a live
  `sleep` process so the quarantine demonstrably blocks reopen until the
  process is actually killed. 57/57 focused, 486/486 full suite (478
  baseline + 8).
- Module graph: `resource_control` now imports `workload_control`,
  `inference_capacity`, and `operator_session` at top level — verified
  cycle-safe (`survival/records.py` and `models.py` are stdlib-only) — and
  still does not import `executor`.

## 2026-09-06: A2 — bounded environmental evidence (`9a02901`)

Recorded by the local opencode agent (Qwen3.8-27B-GGUF), acting as coordinator:

- New `ecosystem/evidence.py` (no classes): `read_evidence(scope,
  relative_path, cursor, limits)` serves one bounded page. `limits` holds the
  CALLER's remaining `{maximum_bytes, maximum_items}`, counted across calls —
  the caller decrements by the UTF-8 length of `text` and by `items_read`.
  Result is exactly `{path (canonical), digest (whole-file sha256),
  observed_at, text, next_cursor, truncated, items_read}`.
- Containment is canonical and symlink-safe: `Path(workspace / relative_path)
  .resolve()` must land inside a contracted root (`read_paths` for reads,
  `write_paths` for writes). Empty root list, absolute paths, `..` escapes,
  and symlink escapes are all `ValueError`. Note `resolve()` is what makes
  symlinks honest — a link inside a root pointing outside resolves outside and
  is rejected.
- UTF-8: a page never splits a codepoint. `_page_boundary` walks back over
  continuation bytes (`& 0xC0 == 0x80`) and, if the cut lands mid-lead, drops
  the incomplete lead byte. A `cursor` that lands mid-sequence is an explicit
  `ValueError`, not a silent re-align.
- Event mode (`.jsonl` only): `_events` serves whole JSON lines up to
  `maximum_items`; a cut tail line is NOT served and the cursor stays at its
  start, so the next page re-reads it whole. A non-JSON non-empty line is
  `ValueError` (events are validated records, not blobs).
- Honest exhaustion (design ruling): when the budget is 0 but the file still
  has data, the page is empty but `truncated` is `True`. A false `False`
  here would let a caller mistake a budget stop for EOF — the exact
  misleading-fallback the repo forbids. Empty file or past-EOF stays
  `truncated=False`.
- `record_contribution(root, job, relative_path, text)` validates the DURABLE
  job at `state/jobs/<id>.json` (identity and contract are read from that
  record, not the caller's dict — a drifted caller contract is rejected),
  appends `## <stamp> job=<id> agent=<agent>\n\n<text>` under a contracted
  write root, audits `evidence.contribution`, and returns `{path, digest,
  observed_at}`.
- `executor.discovery_evidence(job)` is the discovery-run adapter: contract
  scope + remaining `maximum_evidence_items` + `evidence.DEFAULT_MAXIMUM_BYTES`
  (65536) page envelope; contractless or budgetless jobs fail explicitly.
  `execute_next` now passes `task_contract` into `render_context`, so prompts
  stop claiming "No executable contract was supplied" when the job has one.
- Design rulings: the byte envelope is `DEFAULT_MAXIMUM_BYTES` because A1's
  budget schema has no evidence-bytes field and A2's file list forbids
  touching `BUDGET_FIELDS` (editing it would break every contract producer).
  The item budget comes from the contract. `task_contracts._validate_scope`
  was promoted to public `validate_scope` so `evidence` reuses the canonical
  scope contract — a disclosed modification outside A2's declared file list,
  made for one harmonious scope representation.
- Tests: `tests/test_mvp_evidence.py` (15, function-based + the hand-maintained
  `load_tests` tuple — keep it in sync or tests are silently uncollected).
  Full suite 501/501 (486 baseline + 15).
- Boundary handed to A3: repo-side enforcement is contract scope + bounded
  API + the `_base.md` Bounded-inspection profile. Mechanically locking the
  opencode child's raw read/shell tools is opencode-configuration domain, NOT
  A2 scope — do not pretend the profile alone is a mechanical lockout.
- Next on the critical path: A3 (discovery jobs; needs A2+R7+H1).
