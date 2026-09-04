# Cointelprofessional Deep Monitors and Live Acceptance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add staggered subsystem monitor agents which evolve heartbeat contracts, expose quick status through Cointelprofessional, then deploy and prove the entire survival path live.

**Architecture:** One five-minute monitor schedule produces one bounded roleless agent per implemented subsystem at stable offsets. Supported blind spots become durable health gaps and one verified contract-change job. Final fault injection exercises the installed gateway, guardian, Lemonade teardown, fast control, heartbeat repair, and context escalation through actual process and Telegram boundaries.

**Tech Stack:** Python 3, JSON subsystem contracts, existing durable jobs/verifier, systemd system/user units, Telegram, Lemonade, OpenCode, and `unittest`.

**Spec:** `docs/superpowers/specs/2026-09-04-cointelprofessional-survival-control-design.md`

## Global Constraints

- Monitor agents cannot renew their own subsystem heartbeat.
- A model conjecture cannot permanently rewrite a health contract without primary evidence, a focused regression test, and independent verification.
- A confirmed unresolved gap blocks heartbeat renewal.
- Monitor schedules are five minutes initially and staggered by `config/time.cfg`.
- Live deployment must preserve credentials, append-only logs, unrelated dirty changes, desktop responsiveness, and the kernel OOM count.
- Do not push or merge; the completed local topic branch remains for David's review.
- New function-style test modules end with the repository's existing `load_tests`
  collector so `unittest` discovers every `test_*` function.

---

### Task 1: Staggered per-subsystem monitor scheduling

**Files:**
- Create: `ecosystem/monitor_scheduler.py`
- Create: `ecosystem/subsystem_monitor.py`
- Create: `scripts/subsystem-monitor-scheduler`
- Create: `services/systemd/agent-subsystem-monitor.service`
- Create: `tests/test_subsystem_monitor.py`

**Interfaces:**
- Consumes: subsystem definitions/status and timing policy
- Produces: `monitor_offsets(subsystem_ids: list[str], period: float, spacing: float) -> dict[str, float]`
- Produces: `due_monitors(state: dict, definitions: dict, now: float, policy: dict) -> list[str]`
- Produces: `monitor(subsystem_id: str, evidence: dict, infer: Callable) -> dict`

- [ ] **Step 1: Write stagger, implementation-state, and bounded-output tests**

```python
def test_each_implemented_subsystem_runs_once_per_period():
    definitions = three_implemented_and_one_unimplemented()
    schedule = monitor_scheduler.schedule(definitions, period=300, spacing=25)
    assert set(schedule) == {"dispatch", "scheduler", "executor"}
    assert sorted(schedule.values()) == [0, 25, 50]


def test_due_monitor_is_not_reenqueued_in_same_generation():
    state = {"scheduler": {"last_generation": 7}}
    due = monitor_scheduler.due_monitors(state, definitions(), now=350,
                                         policy=monitor_policy(generation=7))
    assert "scheduler" not in due


def test_monitor_cannot_claim_heartbeat_renewal():
    with unittest.TestCase().assertRaisesRegex(ValueError, "unsupported monitor action"):
        subsystem_monitor.validate_result({"action": "renew_heartbeat"})


def test_monitor_period_comes_from_central_time_policy():
    policy = time_policy.load()
    assert time_policy.seconds(policy, "monitor", "activation_period_seconds") == 300
```

- [ ] **Step 2: Run and confirm missing monitor failure**

Run: `python3 -m unittest tests.test_subsystem_monitor -v`

Expected: FAIL because monitor scheduling does not exist.

- [ ] **Step 3: Implement stable scheduling and roleless monitor jobs**

```python
def schedule(definitions, period, spacing):
    enabled = sorted(key for key, value in definitions.items()
                     if value["implementation_state"] == "implemented")
    if enabled and spacing * (len(enabled) - 1) >= period:
        raise ValueError("monitor stagger does not fit activation period")
    return {subsystem_id: index * spacing
            for index, subsystem_id in enumerate(enabled)}
```

The scheduler enqueues with `role=None`, source
`subsystem-monitor:<subsystem_id>:<generation>`, the configured 120-second deadline,
and an idempotency key using the same fields. Each prompt limits evidence to that
subsystem and requires `healthy`, `health_gap`, or `report_only` output.

- [ ] **Step 4: Run monitor and timing tests and commit**

Run: `python3 -m unittest tests.test_subsystem_monitor tests.test_time_policy tests.test_subsystems -v`

Expected: PASS.

```bash
git add ecosystem/monitor_scheduler.py ecosystem/subsystem_monitor.py \
  scripts/subsystem-monitor-scheduler services/systemd/agent-subsystem-monitor.service \
  tests/test_subsystem_monitor.py
git commit -m "Schedule staggered subsystem monitors"
```

### Task 2: Durable health gaps and verified contract changes

**Files:**
- Create: `ecosystem/health_gaps.py`
- Create: `tests/test_health_gaps.py`
- Modify: `ecosystem/subsystem_monitor.py`
- Modify: `ecosystem/heartbeat.py`
- Modify: `ecosystem/verification.py`
- Modify: `config/subsystems/*.json`

**Interfaces:**
- Produces: `open_gap(subsystem_id: str, finding: dict, monitor_job: dict) -> dict`
- Produces: `confirm_gap(gap_id: str, check_id: str, evidence: dict) -> dict`
- Produces: `disprove_gap(gap_id: str, evidence: dict) -> dict`
- Produces: `enqueue_contract_change(gap: dict) -> str`

- [ ] **Step 1: Write deduplication, blocking, disproof, and verification tests**

```python
def test_repeated_finding_opens_one_gap(root):
    first = health_gaps.open_gap("scheduler", finding("stuck claims"), monitor_job())
    second = health_gaps.open_gap("scheduler", finding("stuck claims"), monitor_job())
    assert first["gap_id"] == second["gap_id"]


def test_confirmed_gap_blocks_renewal_until_check_passes(root):
    gap = health_gaps.confirm_gap("gap-1", "no_stuck_claims", evidence())
    with unittest.TestCase().assertRaisesRegex(RuntimeError, "no_stuck_claims"):
        heartbeat.renew("scheduler", evidence_without("no_stuck_claims"),
                        healthy_verdict(), fixed_clock())


def test_disproved_gap_does_not_change_contract(root):
    health_gaps.disprove_gap("gap-1", evidence("claim was live"))
    assert "no_stuck_claims" not in configured_checks("scheduler")


def test_contract_job_requires_regression_test_and_verifier_acceptance(root):
    job = read_job(root, health_gaps.enqueue_contract_change(confirmed_gap()))
    assert "regression test" in job["task"]
    assert job["requires_verification"] is True
```

- [ ] **Step 2: Run and confirm missing gap model**

Run: `python3 -m unittest tests.test_health_gaps tests.test_heartbeat -v`

Expected: FAIL because durable health gaps do not exist.

- [ ] **Step 3: Implement evidence-backed gap transitions**

```python
GAP_STATES = {"suspected", "confirmed", "implementing", "verifying",
              "resolved", "disproved"}


def gap_fingerprint(subsystem_id, finding):
    canonical = json.dumps({"subsystem_id": subsystem_id,
                            "evidence_codes": sorted(finding["evidence_codes"]),
                            "summary": finding["summary"]},
                           sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:20]
```

A suspected gap marks status `suspect` and creates one verification/implementation
job. Confirmation adds a temporary required check immediately. Permanent contract
changes land only with their failing/passing regression test and accepted verifier
record.

- [ ] **Step 4: Run gap, heartbeat, monitor, and verifier tests**

Run: `python3 -m unittest tests.test_health_gaps tests.test_heartbeat tests.test_subsystem_monitor tests.test_executor -v`

Expected: PASS.

- [ ] **Step 5: Commit evolving health contracts**

```bash
git add ecosystem/health_gaps.py ecosystem/subsystem_monitor.py ecosystem/heartbeat.py \
  ecosystem/verification.py config/subsystems tests/test_health_gaps.py
git commit -m "Turn monitor findings into verified health checks"
```

### Task 3: Quick subsystem questions through fast control

**Files:**
- Modify: `ecosystem/fast_control.py`
- Modify: `ecosystem/subsystems.py`
- Modify: `roles/_control-plane.md`
- Test: `tests/test_fast_control.py`
- Test: `tests/test_subsystems.py`

**Interfaces:**
- Consumes: `subsystems.summary()` and `subsystems.detail()`
- Produces: `inspect_subsystem(subsystem_id: str) -> dict`
- Changes: fast decision may use one read-only `inspect_subsystem` tool before its terminal respond/dispatch result

- [ ] **Step 1: Write direct status-answer and nonexistent-subsystem tests**

```python
def test_scheduler_question_answers_without_dispatch():
    decision = fast_control.decide(
        "How is the scheduler?", [], summary_with("scheduler", "healthy"),
        infer=status_answering_model())
    assert decision["decision"] == "respond"
    assert "healthy" in decision["reply"]


def test_detail_has_agents_heartbeat_and_incident():
    detail = subsystems.detail("scheduler", root)
    assert set(detail) >= {"health", "heartbeat", "active_agents", "incidents"}


def test_unknown_subsystem_is_explicit():
    with unittest.TestCase().assertRaisesRegex(KeyError, "unknown subsystem"):
        subsystems.detail("telepathy", root)
```

- [ ] **Step 2: Run and observe status-tool failure**

Run: `python3 -m unittest tests.test_fast_control tests.test_subsystems -v`

Expected: FAIL because fast control does not expose subsystem detail.

- [ ] **Step 3: Add one bounded read-only tool loop**

Allow at most one `inspect_subsystem` tool call and one terminal model response inside
the existing front deadline. The tool accepts only a catalogue identifier and reads
the projection without mutation. Include implementation state so Cointelprofessional
truthfully says that orchestrator and messaging are not yet implemented.

- [ ] **Step 4: Run fast-control regression tests and commit**

Run: `python3 -m unittest tests.test_fast_control tests.test_subsystems tests.test_fast_worker -v`

Expected: PASS with no job created for a status question.

```bash
git add ecosystem/fast_control.py ecosystem/subsystems.py roles/_control-plane.md \
  tests/test_fast_control.py tests/test_subsystems.py
git commit -m "Expose subsystem health to Cointelprofessional"
```

### Task 4: Full offline fault-injection harness

**Files:**
- Create: `tests/integration/test_cointelprofessional_survival.py`
- Create: `scripts/test-survival-flow`
- Modify: `services/systemd/*.service`
- Modify: `services/systemd/*.timer`
- Modify: `services/systemd/*.path`
- Modify: `services/system/*.service`
- Modify: `services/system/*.socket`

**Interfaces:**
- Consumes: all prior plan interfaces
- Produces: a hermetic fake Telegram API, fake Lemonade daemon, fake model workers, disposable state roots, and process identity assertions

- [ ] **Step 1: Write the end-to-end scenarios before the harness implementation**

```python
def test_gateway_answers_restart_while_every_agent_daemon_is_dead(harness):
    stop_destructible_plane(harness)
    reply = telegram_send(harness, "RESTART")
    assert reply["received_after_seconds"] < 2.0
    assert gateway_same_process_identity(harness)
    assert wait_lifecycle_completed(harness)


def test_small_repair_success_never_launches_emergency_model(harness):
    expire_heartbeat(harness, "scheduler")
    repair_fix_and_report(harness, "restarted scheduler")
    pass_fresh_probe(harness, "scheduler")
    assert incident_state(harness) == "closed"
    assert emergency_launch_count(harness) == 0


def test_context_death_reports_then_escalates_with_largest_safe_context(harness):
    expire_heartbeat(harness, "executor")
    repair_report(harness, "found truncated executor state")
    kill_repair(harness, reason="context_overflow", handoff=None)
    assert last_telegram_message(harness)["kind"] == "repair_escalated"
    assert emergency_context_tokens(harness) == 131072


def test_monitor_gap_blocks_next_heartbeat(harness):
    monitor_find_gap(harness, "dispatch", "claim can remain stuck")
    confirm_gap(harness, check_id="no_stuck_claims")
    assert renew_probe(harness, "dispatch")["refused"] is True
```

- [ ] **Step 2: Run the integration module and confirm fixture failures**

Run: `python3 -m unittest tests.integration.test_cointelprofessional_survival -v`

Expected: FAIL because the process harness fixtures are absent.

- [ ] **Step 3: Implement fake external boundaries and real subprocess orchestration**

`harness` is a plain dictionary of paths, PIDs, captured records, and injected
function adapters; every operation above is a free function. The harness allocates
temporary ports/directories, starts each daemon in a new
process group, records `/proc/<pid>/stat` start identities, drives fake clock files,
and registers a free-function cleanup callback with `unittest.TestCase().addCleanup`.
It never reads real credentials or calls the real Telegram/Lemonade endpoints.

- [ ] **Step 4: Run offline integration and the complete suite**

Run: `./scripts/test-survival-flow`

Expected: every restart/reset/repair/escalation scenario passes and all child
processes are reaped.

Run: `python3 -m unittest discover -s tests -v`

Expected: PASS.

- [ ] **Step 5: Commit offline acceptance**

```bash
git add tests/integration/test_cointelprofessional_survival.py scripts/test-survival-flow \
  services/systemd services/system
git commit -m "Prove Cointelprofessional survival under fault injection"
```

### Task 5: Documentation, durable notes, and static release audit

**Files:**
- Modify: `docs/status.md`
- Modify: `docs/system-map.md`
- Modify: `docs/operations.md`
- Create: `docs/decisions/0007-permanent-cointelprofessional-survival-plane.md`
- Create: `agent_notes/0010-cointelprofessional-survival-plane.md`

**Interfaces:**
- Consumes: verified behavior and exact commands from all prior tasks
- Produces: installation, rollback, incident inspection, configuration tuning, and recovery instructions

- [ ] **Step 1: Reconcile claims against tests and unit files**

Run:

```bash
rg -n "RESTART|RESET|heartbeat|monitor|guardian|gateway|time.cfg" \
  docs services scripts config ecosystem survival tests
```

Expected: every operational claim maps to an implementation or test; no old
three-minute advisory watchdog is described as hard supervision.

- [ ] **Step 2: Write the ADR and maintained agent note**

The ADR records the survival/destructible boundary, dedicated UID and peer
authentication, exact command semantics, optional roles, direct incident messages,
and why a maximum model remains resource-admitted. The agent note names `/root`,
`ingress_audit`, `watchdog_audit`, and `lifecycle_audit`, then records only durable
architectural lessons—not conversation text or credentials.

- [ ] **Step 3: Run static release checks**

```bash
git diff --check
systemd-analyze verify services/system/*.service services/system/*.socket \
  services/systemd/*.service services/systemd/*.timer services/systemd/*.path
python3 -m unittest discover -s tests -v
```

Expected: all commands exit 0.

- [ ] **Step 4: Commit documentation and notes**

```bash
git add docs/status.md docs/system-map.md docs/operations.md \
  docs/decisions/0007-permanent-cointelprofessional-survival-plane.md \
  agent_notes/0010-cointelprofessional-survival-plane.md
git commit -m "Document permanent Cointelprofessional recovery"
```

### Task 6: Install, enable, and execute live acceptance

**Files:**
- Runtime only: `/usr/local/lib/cointelprofessional-survival/`
- Runtime only: `/etc/systemd/system/cointelprofessional-*`
- Runtime only: `/var/lib/cointelprofessional/`
- Runtime only: existing protected Telegram credential files
- Modify after evidence: `docs/status.md`
- Modify after evidence: `agent_notes/0010-cointelprofessional-survival-plane.md`

**Interfaces:**
- Consumes: `scripts/install-survival-plane --enable`
- Produces: live root-owned survival services and recorded acceptance evidence

- [ ] **Step 1: Capture pre-deployment facts without exposing credentials**

```bash
systemctl --user --no-pager --full status agent-telegram.service \
  agent-resource-guard.service agent-ecosystem.path agent-ecosystem.timer
systemctl --no-pager --full status lemond.service
jq '{mode,last_oom_kills,last_resources}' state/resource-control.json
cat /proc/sys/kernel/random/boot_id
```

Expected: current unit/resource state is recorded in the local operator transcript;
no environment or credential content is printed.

- [ ] **Step 2: Install and enable the approved survival boundary**

Run: `sudo ./scripts/install-survival-plane --enable`

Expected: installer validates ownership/modes and units, enables gateway/guardian,
starts the guardian first, stops the old user gateway, atomically imports its durable
Telegram offset, and starts the permanent gateway. If the new poll heartbeat does
not appear within two seconds, systemd continues rapid restart attempts and the
guardian emits a local critical incident; the old gateway is not run concurrently
because two `getUpdates` pollers would race.

- [ ] **Step 3: Perform the live acceptance sequence**

Use the real allowlisted Telegram chat and record update IDs/timestamps without
copying message content into Git:

```text
baseline ordinary message -> generated reply
stop Lemonade -> ordinary message -> deterministic degraded reply
RESTART -> immediate acknowledgement -> phase updates -> generated reply
seed one recoverable agent -> RESTART -> preserved/requeued agent
seed one active fake agent -> RESET -> immediate kill -> reconciled state
expire scheduler lease -> initial repair report -> fresh lease -> no large model
expire executor lease -> context-overflow repair death -> escalation report -> large repair
ask for scheduler and active-agent status -> fast registry answer
```

For both commands, record gateway PID/start identity before and after; it must be
unchanged. Record Lemonade and model-server identities; they must change. Record the
kernel OOM count before and after; it must not increase.

- [ ] **Step 4: Verify postconditions independently**

```bash
systemctl --no-pager --full status cointelprofessional-gateway.service \
  cointelprofessional-guardian.service lemond.service
systemctl --user --no-pager --full status agent-inference-arbiter.service \
  agent-fast-control.service agent-health-scheduler.service \
  agent-subsystem-monitor.service agent-resource-guard.service
find state/subsystems -name heartbeat.json -maxdepth 3 -print
jq -s 'group_by(.state) | map({state: .[0].state, count:length})' state/jobs/*.json
python3 -m unittest discover -s tests -v
```

Expected: survival and destructible units are healthy, every implemented subsystem
has a fresh valid lease, no active record has a dead owner, and the suite passes.

- [ ] **Step 5: Record evidence and commit the live result**

Update status and the maintained note with timestamps, measured latencies, process
identity turnover, incident IDs, OOM delta, and any honestly degraded condition.

```bash
git add docs/status.md agent_notes/0010-cointelprofessional-survival-plane.md
git commit -m "Record live survival-plane acceptance"
```

Stop if any live acceptance item fails. Keep the permanent gateway online, leave the
guardian's incident record open, notify David through Cointelprofessional, and
resume from the failed bounded task after root-cause analysis.
