# CointOS MVP Health and Repair Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development or superpowers:executing-plans task-by-task. Execute only an assigned task; checkboxes describe steps, not independent agents.

**Goal:** Detect real subsystem failures without inference, run bounded repair, and keep Coin informed.

**Architecture:** Deterministic user-level probes publish boot-bound observations. The installed guardian owns the incident reducer and dispatches a bounded user-level recovery runner outside the ordinary scheduler. All consumers use the same job/resource facts.

**Tech Stack:** Python standard library, JSON/JSONL, systemd, existing survival spools and local inference.

**Spec:** [MVP design](../specs/2026-09-05-cointos-mvp-design.md).

## Global constraints

- Read the spec and [swarm contract](2026-09-05-cointos-mvp-swarm.md); code is functions over plain data.
- Coin available, no OOM, seamless dynamic-context handovers are binding.
- No model is required for a deterministic health tick or guardian supervision.
- Existing runtime records are evidence, not test fixtures; tests use temporary roots.
- Repair reuses R2-R7 admission, execution and continuation; it cannot waive them.
- New changes require Coin approval before activation; installed containment actions do not.
- Every task ends with focused checks, exact diff review and one bounded independent review.
- New test files use the function collector in the swarm contract. Commands below use unittest discovery.

## H1 — Small deterministic health catalogue and probes

**Owner/budget:** Sol medium, 20 minutes. Local child: implement one specified check/test, <=300 seconds.
**Depends on:** R1, R7 and C3; does not block C5 early contact acceptance.
**Files:** create `config/subsystems.json`, `ecosystem/health_checks.py`, `scripts/health_check`,
`services/systemd/agent-health.service`, `tests/test_mvp_health_checks.py`; modify `config/time.cfg`
and its owning validators, plus `config/survival-lifecycle.json` for exact restore membership.
**Evidence:** old Plan 04 Tasks 1-2; `resource_control.resource_snapshot`; `control_turns` and gateway heartbeat.
**Interfaces:** `validate_definitions(raw: dict) -> dict`;
`evaluate_checks(definition: dict, observations: dict, clock: dict) -> dict`;
`probe_once(definitions: dict, readers: dict, clock: dict, root: Path) -> list[dict]`.
`clock` is `{boot_id, monotonic, utc}`. Each observation has `boot_id`,
`observed_monotonic`, `status: pass|fail|unknown`, `evidence_code`. Probe result adds
`subsystem_id`, `required_checks`, `checks`, `status`, and `deadline_monotonic`.

- [ ] Write an executable failure example and the wrong-boot/missing-check cases:

```python
from ecosystem.health_checks import evaluate_checks

def test_process_alive_does_not_hide_queue_failure():
    definition = {"subsystem_id": "work", "required_checks": ["process", "queue"],
                  "maximum_age_seconds": 30}
    observed = {
        "process": {"boot_id": "b", "observed_monotonic": 9,
                    "status": "pass", "evidence_code": "process_alive"},
        "queue": {"boot_id": "b", "observed_monotonic": 9,
                  "status": "fail", "evidence_code": "dead_running_owner"}}
    result = evaluate_checks(definition, observed,
                             {"boot_id": "b", "monotonic": 10, "utc": "2026-09-05T00:00:00Z"})
    assert result["status"] == "fail"
    assert result["checks"]["queue"]["evidence_code"] == "dead_running_owner"
```

- [ ] Run `python3 -m unittest discover -s tests -p 'test_mvp_health_checks.py' -v`; establish the missing-boundary failure.
- [ ] Implement checks for six actual owners: contact (gateway heartbeat plus ordinary turn progress),
  inference (loaded/backend-alive plus aged canary result), work (owner PID/start identity and queue
  progress), resources (fresh envelope and guard progress), autonomy (tick progress and pending
  claims), releases (no abandoned activation). Before a component is installed, record
  `unimplemented` and do not create a stale-health incident for it.

```python
required = set(definition["required_checks"])
failed = [name for name in required
          if name not in observations or observations[name]["status"] != "pass"
          or observations[name]["boot_id"] != clock["boot_id"]
          or not 0 <= clock["monotonic"] - observations[name]["observed_monotonic"]
                     < definition["maximum_age_seconds"]]
```

  Do not infer service health from active state alone. Each external read has a two-second
  deadline; run independent slow checks in reaped child processes so one timeout does not
  serialize a 12-second freeze. The service publishes current result atomically and events
  append-only. Five-second ticks use bounded concurrency; no inference in this service.
- [ ] Run the new module plus `test_time_policy.py` and `test_resource_control.py` through separate
  discovery invocations; verify unit syntax without starting it. Commit only named files.
**Acceptance/stop:** stale/wrong-boot/missing evidence is never healthy; one failed check does not
stop later probes; no model call occurs. Stop after this catalogue works, not after surveying all services.

## H2 — One incident owner and independent hard supervision

**Owner/budget:** Sol medium, 20 minutes. Local child: pure reducer cases, <=300 seconds.
**Depends on:** H1, existing survival guardian.
**Files:** create `survival/health.py`, `tests/test_mvp_incidents.py`; modify
`survival/guardian.py`, `survival/system_control.py` only at the incident dispatch/reporting adapter.
**Interfaces:** `new_incident(subsystem_id: str, fingerprint: str, clock: dict) -> dict`;
`reduce_incident(incident: dict, event: dict) -> tuple[dict, list[dict]]`;
`scan_observations(root: Path, definitions: dict, clock: dict) -> list[dict]`.
States: `open`, `repairing`, `verifying`, `awaiting_approval`, `escalated`, `recovered`, `blocked`.
Effects: `report`, `start_repair`, `request_probe`, `request_approval`; each includes incident ID and attempt ID.

- [ ] Add reducer tests, including this case:

```python
from survival.health import new_incident, reduce_incident

def test_claimed_repair_cannot_close_incident():
    state = new_incident("work", "dead_owner", {"boot_id": "b", "monotonic": 1, "utc": "x"})
    state, _ = reduce_incident(state, {"kind": "repair_started", "run_id": "r1"})
    state, effects = reduce_incident(state, {"kind": "repair_finished", "run_id": "r1"})
    assert state["state"] == "verifying"
    assert [item["kind"] for item in effects] == ["request_probe"]
```

- [ ] Run `python3 -m unittest discover -s tests -p 'test_mvp_incidents.py' -v` and observe failure.
- [ ] Implement pure transitions plus a durable effect outbox. Fingerprint uses subsystem/check
  identity, not formatted prose. A repeated failure retains one open incident and one active
  repair attempt. Fresh independent passing observations after the repair generation allow
  recovery; stale observations cannot. Approval-pending repair remains visible without repeated launches.

```python
if event["kind"] == "repair_finished":
    return {**incident, "state": "verifying"}, [
        {"kind": "request_probe", "incident_id": incident["incident_id"],
         "after_run_id": event["run_id"]}]
```

  Guardian uses its installed code and its own clock, validates user observation schema/boot/age,
  and supervises the probe service itself. A dead user health service cannot indefinitely renew
  its own lease. Model quality suggestions are not emergency failures. Progress/report failure
  is separately recorded and cannot halt deterministic containment.
- [ ] Run new tests and existing survival guardian/gateway tests. Review replay of one pending
  effect across guardian restart and three repeated observations. Commit the bounded change.
**Acceptance/stop:** one incident/attempt per persistent cause; only independent fresh proof closes it.

## H3 — Bounded recovery outside the failed ordinary scheduler

**Owner/budget:** Sol medium, 25 minutes; split adapter, reducer tests and output validation among
local <=300-second tasks only after the interface is fixed.
**Depends on:** H2, R2-R7, C3.
**Files:** create `ecosystem/repair_runner.py`, `scripts/incident_repair`,
`services/systemd/agent-incident-repair@.service`, `tests/test_mvp_repair.py`;
modify installed guardian action allowlist and `ecosystem/executor.py` at the reusable run boundary.
**Interfaces:** `repair_event(run: dict, observation: dict) -> dict`;
`run_repair(incident: dict, task_contract: dict, execute: Callable, report: Callable) -> dict`.
Installed adapters: `start_repair_unit(run_id: str, systemctl: Callable) -> dict`;
`reconcile_repair_run(request: dict, unit_observation: dict, result: dict | None) -> dict`;
`ingest_repair_observation(incident: dict, run: dict, observation: dict) -> dict`.
`contained` maps to H2 `repair_finished`; `candidate_ready` maps to `candidate_pending`
and `awaiting_approval`, not an early health probe. Only later verified activation maps
to `repair_finished`. `progress` remains repairing; failures map to bounded escalation.
Observation kinds: `progress`, `partial`, `candidate_ready`, `contained`, `failed`, `deadline`,
`backend_lost`; progress carries evidence references, not arbitrary privileged instructions.

- [ ] Write the failure/escalation example and resource-denial test:

```python
from ecosystem.repair_runner import repair_event

def test_failed_runner_preserves_findings_for_escalation():
    result = repair_event({"run_id": "r1", "incident_id": "i1",
                           "handoff_path": "runs/r1/handoff.md"},
                          {"kind": "backend_lost", "evidence": ["runs/r1/events.jsonl"]})
    assert result["kind"] == "escalate"
    assert result["handoff_path"] == "runs/r1/handoff.md"
    assert result["incident_id"] == "i1"
```

- [ ] Run `python3 -m unittest discover -s tests -p 'test_mvp_repair.py' -v`; observe missing runner failure.
- [ ] Implement guardian-owned launch intent plus allowlisted David-owned unit; it uses the same
  run/budget/context mechanism as ordinary work but a recovery admission class and no dependency
  on the ordinary scheduler. Root accepts only installed incident/run identities. Authority is
  fixed by incident scope; a model cannot choose a unit, command, destination or root path.

  Guardian publishes `/var/lib/cointelprofessional/repair_requests/<run_id>.json` with
  schema version, incident/run IDs, task contract, deadline and expected result path.
  `run_id` is exactly `repair-` plus 32 lowercase hexadecimal digits, generated by the
  guardian. It starts only `agent-incident-repair@<run_id>.service`; the installed user
  entry point derives the request/result paths from that validated ID. David's runner
  writes `repair_results/<run_id>.json` with matching IDs, boot/process identity,
  outcome, evidence references, handoff path and observed completion time. Permissions
  grant request read and result write separately. Guardian compares recorded IDs and
  live unit/PID-start postconditions; missing/malformed/dead-runner results reconcile
  to a bounded failed attempt, never a second simultaneous recovery run. Test this
  actual constructor with only systemd/clock/inference fingertips substituted.

```python
if observation["kind"] in {"failed", "deadline", "backend_lost"}:
    return {"kind": "escalate", "incident_id": run["incident_id"],
            "run_id": run["run_id"], "handoff_path": run["handoff_path"],
            "evidence": observation.get("evidence", [])}
```

  Initial repair gets 180 seconds, escalation a new resource-admitted route and a 300-second
  dispatch budget. At most two repair attempts before a visible blocker. Resource pressure may
  defer the model while deterministic recovery keeps contact alive. Code repairs produce an
  isolated candidate for P1-P4 approval; existing allowlisted restart/containment can run now.
  Terminal context overflow is forbidden: R6 continuation applies to this runner too.
- [ ] Exercise process death, deadline, model loss, explicit escalation and independent probe
  in fake-boundary tests. Report directly through the survival critical-message adapter with
  deduplicated phase/attempt IDs. Commit named files only.
**Acceptance/stop:** kill the fake ordinary scheduler; recovery still dispatches, reports and preserves
handoff. Stop after one repaired incident and one bounded failed escalation scenario work offline.

## H4 — Truthful Coin status and two live recovery observations

**Owner/budget:** Sol medium, 15 minutes; live portion coordinator-only under the smoke fence.
**Depends on:** H1-H3, C5, R7.
**Files:** create `ecosystem/subsystems.py`, `tests/test_mvp_status.py`; modify
`ecosystem/fast_control.py`, `roles/_control-plane.md`, `docs/operations.md` at the status query.
**Interfaces:** `project_status(definitions: dict, observations: list[dict], jobs: list[dict], clock: dict) -> dict`;
`subsystem_detail(subsystem_id: str, projection: dict) -> dict`.

- [ ] Test that stale evidence is exposed rather than restated as healthy:

```python
from ecosystem.subsystems import subsystem_detail

def test_status_preserves_pending_approval():
    view = {"work": {"health": "suspect", "incident_state": "awaiting_approval",
                     "active_agents": [], "observed_at": "2026-09-05T00:00:00Z"}}
    assert subsystem_detail("work", view)["incident_state"] == "awaiting_approval"
```

- [ ] Run `python3 -m unittest discover -s tests -p 'test_mvp_status.py' -v`.
- [ ] Implement read-only projection from jobs, model leases, observations and incidents. Preserve
  agent name, role, task, state, age, model and context allocation/usage where measured; say
  unknown where not measured. No projection writes authoritative jobs. Fast-control includes
  a bounded projection or one bounded read-only detail call inside its front deadline.
- [ ] Run focused tests, then close worker admission and wait for all local workers. Use C5's
  smoke driver to expire a test-owned lease, observe one repair/report/fresh probe, and run a
  failed repair with findings preserved. Never corrupt an unrelated real job. Record actual
  delivery and incident IDs locally without private content in Git.
**Acceptance/stop:** Coin's answer agrees with durable facts; successful containment closes only
after fresh evidence; failed repair is visible and bounded. A defect returns to its owning task.

## H5 — Small and large health inspectors with enforced priority

**Owner/budget:** Sol medium, 15 minutes. Local child: role description/profile tests, <=300 seconds.
**Depends on:** A3, H4, R3-R4. H1-H4 do not depend on this task.
**Files:** create `roles/health_inspector.md`, `ecosystem/health_inspection.py`,
`tests/test_mvp_health_inspection.py`; modify `config/autonomy.json`, `config/scheduling.json`.
**Interfaces:** `inspection_request(profile: str, subsystem_id: str, observation: dict, policy: dict) -> dict`.
Profiles are `small` and `large`; the scheduler resolves trusted authority and priority
from installed configuration. Generated role text/request payload cannot self-promote.

- [ ] Test that the two profiles remain distinct data:

```python
from ecosystem.health_inspection import inspection_request

def test_inspector_profiles_have_distinct_trusted_priorities():
    policy = {"small": {"priority": 800, "run_seconds": 30},
              "large": {"priority": 700, "run_seconds": 120}}
    observation = {"boot_id": "b", "subsystem_id": "work", "status": "suspect",
                   "evidence_refs": ["health/work.json"]}
    small = inspection_request("small", "work", observation, policy)
    large = inspection_request("large", "work", observation, policy)
    assert small["execution_profile"] == "small"
    assert large["execution_profile"] == "large"
    assert small["priority"] > large["priority"]
```

- [ ] Run `python3 -m unittest discover -s tests -p 'test_mvp_health_inspection.py' -v`.
- [ ] Define the common role: inspect actual bounded health evidence, distinguish facts from
  conjecture, emit a grounded observation or scoped repair/improvement request, never renew
  its own lease. Small uses the qualified small model/short evidence; large uses the largest
  safe qualified local model/context. Both use R5/R6 continuation and stop budgets.
- [ ] Add one system-wide small cadence of 60 seconds/30-second budget and one large cadence
  of 600 seconds/120-second budget, rotating target subsystem. Reuse A3 scheduling,
  source-key deduplication and R3/R4 enforcement. Do not multiply cadences by subsystem
  count or launch a scheduler/service per inspector. Rate policy bounds demand;
  eligible small inspection still outranks large and ordinary work.
- [ ] Integration-test queued and running ordering: Sole Survivor > Coin > small inspector >
  large inspector > ordinary job, while the front reserve remains usable. Test an ordinary
  worker spoofing `health_inspector` cannot claim this profile. Age boosts cannot cross 700.
- [ ] Run health/priority/autonomy focused tests; commit config, role and helper. During A5,
  observe one real small and one large inspection plus ordinary work with Coin responsive.
**Acceptance/stop:** the priority order is enforced, inspection runs at both sizes, and one
added role/profile requires no scheduler source branch.
