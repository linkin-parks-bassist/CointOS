# Cointelprofessional Survival Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close every load-bearing residual from the rejected Plan 2 scoped review while preserving the single production survival route.

**Architecture:** Extend the existing reducer and production adapter composition with crash-safe per-job transition records, an unprivileged checkpoint consumer, independent activity/pause restoration, absolute-deadline systemd operations, installed incident routing, timed progress, and irreversible delivery-uncertainty facts. No parallel controller or compatibility route is introduced.

**Tech Stack:** Python 3 standard library, plain JSON records, atomic filesystem publication, Unix peer credentials, systemd system/user services, cgroups, and `unittest`.

**Spec:** `docs/superpowers/specs/2026-09-05-cointelprofessional-survival-closure-design.md`

## Global Constraints

- Preserve the permanent gateway and guardian outside every destructible unit set.
- Root never executes model-generated code; checkpoint work runs as David.
- Preserve strict command, schema, UID, unit, action, and path allowlists.
- Persist intent before every external mutation and verify postconditions before reduction.
- Repeated failures remain durably blocked without guardian death or report storms.
- Pause state, service activity, job handoff state, and message delivery state are distinct facts.
- Delivery uncertainty never authorizes automatic Telegram replay.
- All duration policy comes from the accepted central timing projection.
- Use functions and explicit plain data only; no classes, inheritance, or hidden mutable object state.
- This plan does not install, enable, stop, or restart live services.
- Pre-existing unrelated dirty work remains unstaged and unmodified.

---

### Task 1: Indefinitely idempotent retry and crash-safe job transitions

**Files:**
- Modify: `survival/lifecycle.py`
- Modify: `survival/system_control.py`
- Modify: `tests/test_survival_lifecycle.py`
- Modify: `tests/test_system_control.py`
- Modify: `tests/test_survival_guardian.py`

**Interfaces:**
- Consumes: existing lifecycle request records and immutable effect-attempt records
- Produces: one exact per-job transition record under `lifecycle-transitions/<request_id>/<job_id>.json`
- Preserves: `advance_request(path: Path, adapters: dict, policy: dict) -> dict`

- [ ] **Step 1: Add focused failing retry tests**

Invoke one permanently failing adapter at least three times, calling `recover_request()` between attempts. Assert every attempt returns `phase == "blocked"`, recovery never raises, only one deterministic blocked notification exists inside its deduplication interval, and a later lifecycle request remains serialized.

```python
results = []
for _attempt in range(3):
    results.append(system_control.advance_request(path, adapters, policy))
    system_control.recover_request(path)
assert [result["phase"] for result in results] == ["blocked"] * 3
assert len(blocked_reports(store, request_id)) == 1
```

- [ ] **Step 2: Run the focused tests and reproduce the failure**

Run: `python3 -m unittest tests.test_system_control tests.test_survival_guardian -v`

Expected before repair: the second identical failure raises while searching for a pending notify effect.

- [ ] **Step 3: Make blocked reporting optional and retries total**

Replace the unconditional `next(...)` in `advance_request()` with a pure selector returning `None` when the deterministic report effect was already applied. The original failed effect remains the retry subject. A missing report effect is a valid deduplicated state. Ensure idle guardian recovery returns stable blocked results indefinitely.

```python
def _pending_blocked_report(state):
    return next((effect for effect in reversed(state["pending_effects"])
                 if effect["kind"] == "notify"), None)
```

- [ ] **Step 4: Add per-job crash-cut tests**

For two active jobs, inject death before transition intent, after intent, after job mutation, and after transition completion. Reload only from disk and assert both jobs occur in the derived interrupted set exactly once with valid handoff identities preserved.

- [ ] **Step 5: Implement per-job interruption transitions**

Publish an exact `intended` record before changing a job. After observing `interrupted` with the right request identity, publish `completed`. Recovery completes or safely retries from job postconditions. Derive `runtime["interrupted_jobs"]` from transition records; the post-loop aggregate is no longer authoritative.

- [ ] **Step 6: Verify and commit**

Run: `python3 -m unittest tests.test_survival_lifecycle tests.test_system_control tests.test_survival_guardian -v`

Expected: PASS, including repeated permanent failure and every per-job crash cut.

```bash
git add survival/lifecycle.py survival/system_control.py tests/test_survival_lifecycle.py tests/test_system_control.py tests/test_survival_guardian.py
git commit -m "Make survival recovery indefinitely idempotent"
```

### Task 2: Real unprivileged checkpoint consumer

**Files:**
- Create: `survival/checkpoint.py`
- Create: `scripts/cointelprofessional-checkpoint`
- Create: `services/system/cointelprofessional-checkpoint.service`
- Create: `tests/test_survival_checkpoint.py`
- Modify: `survival/system_control.py`
- Modify: `config/survival-lifecycle.json`
- Modify: `scripts/install-survival-plane`
- Modify: `docs/operations.md`
- Modify: `tests/test_system_control.py`
- Modify: `tests/integration/test_survival_processes.py`

**Interfaces:**
- Produces: `validate_checkpoint_request(value: dict) -> dict`
- Produces: `process_checkpoint_request(path: Path, agent_state: Path, result_root: Path, now: Callable) -> int`
- Produces exact result states: `checkpointed`, `already_terminal`, `unsupported`, `deadline_expired`
- Consumes the existing job/session handoff representation, never arbitrary command text

- [ ] **Step 1: Write strict schema and outcome tests**

Cover exact-field rejection, replay, already-terminal jobs, a valid durable session/handoff, unsupported jobs, deadline expiry, and malformed/missing job records. Assert one atomic result per requested job and no privileged operation.

- [ ] **Step 2: Prove the module is absent**

Run: `python3 -m unittest tests.test_survival_checkpoint -v`

Expected before implementation: FAIL because `survival.checkpoint` does not exist.

- [ ] **Step 3: Implement the checkpoint fingertip**

Requests contain `schema_version`, `request_id`, canonical `job_ids`, `requested_at`, and a finite absolute `deadline_monotonic`. Validate job IDs as existing record stems. Reuse existing session/handoff facts and publish each terminal result atomically. Replay returns the exact existing result.

- [ ] **Step 4: Make guardian checkpoint success observational**

Update `_checkpoint_runtime()` to publish the request, poll results under one absolute deadline, validate every claimed handoff, and send all non-checkpointed jobs through Task 1's interruption transition. Elapsed sleep alone is never success.

- [ ] **Step 5: Package without privilege expansion**

Install the wrapper and service through the content-addressed release and sole `current` cutover. Run as David outside ordinary admission activation with only checkpoint/job-state paths. Do not grant root or guardian-socket authority.

- [ ] **Step 6: Add process and installer evidence**

Start the consumer against a temporary store and mixed request. Extend first-install interruption, unit verification, tamper detection, and survival-unit exclusion tests for the new unit.

- [ ] **Step 7: Verify and commit**

Run: `python3 -m unittest tests.test_survival_checkpoint tests.test_system_control tests.integration.test_survival_processes -v`

Expected: PASS.

```bash
git add survival/checkpoint.py scripts/cointelprofessional-checkpoint services/system/cointelprofessional-checkpoint.service survival/system_control.py config/survival-lifecycle.json scripts/install-survival-plane docs/operations.md tests/test_survival_checkpoint.py tests/test_system_control.py tests/integration/test_survival_processes.py
git commit -m "Add verified lifecycle checkpoint consumer"
```

### Task 3: Exact activity restoration, semantic deadlines, and backend truth

**Files:**
- Modify: `survival/lifecycle.py`
- Modify: `survival/system_control.py`
- Modify: `tests/test_survival_lifecycle.py`
- Modify: `tests/test_system_control.py`

**Interfaces:**
- Produces: `restore_runtime_activity(config, effect, user_adapter, wait, reopen_admission: bool) -> dict`
- Produces one absolute deadline per semantic unit action
- Requires expected model, `loaded`, accepted status, `backend_alive`, and bounded canary success

- [ ] **Step 1: Add paused/activity matrix tests**

Cross paused/unpaused with active/inactive ordinary and activation units. Exact prior activity is restored in every case; only pause/admission and interrupted-job resumption differ.

- [ ] **Step 2: Unify finish/resume restoration**

Move service restoration into one adapter used for both prior pause values. Pass `reopen_admission=False` for previously paused and `True` otherwise. Restore only units captured active; keep intentionally inactive units down.

- [ ] **Step 3: Add one-clock deadline tests**

Use a fake monotonic clock and manager consuming time across action and probes. Assert total duration uses one deadline, calls receive remaining time, unfinished manager work gets the fixed cancellation/escalation sequence, and failure is recorded only after safe postconditions.

- [ ] **Step 4: Enforce manager-job truth**

Issue fixed `systemctl --no-block` actions and observe manager/cgroup postconditions under one deadline. On expiry perform only allowlisted stage escalation and verify safe terminal state. Never treat death of the local `systemctl` client as cancellation.

- [ ] **Step 5: Require the complete backend contract**

Reject false/missing/malformed `backend_alive`, wrong model identity, unloaded or invalid status, boolean-as-number, NaN, infinity, or failed inference canary. Every negative keeps admission closed.

- [ ] **Step 6: Verify and commit**

Run: `python3 -m unittest tests.test_survival_lifecycle tests.test_system_control -v`

Expected: PASS for the restoration matrix, total deadlines, safe timeout, and backend-negative cases.

```bash
git add survival/lifecycle.py survival/system_control.py tests/test_survival_lifecycle.py tests/test_system_control.py
git commit -m "Restore lifecycle activity and enforce health truth"
```

### Task 4: Pre-command reporting, progress cadence, and delivery uncertainty

**Files:**
- Modify: `survival/telegram_api.py`
- Modify: `survival/gateway.py`
- Modify: `survival/system_control.py`
- Modify: `survival/guardian.py`
- Modify: `scripts/install-survival-plane`
- Modify: `services/system/cointelprofessional-gateway.service`
- Modify: `services/system/cointelprofessional-guardian.service`
- Modify: `docs/operations.md`
- Modify: `tests/test_survival_gateway.py`
- Modify: `tests/test_system_control.py`
- Modify: `tests/test_survival_guardian.py`
- Modify: `tests/integration/test_survival_processes.py`

**Interfaces:**
- Produces validated installed `incident_destination.json` with exact authorized Telegram identity
- Produces an immutable per-message attempt-observed fact
- Preserves: `ensure_critical_delivery(root, message_id, initial_state) -> tuple[Path, dict]`
- Consumes: `lifecycle.progress_update_period_seconds`

- [ ] **Step 1: Add pre-command destination tests**

With no lifecycle records, seed a valid installed destination and assert data-health and rejected-policy incidents create root critical messages. Reject missing, extra, mismatched, non-integer, or spool-supplied destination fields.

- [ ] **Step 2: Install one destination owner**

Derive the destination at installation from the administrator-approved identity used by gateway authorization. Publish a root-owned validated record outside immutable releases. Remove lifecycle history as destination policy.

- [ ] **Step 3: Add progress cadence tests**

With fake time, assert opening report, silence before the period, one report per period, immediate phase/blocker-change report, restart deduplication, and live adoption of a changed accepted period.

- [ ] **Step 4: Implement durable progress observations**

Persist last phase, blocker fingerprint, and report times under root lifecycle state. Evaluate during bounded guardian idle recovery. Report failure affects delivery health only; it neither blocks nor advances lifecycle.

- [ ] **Step 5: Reproduce delivery replay**

Deliver a critical source, corrupt/remove its gateway delivery record, restart draining, and assert Telegram is not called again. Separately cover corruption before any attempt.

- [ ] **Step 6: Persist irreversible attempt observation**

Before `sending`, atomically create an immutable attempt-observed record. If an attempt exists, any absent, malformed, quarantined, or interrupted delivery record reconstructs as `delivery_unknown`, never `ready`. That state is terminal for automatic egress and emits one local incident.

- [ ] **Step 7: Extend packaging/process evidence**

Verify destination modes, direction-specific paths, progress across guardian restart, delivery ambiguity across gateway restart, and sandbox access only to exact new paths. Keep real cross-UID kernel credential execution for Plan 5.

- [ ] **Step 8: Run final verification**

```bash
python3 -m unittest -q tests.test_survival_records tests.test_survival_protocol tests.test_survival_lifecycle tests.test_survival_checkpoint tests.test_survival_gateway tests.test_survival_guardian tests.test_system_control tests.test_time_policy tests.integration.test_survival_processes
python3 -m unittest discover -s tests -v
python3 -m py_compile survival/*.py ecosystem/time_policy.py
bash -n scripts/install-survival-plane scripts/cointelprofessional-gateway scripts/cointelprofessional-guardian scripts/cointelprofessional-checkpoint
systemd-analyze verify services/system/cointelprofessional-survival.slice services/system/cointelprofessional-gateway.service services/system/cointelprofessional-guardian.socket services/system/cointelprofessional-guardian.service services/system/cointelprofessional-checkpoint.service
git diff --check
```

Expected: all commands exit 0; all tests pass; verification emits no errors.

- [ ] **Step 9: Commit**

```bash
git add survival/telegram_api.py survival/gateway.py survival/system_control.py survival/guardian.py scripts/install-survival-plane services/system/cointelprofessional-gateway.service services/system/cointelprofessional-guardian.service docs/operations.md tests/test_survival_gateway.py tests/test_system_control.py tests/test_survival_guardian.py tests/integration/test_survival_processes.py
git commit -m "Complete survival reporting and delivery truth"
```

## Installed acceptance handoff

After this plan's task reviews and whole-branch review are clean, Plan 5 must run real operations under the installed gateway and David identities. It must prove every allowed direction and prohibited rename/injection/mutation, then exercise live systemd, checkpoint, Telegram progress/completion, cgroup turnover, and rollback without sacrificing the current gateway. Any failure blocks enablement.

