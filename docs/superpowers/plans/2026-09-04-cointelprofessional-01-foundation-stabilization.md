# Cointelprofessional Foundation Stabilization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the current user-level system safe enough to develop: centralize time policy, make roles optional, and eliminate the observed partial-emergency and busy-model restart storm.

**Architecture:** A typed INI loader becomes the only timing interface. Role lookup becomes optional context resolution rather than validation. Resource recovery becomes an idempotent phase transition which distinguishes model liveness from idleness and confirms non-OOM pressure before entering emergency.

**Tech Stack:** Python 3 standard library (`configparser`, `pathlib`, `time`), JSON state, systemd user services, and `unittest`.

**Spec:** `docs/superpowers/specs/2026-09-04-cointelprofessional-survival-control-design.md`

## Global Constraints

- Work on `fix/cointelprofessional-survival-plane`; preserve every pre-existing uncommitted change and stage only files named by the current task.
- Do not enable new services in this plan. Task 4 alone may restart the existing
  user resource guard after its regression suite passes, solely to clear the
  currently observed partial emergency without restarting Telegram.
- Do not run model inference in tests.
- Roles are nullable advisory context; invalid path syntax must never be used to construct a path.
- A busy or in-use model is live.
- A single non-OOM resource sample cannot enter emergency.
- All durations touched here come from `config/time.cfg`.
- New function-style test modules end with the repository's existing `load_tests`
  collector so `unittest` discovers every `test_*` function.

---

### Task 1: Typed central timing policy

**Files:**
- Create: `config/time.cfg`
- Create: `ecosystem/time_policy.py`
- Create: `tests/test_time_policy.py`

**Interfaces:**
- Produces: `load(path: Path = CONFIG_PATH, required: dict[str, set[str]] = REQUIRED_KEYS) -> dict[str, dict[str, float]]`
- Produces: `seconds(policy: dict, section: str, key: str) -> float`
- Produces: `reload_if_changed(active: dict, active_mtime_ns: int, path: Path = CONFIG_PATH) -> tuple[dict, int, str | None]`
- Produces: `validate(policy: dict) -> None`

- [ ] **Step 1: Write parser and relational-validation failures**

```python
def test_loads_explicit_seconds():
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "time.cfg"
        path.write_text("[heartbeat]\nprobe_deadline_seconds = 15\nmaximum_age_seconds = 60\n")
        policy = time_policy.load(path, required={"heartbeat": {
            "probe_deadline_seconds", "maximum_age_seconds"}})
        assert time_policy.seconds(policy, "heartbeat", "maximum_age_seconds") == 60.0


def test_probe_deadline_must_be_shorter_than_lease():
    with tempfile.TemporaryDirectory() as temporary:
        path = write_complete_policy(Path(temporary), probe_deadline_seconds=60,
                                     maximum_age_seconds=60)
        with unittest.TestCase().assertRaisesRegex(ValueError, "probe_deadline_seconds"):
            time_policy.load(path)


def test_invalid_reload_keeps_last_known_good():
    with tempfile.TemporaryDirectory() as temporary:
        path = write_complete_policy(Path(temporary))
        active = time_policy.load(path)
        mtime = path.stat().st_mtime_ns
        path.write_text("[heartbeat]\nmaximum_age_seconds = nope\n")
        current, current_mtime, error = time_policy.reload_if_changed(active, mtime, path)
        assert current == active
        assert current_mtime == mtime
        assert "maximum_age_seconds" in error
```

Define `write_complete_policy(root: Path, **overrides) -> Path` in the test module;
it writes every required section/key with approved defaults, then applies only the
named overrides. Import `tempfile`, `unittest`, and `Path` explicitly.

- [ ] **Step 2: Run the new test and confirm missing-module failure**

Run: `python3 -m unittest tests.test_time_policy -v`

Expected: FAIL because `ecosystem.time_policy` and `config/time.cfg` do not exist.

- [ ] **Step 3: Add the complete approved INI policy and functional loader**

Implement the exact sections and initial values from the spec, including
`[resource] pressure_confirmation_seconds = 5`,
`emergency_confirmation_seconds = 10`, and `healthy_release_seconds = 60`.
The loader must reject missing sections/keys, unknown sections/keys, booleans,
non-finite values, and values less than or equal to zero.

```python
CONFIG_PATH = cli.ROOT / "config/time.cfg"


def seconds(policy: dict, section: str, key: str) -> float:
    try:
        value = policy[section][key]
    except KeyError as error:
        raise KeyError(f"missing time policy {section}.{key}") from error
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"invalid time policy {section}.{key}")
    return float(value)
```

`reload_if_changed` must parse the whole replacement before returning it. On error,
return the original mapping and mtime with a nonempty diagnostic string.

- [ ] **Step 4: Run focused tests**

Run: `python3 -m unittest tests.test_time_policy -v`

Expected: PASS, including invalid-reload retention and relational validation.

- [ ] **Step 5: Commit only timing-policy files**

```bash
git add config/time.cfg ecosystem/time_policy.py tests/test_time_policy.py
git diff --cached --check
git commit -m "Add central ecosystem timing policy"
```

### Task 2: Optional role context

**Files:**
- Create: `roles/_base.md`
- Modify: `ecosystem/roles.py`
- Modify: `ecosystem/cli.py`
- Modify: `ecosystem/models.py`
- Modify: `ecosystem/resource_control.py`
- Modify: `ecosystem/executor.py`
- Modify: `ecosystem/control_runtime.py`
- Test: `tests/test_optional_roles.py`
- Test: `tests/test_resource_control.py`
- Test: `tests/test_executor.py`

**Interfaces:**
- Produces: `resolve_role(role: str | None) -> dict` with keys `label`, `known`, `context`, and `capabilities`
- Changes: `enqueue_task(role: str | None, task: str, ...) -> str`
- Changes: `render_context(role: str | None, ...) -> str`
- Consumes: existing job records whose `role` may still be a string

- [ ] **Step 1: Write failures for null, unknown, and underscored roles**

```python
def test_optional_and_unknown_roles_use_base_context(root):
    assert roles.resolve_role(None)["known"] is False
    assert "base agent" in roles.resolve_role(None)["context"].lower()
    resolved = roles.resolve_role("novel_specialist")
    assert resolved["label"] == "novel_specialist"
    assert resolved["known"] is False
    assert "base agent" in resolved["context"].lower()


def test_known_underscored_role_is_loaded(root):
    write_role(root, "sole_survivor")
    assert roles.resolve_role("sole_survivor")["known"] is True


def test_path_like_role_never_becomes_a_path(root):
    resolved = roles.resolve_role("../../etc/passwd")
    assert resolved["known"] is False
    assert "passwd" not in resolved["context"]


def test_enqueue_unknown_role_does_not_fail(root):
    job_id = cli.enqueue_task("mathematical_mongoose", "inspect the invariant")
    job = read_job(root, job_id)
    assert job["role"] == "mathematical_mongoose"
```

- [ ] **Step 2: Run the failures**

Run: `python3 -m unittest tests.test_optional_roles tests.test_resource_control tests.test_executor -v`

Expected: FAIL because current `load_role` rejects null, underscores, and unknown labels.

- [ ] **Step 3: Implement context resolution without admission validation**

Use a safe regex only to decide whether a role file may be looked up. Never reject a
job because the regex fails or a file is absent.

```python
SAFE_ROLE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def resolve_role(role: str | None) -> dict:
    base = (cli.ROOT / "roles/_base.md").read_text(encoding="utf-8").strip()
    label = role.strip() if isinstance(role, str) and role.strip() else None
    path = cli.ROOT / "roles" / f"{label}.md" if label and SAFE_ROLE.fullmatch(label) else None
    if path is None or not path.is_file() or path.name.startswith("_") and label != "sole_survivor":
        return {"label": label, "known": False, "context": base,
                "capabilities": ["tool-calling"]}
    return {"label": label, "known": True,
            "context": path.read_text(encoding="utf-8").strip(),
            "capabilities": role_capabilities(label)}
```

Keep `_control-plane.md` nonspawnable. Permit the known infrastructure role
`sole_survivor`; its authority still comes from resource mode and exact job identity,
not its label. Update prompt rendering, identity fallback, model compatibility,
status formatting, and audits to tolerate `role is None`.

- [ ] **Step 4: Run focused and full tests**

Run: `python3 -m unittest tests.test_optional_roles tests.test_resource_control tests.test_executor tests.test_identity tests.test_control_turns -v`

Expected: PASS and no `unknown role` exception.

- [ ] **Step 5: Commit the optional-role boundary**

```bash
git add roles/_base.md ecosystem/roles.py ecosystem/cli.py ecosystem/models.py \
  ecosystem/resource_control.py ecosystem/executor.py ecosystem/control_runtime.py \
  tests/test_optional_roles.py tests/test_resource_control.py tests/test_executor.py
git diff --cached --check
git commit -m "Make agent roles optional context"
```

### Task 3: Idempotent resource-emergency entry

**Files:**
- Modify: `ecosystem/resource_control.py`
- Modify: `config/resource-policy.json`
- Test: `tests/test_resource_control.py`

**Interfaces:**
- Produces: `model_is_live(item: dict) -> bool`
- Produces: `confirmed_threshold(state: dict, snapshot: dict, now_monotonic: float) -> str`
- Produces: `advance_emergency(state: dict, snapshot: dict, reason: str) -> dict`
- Consumes: `time_policy.seconds(..., "resource", ...)`

- [ ] **Step 1: Add reproductions for the live failures**

```python
def test_in_use_emergency_model_is_live():
    health = {"all_models_loaded": [{"model_name": "Qwen3.5-4B-GGUF",
                                      "loaded": True, "backend_alive": True,
                                      "status": "in_use"}]}
    assert resource_control.emergency_model_live(health)


def test_one_non_oom_critical_sample_does_not_enter_emergency(root):
    state = normal_resource_state()
    snapshot = critical_psi_snapshot(oom_kills=state["last_oom_kills"])
    result = tick_with(state, snapshot, monotonic=100.0)
    assert result["mode"] == "normal"
    assert result["threshold_candidate"] == "emergency"


def test_emergency_entry_creates_survivor_before_final_mode(root):
    result = run_real_emergency_transition(root)
    assert result["mode"] == "emergency"
    assert result["emergency_phase"] == "active"
    assert read_job(root, result["sole_survivor_job"])["role"] == "sole_survivor"


def test_retry_resumes_partial_emergency_without_restarting_contact(root):
    state = emergency_state(phase="model_loaded", sole_survivor_job=None)
    with patch_systemctl() as calls:
        result = resource_control.advance_emergency(state, healthy_snapshot(), "retry")
    assert result["sole_survivor_job"]
    assert "agent-telegram.service" not in flattened_units(calls)
```

- [ ] **Step 2: Run the resource tests and preserve the failure output**

Run: `python3 -m unittest tests.test_resource_control -v`

Expected: FAIL on `in_use`, one-sample confirmation, real `sole_survivor`, and contact restart assertions.

- [ ] **Step 3: Implement explicit, resumable phases**

Use phases `recorded`, `clients_stopped`, `models_unloaded`, `model_loaded`,
`survivor_ready`, and `active`. Persist after every verified phase. Treat model
statuses `ready`, `in_use`, and `busy` as live when `loaded` and `backend_alive` are
true. Never restart Telegram or the notifier from the resource loop.

```python
def model_is_live(item: dict) -> bool:
    return (bool(item.get("loaded")) and bool(item.get("backend_alive"))
            and item.get("status") not in {"failed", "unloaded", "stopped"})


def emergency_model_live(health: dict | None = None) -> bool:
    current = health or lemonade_health()
    expected = policy()["emergency"]["chat_model"]
    return any(item.get("model_name") == expected and model_is_live(item)
               for item in current.get("all_models_loaded", []))
```

Use monotonic candidate start times to confirm pressure for five seconds and
non-OOM emergency for ten seconds. A kernel OOM increment remains immediate. Remove
the resource guard's looped restart of contact services; write a visible resource
error record instead.

- [ ] **Step 4: Prove the regression and suite**

Run: `python3 -m unittest tests.test_resource_control tests.test_control_turns tests.test_preemption -v`

Expected: PASS; the partial-transition test invokes preparation exactly once and
never targets `agent-telegram.service`.

Run: `python3 -m unittest discover -s tests -v`

Expected: PASS.

- [ ] **Step 5: Commit resource stabilization**

```bash
git add ecosystem/resource_control.py config/resource-policy.json tests/test_resource_control.py
git diff --cached --check
git commit -m "Make resource emergency recovery resumable"
```

### Task 4: Recover the currently wedged resource guard

**Files:**
- Runtime only: existing user services and `state/resource-control.json`
- Create: `state/incidents/` record through the repaired runtime interface

**Interfaces:**
- Consumes: the tested Task 3 resource transition and current live state
- Produces: one durable recovery incident with before/after evidence

- [ ] **Step 1: Capture bounded pre-recovery facts**

```bash
systemctl --user show agent-telegram.service agent-control-worker.service \
  agent-notifier.service agent-resource-guard.service \
  -p Id -p ActiveState -p SubState -p Result -p NRestarts
jq '{mode,emergency_phase,sole_survivor_job,last_resources}' state/resource-control.json
curl --fail --silent --show-error --max-time 2 http://127.0.0.1:8000/api/v1/health
```

Expected: the current partial phase is recorded without printing credentials or
message content. Stop if Telegram is already inactive; restore that contact path
before touching the resource guard.

- [ ] **Step 2: Exercise one repaired transition before restarting the loop**

Stop only `agent-resource-guard.service`, invoke one bounded foreground
`./scripts/resource-control tick`, and inspect the resulting phase, survivor job,
Lemonade health, and exact systemd targets. The tick must resume the partial
transition idempotently and must not target `agent-telegram.service` or
`agent-notifier.service`. If it fails, leave the guard stopped, keep Telegram
online, write a local critical incident, and return to systematic debugging.

- [ ] **Step 3: Restart and observe the existing guard**

Restart `agent-resource-guard.service`; for 30 seconds sample its unit state,
resource phase, Lemonade model liveness, Telegram process identity, and journal.
Acceptance requires a stable guard, no repeated contact-service operation, a
non-null survivor for any remaining emergency, and an unchanged Telegram process
identity. Record the recovery incident as resolved only after these postconditions.

- [ ] **Step 4: Re-run the complete suite**

Run: `python3 -m unittest discover -s tests -v`

Expected: PASS after the live state reconciliation.

### Task 5: Reconcile documentation without concealing history

**Files:**
- Modify: `docs/status.md`
- Modify: `docs/operations.md`
- Modify: `agent_notes/0005-model-residency-concurrency.md`

**Interfaces:**
- Consumes: captured before/after systemd, resource, Lemonade, job, and control-turn state
- Produces: an evidence-backed operator procedure

- [ ] **Step 1: Record the pre-fix evidence commands**

```bash
systemctl --user show agent-telegram.service agent-control-worker.service \
  agent-notifier.service agent-resource-guard.service \
  -p Id -p ActiveState -p SubState -p Result -p ActiveEnterTimestamp
jq '{mode,emergency_phase,sole_survivor_job,last_resources}' state/resource-control.json
python3 -m unittest discover -s tests -v
```

Expected: service facts and current latch are captured locally without editing
append-only logs.

- [ ] **Step 2: Update status and operations with exact limitations**

Document the 2026-09-04 role-validator/busy-model restart storm, the passing-test
gap, the corrected phase model, and the fact that permanent survival services are
not deployed until Plan 5. Remove any claim that current health is proven merely by
unit status.

- [ ] **Step 3: Run documentation checks**

Run: `git diff --check -- docs/status.md docs/operations.md agent_notes/0005-model-residency-concurrency.md`

Expected: no whitespace errors and no credentials or conversation content.

- [ ] **Step 4: Commit only the reconciliation**

```bash
git add docs/status.md docs/operations.md agent_notes/0005-model-residency-concurrency.md
git commit -m "Document the resource recovery failure chain"
```
