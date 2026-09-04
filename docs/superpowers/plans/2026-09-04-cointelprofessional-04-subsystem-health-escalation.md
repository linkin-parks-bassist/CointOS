# Cointelprofessional Subsystem Health and Escalation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide central subsystem status, hard health leases, directly reporting bounded repair, and preserved-context escalation.

**Architecture:** Tracked subsystem definitions drive a read-only runtime projection and per-subsystem heartbeat contracts. The permanent guardian reduces stale leases into deduplicated incidents, launches a restricted repair runner outside the ordinary scheduler, accepts progress/manual escalation, and escalates automatically on timeout, death, invalid completion, or context failure.

**Tech Stack:** Python 3, JSON/JSONL, monotonic clocks, systemd transient/user units, the survival critical outbox, OpenCode session records, Lemonade routing, and `unittest`.

**Spec:** `docs/superpowers/specs/2026-09-04-cointelprofessional-survival-control-design.md`

## Global Constraints

- Runtime subsystem state is a projection; job, turn, systemd, and model records remain authoritative.
- Unimplemented subsystems are queryable but have no heartbeat deadline or monitor activation.
- Heartbeat renewal requires all contract checks and all confirmed health-gap checks.
- Incident repair and progress reporting do not depend on the ordinary scheduler or notifier.
- Successful smaller-model repair plus a fresh independent probe closes the incident without escalation.
- Resource admission remains authoritative for emergency model/context choice.
- New function-style test modules end with the repository's existing `load_tests`
  collector so `unittest` discovers every `test_*` function.

---

### Task 1: Subsystem catalogue and derived status projection

**Files:**
- Create: `config/subsystems/cointelprofessional.json`
- Create: `config/subsystems/lifecycle.json`
- Create: `config/subsystems/health_supervision.json`
- Create: `config/subsystems/inference.json`
- Create: `config/subsystems/dispatch.json`
- Create: `config/subsystems/scheduler.json`
- Create: `config/subsystems/executor.json`
- Create: `config/subsystems/notification.json`
- Create: `config/subsystems/resource_control.json`
- Create: `config/subsystems/orchestrator.json`
- Create: `config/subsystems/messaging.json`
- Create: `ecosystem/subsystems.py`
- Create: `tests/test_subsystems.py`

**Interfaces:**
- Produces: `definitions(root: Path = ROOT) -> dict[str, dict]`
- Produces: `project(definition: dict, facts: dict, now: datetime) -> dict`
- Produces: `refresh(fact_adapters: dict, root: Path = ROOT) -> dict[str, dict]`
- Produces: `summary(root: Path = ROOT) -> dict`
- Produces: `detail(subsystem_id: str, root: Path = ROOT) -> dict`

- [ ] **Step 1: Write catalogue, planned-state, and active-agent tests**

```python
def test_catalogue_contains_required_subsystems():
    loaded = subsystems.definitions()
    assert set(loaded) == {"cointelprofessional", "lifecycle", "health_supervision",
                           "inference", "dispatch", "scheduler", "executor",
                           "notification", "resource_control", "orchestrator",
                           "messaging"}


def test_unimplemented_subsystem_has_no_lease():
    projection = subsystems.project(definition("orchestrator", "unimplemented"),
                                    empty_facts(), fixed_now())
    assert projection["health"] == "unimplemented"
    assert projection["heartbeat"] is None


def test_agent_projection_tolerates_optional_role():
    facts = facts_with_job(name="Noether", role=None, task="inspect dispatch",
                           state="running", context_tokens=32768)
    item = subsystems.project(definition("dispatch"), facts, fixed_now())["active_agents"][0]
    assert item["name"] == "Noether"
    assert item["role"] is None
    assert item["age_seconds"] == 30
```

- [ ] **Step 2: Run and confirm missing catalogue failure**

Run: `python3 -m unittest tests.test_subsystems -v`

Expected: FAIL because subsystem definitions and projection code are absent.

- [ ] **Step 3: Implement strict definitions and read-only projections**

Each JSON definition contains exactly `schema_version`, `subsystem_id`, `title`,
`purpose`, `implementation_state`, `dependencies`, `services`, `process_groups`,
`heartbeat_contract`, `repair_authority`, and `escalation_class`.

```python
def refresh(fact_adapters, root=cli.ROOT):
    facts = collect_facts(fact_adapters)
    projections = {}
    for subsystem_id, definition in definitions(root).items():
        value = project(definition, facts, datetime.now(timezone.utc))
        cli.atomic_json(root / "state/subsystems" / subsystem_id / "status.json", value)
        projections[subsystem_id] = value
    return projections
```

Malformed authoritative records become evidence entries in the owning projection;
they do not stop later subsystems from refreshing.

- [ ] **Step 4: Run projection and current status tests**

Run: `python3 -m unittest tests.test_subsystems tests.test_conversation tests.test_executor -v`

Expected: PASS.

- [ ] **Step 5: Commit central subsystem state**

```bash
git add config/subsystems ecosystem/subsystems.py tests/test_subsystems.py
git commit -m "Add central subsystem status projections"
```

### Task 2: Heartbeat contracts and atomic leases

**Files:**
- Create: `ecosystem/health_checks.py`
- Create: `ecosystem/heartbeat.py`
- Create: `ecosystem/health_scheduler.py`
- Create: `scripts/health-scheduler`
- Create: `services/systemd/agent-health-scheduler.service`
- Create: `tests/test_heartbeat.py`
- Modify: `config/subsystems/*.json`

**Interfaces:**
- Produces: `run_check(check_id: str, facts: dict) -> dict`
- Produces: `required_checks(definition: dict, health_gaps: list[dict]) -> list[str]`
- Produces: `renew(subsystem_id: str, evidence: list[dict], verdict: dict, clock: dict) -> dict`
- Produces: `due_subsystem(definitions: dict, leases: dict, now_monotonic: float, policy: dict) -> str | None`

- [ ] **Step 1: Write all-checks, wrong-boot, stale-evidence, and staggering tests**

```python
def test_lease_renews_only_when_every_required_check_passes(root):
    evidence = [check("service_active", True), check("queue_progress", False)]
    with unittest.TestCase().assertRaisesRegex(RuntimeError, "queue_progress"):
        heartbeat.renew("scheduler", evidence, healthy_verdict(), fixed_clock())
    assert not heartbeat_path(root, "scheduler").exists()


def test_confirmed_gap_becomes_required_check():
    checks = heartbeat.required_checks(definition("scheduler"),
        [{"state": "confirmed", "check_id": "no_stuck_claims"}])
    assert "no_stuck_claims" in checks


def test_schedule_offsets_are_stable_and_distinct():
    first = health_scheduler.offsets(["dispatch", "scheduler", "executor"], 300, 25)
    second = health_scheduler.offsets(["dispatch", "scheduler", "executor"], 300, 25)
    assert first == second
    assert len(set(first.values())) == 3
```

- [ ] **Step 2: Run heartbeat tests**

Run: `python3 -m unittest tests.test_heartbeat -v`

Expected: FAIL because health checks, leases, and scheduler do not exist.

- [ ] **Step 3: Implement bounded probes and lease records**

```python
def renew(subsystem_id, evidence, verdict, clock, root=cli.ROOT):
    failures = [item["check_id"] for item in evidence if item.get("status") != "pass"]
    if failures or verdict.get("status") != "healthy":
        raise RuntimeError("heartbeat refused: " + ", ".join(failures))
    lease = {"schema_version": 1, "subsystem_id": subsystem_id,
             "boot_id": clock["boot_id"], "generation": clock["generation"],
             "observed_monotonic": clock["monotonic"], "observed_at": clock["utc"],
             "checks": evidence, "verdict": verdict}
    cli.atomic_json(heartbeat_path(root, subsystem_id), lease)
    return lease
```

The scheduler creates one small roleless probe task per due subsystem and enforces
the configured fifteen-second deadline. Deterministic checks run outside the model;
the model verdict is necessary but never sufficient.

- [ ] **Step 4: Run heartbeat, timing, and subsystem tests**

Run: `python3 -m unittest tests.test_heartbeat tests.test_time_policy tests.test_subsystems -v`

Expected: PASS.

- [ ] **Step 5: Commit heartbeat supervision inputs**

```bash
git add ecosystem/health_checks.py ecosystem/heartbeat.py ecosystem/health_scheduler.py \
  scripts/health-scheduler services/systemd/agent-health-scheduler.service \
  tests/test_heartbeat.py config/subsystems
git commit -m "Add per-subsystem heartbeat leases"
```

### Task 3: Health incident reducer and hard lease watcher

**Files:**
- Create: `survival/health.py`
- Modify: `survival/guardian.py`
- Create: `tests/test_health_incidents.py`
- Modify: `tests/test_survival_guardian.py`

**Interfaces:**
- Produces: `lease_status(definition: dict, lease: dict | None, clock: dict, policy: dict) -> dict`
- Produces: `new_incident(subsystem_id: str, failure: dict, clock: dict) -> dict`
- Produces: `reduce_incident(incident: dict, event: dict) -> tuple[dict, list[dict]]`
- Produces: `watch_leases(store: Path, repository: Path, clock: dict) -> list[dict]`

- [ ] **Step 1: Write stale, wrong-boot, deduplication, and repair-success tests**

```python
def test_sixty_second_lease_is_stale():
    result = health.lease_status(implemented_definition(), lease_at(40),
                                 clock_at(100), time_policy(maximum_age_seconds=60))
    assert result["status"] == "stale"


def test_repeated_stale_checks_open_one_incident(root):
    first = health.watch_leases(root, repository(), clock_at(100))
    second = health.watch_leases(root, repository(), clock_at(105))
    assert first[0]["incident_id"] == second[0]["incident_id"]
    assert len(list((root / "incidents").glob("*.json"))) == 1


def test_verified_fresh_lease_closes_without_escalation():
    incident = repairing_incident()
    state, effects = health.reduce_incident(incident,
        {"kind": "fresh_probe", "observation_id": "obs-2"})
    assert state["state"] == "recovered"
    assert "launch_emergency_repair" not in effect_kinds(effects)
```

- [ ] **Step 2: Run incident tests**

Run: `python3 -m unittest tests.test_health_incidents tests.test_survival_guardian -v`

Expected: FAIL because lease watching and incident reduction are absent.

- [ ] **Step 3: Implement fingerprinted incident transitions**

```python
INCIDENT_STATES = {"suspect", "repair_starting", "repairing", "verifying",
                   "recovered", "closed", "escalating", "operator_required"}


def incident_fingerprint(subsystem_id, failure):
    canonical = json.dumps({"subsystem_id": subsystem_id,
                            "evidence_codes": sorted(failure["evidence_codes"])},
                           sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:20]
```

The watcher runs every five seconds from the permanent guardian. Its first effects
are `critical_update(incident_opened)` and `launch_initial_repair`. Repeated stale
observations update `last_seen_at`; they do not create new agents or messages.

- [ ] **Step 4: Run incident and gateway outbox tests**

Run: `python3 -m unittest tests.test_health_incidents tests.test_survival_guardian tests.test_survival_gateway -v`

Expected: PASS.

- [ ] **Step 5: Commit hard lease supervision**

```bash
git add survival/health.py survival/guardian.py tests/test_health_incidents.py \
  tests/test_survival_guardian.py
git commit -m "Escalate stale subsystem health leases"
```

### Task 4: Reporting repair runner and context-failure escalation

**Files:**
- Create: `ecosystem/repair_runner.py`
- Create: `ecosystem/incident_client.py`
- Create: `scripts/incident-repair`
- Create: `services/systemd/agent-incident-repair@.service`
- Modify: `survival/protocol.py`
- Modify: `survival/guardian.py`
- Modify: `ecosystem/executor.py`
- Modify: `ecosystem/models.py`
- Test: `tests/test_repair_runner.py`
- Test: `tests/test_health_incidents.py`

**Interfaces:**
- Produces: `report_progress(incident_id: str, run_token: str, findings: str, action: str, next_check: str) -> dict`
- Produces: `escalate_incident(incident_id: str, run_token: str, findings: str, reason: str, preserved_context: dict) -> dict`
- Produces: `run_incident(incident: dict, infer: Callable, tools: dict, clock: Callable) -> dict`
- Produces: `select_emergency_route(incident: dict, inventory: dict) -> dict`
- Produces: `capability_rank(model: dict) -> tuple[int, int, float]`

- [ ] **Step 1: Write reporting, manual escalation, successful repair, and death tests**

```python
def test_progress_report_reaches_critical_outbox(root):
    incident_client.report_progress("incident-1", token(), "worker was dead",
                                    "restarted worker", "probe queue progress")
    message = read_critical_outbox(root)
    assert message["kind"] == "repair_progress"
    assert "worker was dead" in message["message"]


def test_manual_escalation_preserves_findings():
    result = repair_runner.run_incident(incident(), infer=manual_escalating_model(),
                                        tools=fake_tools(), clock=fake_clock())
    assert result["terminal"] == "escalate"
    assert result["preserved_context"]["findings"] == "state reducer is corrupt"


def test_context_overflow_without_handoff_escalates():
    event = {"kind": "runner_exit", "reason": "context_overflow",
             "handoff": None, "transcript": "run.jsonl"}
    state, effects = health.reduce_incident(repairing_incident(), event)
    assert "critical_update" in effect_kinds(effects)
    assert "launch_emergency_repair" in effect_kinds(effects)


def test_success_requires_independent_probe():
    result = repair_runner.run_incident(incident(), infer=claims_success(),
                                        tools=fake_tools(), clock=fake_clock())
    assert result["terminal"] == "verify"
    assert result["recovered"] is False
```

- [ ] **Step 2: Run repair tests**

Run: `python3 -m unittest tests.test_repair_runner tests.test_health_incidents -v`

Expected: FAIL because direct reporting and repair supervision are absent.

- [ ] **Step 3: Implement roleless restricted repair execution**

The guardian starts `agent-incident-repair@<incident_id>.service` through the user
manager. It passes an opaque run token through a protected credential. The service
runs as David, not root, and its only guardian operations are progress, escalate,
and terminal result.

```python
def terminal_event(exit_code, result, usage, allocation):
    if usage and usage["total_tokens"] >= allocation:
        return {"kind": "runner_exit", "reason": "context_overflow",
                "handoff": result.get("handoff") if result else None}
    if exit_code != 0 or not valid_terminal_result(result):
        return {"kind": "runner_exit", "reason": "invalid_or_failed",
                "handoff": result.get("handoff") if result else None}
    return {"kind": result["terminal"], "result": result}
```

At the configured rollover fraction, request a semantic handoff. If absent, preserve
the raw transcript/session pointer and escalate. A reported repair always enters
`verifying`; only a fresh heartbeat closes it.

- [ ] **Step 4: Implement strongest-safe emergency routing**

```python
def select_emergency_route(incident, inventory):
    candidates = [candidate for candidate in inventory["models"]
                  if models.emergency_compatible(candidate, incident)]
    admitted = [(candidate, models.context_options(candidate, inventory))
                for candidate in candidates if models.admission(candidate["id"], inventory)[0]]
    usable = [(candidate, contexts) for candidate, contexts in admitted if contexts]
    if not usable:
        return {"action": "operator_required", "reason": "no safe recovery model"}
    candidate, contexts = max(usable, key=lambda item: models.capability_rank(item[0]))
    return {"action": "launch", "model": candidate["id"],
            "context_tokens": max(contexts)}
```

Resource incidents never waive deterministic admission. The critical update states
when the nominal largest model is unsafe and which alternative was selected.

- [ ] **Step 5: Run repair, executor, and routing tests**

Run: `python3 -m unittest tests.test_repair_runner tests.test_health_incidents tests.test_executor tests.test_resource_control -v`

Expected: PASS for manual escalation, context death, timeout, invalid result,
independent verification, and largest-safe context.

- [ ] **Step 6: Commit reported repair and escalation**

```bash
git add ecosystem/repair_runner.py ecosystem/incident_client.py scripts/incident-repair \
  services/systemd/agent-incident-repair@.service survival/protocol.py \
  survival/guardian.py ecosystem/executor.py ecosystem/models.py \
  tests/test_repair_runner.py tests/test_health_incidents.py
git commit -m "Add reported bounded repair and escalation"
```
