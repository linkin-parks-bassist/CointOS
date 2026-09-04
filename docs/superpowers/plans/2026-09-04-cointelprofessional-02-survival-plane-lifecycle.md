# Cointelprofessional Permanent Survival Plane Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a model-independent, root-installed Telegram gateway and guardian which execute durable `RESTART` and `RESET` while remaining online.

**Architecture:** Root-owned installed code contains a minimal gateway running as a dedicated unprivileged user and a non-agentic guardian running as root. The gateway authenticates Telegram and sends only typed command enums over a peer-credential-checked Unix socket; the guardian reduces durable lifecycle records and controls an immutable unit/cgroup allowlist.

**Tech Stack:** Python 3 standard library, Unix domain sockets, `SO_PEERCRED`, filesystem spools, systemd system/user units, cgroups, and `unittest`.

**Spec:** `docs/superpowers/specs/2026-09-04-cointelprofessional-survival-control-design.md`

## Global Constraints

- The gateway and guardian are never members of the destructible unit list.
- Telegram secrets use systemd credentials and never enter Git or test output.
- Model code and model-generated code never run as root.
- The guardian accepts exactly `restart` and `reset`; no arbitrary unit, path, model, shell, or argument fields exist.
- The ordinary David account cannot authenticate to the lifecycle socket.
- Durable transitions precede side effects and resume idempotently after process death.
- This plan creates installable artifacts but does not install or enable them.
- New function-style test modules end with the repository's existing `load_tests`
  collector so `unittest` discovers every `test_*` function.

---

### Task 1: Versioned survival records and command protocol

**Files:**
- Create: `survival/__init__.py`
- Create: `survival/records.py`
- Create: `survival/protocol.py`
- Create: `tests/test_survival_records.py`
- Create: `tests/test_survival_protocol.py`

**Interfaces:**
- Produces: `atomic_json(path: Path, value: dict) -> None`
- Produces: `append_event(path: Path, event: dict) -> None`
- Produces: `accept_update(root: Path, update: dict, allowed_user_ids: set[int]) -> dict`
- Produces: `parse_literal_command(text: str) -> str | None`
- Produces: `encode_command(command: dict) -> bytes`
- Produces: `decode_command(payload: bytes) -> dict`

- [ ] **Step 1: Write exact-command, authorization, and idempotency tests**

```python
def test_only_exact_uppercase_command_is_literal():
    assert protocol.parse_literal_command("RESTART") == "restart"
    assert protocol.parse_literal_command("RESET") == "reset"
    for text in ("restart", " RESTART", "RESTART ", "RESTART now", "/RESTART"):
        assert protocol.parse_literal_command(text) is None


@with_survival_root
def test_replayed_update_keeps_one_record(root):
    first = records.accept_update(root, telegram_update(91, 42, "RESTART"), {42})
    second = records.accept_update(root, telegram_update(91, 42, "RESTART"), {42})
    assert first["id"] == second["id"]
    assert len(list((root / "commands").glob("*.json"))) == 1


def test_protocol_rejects_extra_fields():
    payload = b'{"schema_version":1,"command":"restart","unit":"ssh.service"}'
    with unittest.TestCase().assertRaisesRegex(ValueError, "fields"):
        protocol.decode_command(payload)
```

`with_survival_root` is a function decorator in the test module which creates a
`tempfile.TemporaryDirectory`, passes its `Path` to the test, and cleans it up; it
contains no mutable object wrapper.

- [ ] **Step 2: Run the protocol tests**

Run: `python3 -m unittest tests.test_survival_records tests.test_survival_protocol -v`

Expected: FAIL because `survival.records` and `survival.protocol` do not exist.

- [ ] **Step 3: Implement strict records and protocol**

```python
COMMAND_FIELDS = {"schema_version", "request_id", "telegram_update_id",
                  "telegram_user_id", "command", "received_at"}
COMMANDS = {"restart", "reset"}


def parse_literal_command(text: str) -> str | None:
    return {"RESTART": "restart", "RESET": "reset"}.get(text)


def decode_command(payload: bytes) -> dict:
    value = json.loads(payload)
    if not isinstance(value, dict) or set(value) != COMMAND_FIELDS:
        raise ValueError("invalid command fields")
    if value["schema_version"] != 1 or value["command"] not in COMMANDS:
        raise ValueError("invalid command value")
    return value
```

Use exclusive creation keyed by Telegram update ID. An existing record must match
the original chat/user/text identity or fail explicitly.

- [ ] **Step 4: Run focused tests and commit**

Run: `python3 -m unittest tests.test_survival_records tests.test_survival_protocol -v`

Expected: PASS.

```bash
git add survival/__init__.py survival/records.py survival/protocol.py \
  tests/test_survival_records.py tests/test_survival_protocol.py
git commit -m "Add typed survival-plane protocol"
```

### Task 2: Pure lifecycle reducer

**Files:**
- Create: `survival/lifecycle.py`
- Create: `tests/test_survival_lifecycle.py`

**Interfaces:**
- Consumes: decoded command records from Task 1
- Produces: `new_lifecycle(command: dict, previous_pause: bool) -> dict`
- Produces: `reduce_lifecycle(state: dict, event: dict) -> tuple[dict, list[dict]]`
- Produces command effects with `kind` in `notify`, `close_admission`, `checkpoint`, `stop_units`, `kill_units`, `stop_lemonade`, `start_lemonade`, `start_units`, `reconcile`, `verify`, `resume`, or `finish`

- [ ] **Step 1: Write full restart/reset transition-table tests**

```python
def test_restart_requests_checkpoint_after_acknowledgement():
    state = lifecycle.new_lifecycle(command_record("restart"), previous_pause=False)
    state, effects = lifecycle.reduce_lifecycle(state, {"kind": "ack_delivered"})
    assert state["phase"] == "admission_closed"
    assert [effect["kind"] for effect in effects] == ["close_admission", "checkpoint"]


def test_reset_skips_checkpoint():
    state = lifecycle.new_lifecycle(command_record("reset"), previous_pause=True)
    state, effects = lifecycle.reduce_lifecycle(state, {"kind": "ack_delivered"})
    assert [effect["kind"] for effect in effects] == ["close_admission", "kill_units"]


def test_replayed_effect_completion_is_idempotent():
    state = lifecycle_state(phase="backend_stopped")
    event = {"kind": "backend_stopped",
             "idempotency_key": "request-1:backend-stopped"}
    first = lifecycle.reduce_lifecycle(state, event)
    second = lifecycle.reduce_lifecycle(first[0], event)
    assert second == (first[0], [])
```

- [ ] **Step 2: Run and observe missing reducer failure**

Run: `python3 -m unittest tests.test_survival_lifecycle -v`

Expected: FAIL because `survival.lifecycle` does not exist.

- [ ] **Step 3: Implement the reducer as tables and functions**

```python
PHASES = ("accepted", "acknowledged", "admission_closed", "checkpointing",
          "stopping", "backend_stopped", "starting", "reconciling",
          "verifying", "resumed", "completed", "blocked", "failed")


def reduce_lifecycle(state: dict, event: dict) -> tuple[dict, list[dict]]:
    key = (state["command"], state["phase"], event["kind"])
    transition = TRANSITIONS.get(key)
    if transition is None:
        if event.get("idempotency_key") in state.get("applied_events", []):
            return state, []
        raise ValueError(f"illegal lifecycle transition {key!r}")
    return apply_transition(state, event, transition)
```

Every effect carries `request_id`, `phase`, and an idempotency key. Preserve the
pre-command pause state and restore it only after verification.

- [ ] **Step 4: Run reducer tests and commit**

Run: `python3 -m unittest tests.test_survival_lifecycle -v`

Expected: PASS for every legal and illegal transition.

```bash
git add survival/lifecycle.py tests/test_survival_lifecycle.py
git commit -m "Define durable restart and reset transitions"
```

### Task 3: Permanent gateway transport

**Files:**
- Create: `survival/telegram_api.py`
- Create: `survival/gateway.py`
- Create: `scripts/cointelprofessional-gateway`
- Create: `tests/test_survival_gateway.py`

**Interfaces:**
- Consumes: Task 1 record/protocol functions and accepted timing projection
- Produces: `handle_update(update: dict, allowed: set[int], store: Path, send: Callable, send_command: Callable) -> dict`
- Produces: `drain_critical_outbox(store: Path, send: Callable) -> int`
- Produces: `mark_gateway_heartbeat(store: Path, monotonic_now: float) -> None`

- [ ] **Step 1: Write gateway tests with no network or model**

```python
def test_command_is_acknowledged_and_sent_to_guardian():
    sent, commands = [], []
    result = gateway.handle_update(telegram_update(7, 42, "RESET"), {42}, root,
                                   send=lambda chat, text: sent.append((chat, text)),
                                   send_command=commands.append)
    assert result["kind"] == "command"
    assert commands[0]["command"] == "reset"
    assert sent == [(42, "Reset accepted. I am staying online while the agent system restarts.")]


def test_ordinary_message_is_spooled_without_model_call():
    result = gateway.handle_update(telegram_update(8, 42, "how is scheduler?"), {42}, root,
                                   send=fail_if_called, send_command=fail_if_called)
    assert result["kind"] == "ordinary"
    assert (root / "inbox/telegram-8.json").exists()


def test_due_message_gets_honest_degraded_reply():
    write_old_pending_message(root, update_id=8)
    assert gateway.send_due_degraded_responses(root, send=capture_send, now=10.0) == 1
```

- [ ] **Step 2: Run and confirm missing gateway failure**

Run: `python3 -m unittest tests.test_survival_gateway -v`

Expected: FAIL because the survival gateway is absent.

- [ ] **Step 3: Implement functional polling/sending workers**

The entry point creates supervised child processes with `os.fork`: one blocking
long-poll worker and one critical-outbox/deadline worker. The parent reaps and
restarts either child. No threads or stateful classes are introduced.

```python
def handle_update(update, allowed, store, send, send_command):
    accepted = records.accept_update(store, update, allowed)
    command = protocol.parse_literal_command(accepted["text"])
    if command is None:
        records.enqueue_inbound(store, accepted)
        return {"kind": "ordinary", "id": accepted["id"]}
    request = protocol.command_record(accepted, command)
    send_command(request)
    send(accepted["chat_id"], acknowledgement(command))
    records.mark_acknowledged(store, accepted["id"])
    return {"kind": "command", "id": accepted["id"]}
```

Denied users create only a minimal denial audit without message text. Egress
distinguishes `ready`, `sending`, `delivered`, and `delivery_unknown`.

- [ ] **Step 4: Run gateway/protocol tests and commit**

Run: `python3 -m unittest tests.test_survival_gateway tests.test_survival_protocol tests.test_survival_records -v`

Expected: PASS.

```bash
git add survival/telegram_api.py survival/gateway.py scripts/cointelprofessional-gateway \
  tests/test_survival_gateway.py
git commit -m "Build permanent Telegram gateway"
```

### Task 4: Guardian effects and peer authentication

**Files:**
- Create: `survival/system_control.py`
- Create: `survival/guardian.py`
- Create: `scripts/cointelprofessional-guardian`
- Create: `tests/test_survival_guardian.py`
- Create: `tests/test_system_control.py`

**Interfaces:**
- Consumes: Task 2 reducer effects
- Produces: `peer_uid(connection: socket.socket) -> int`
- Produces: `authorize_peer(uid: int, gateway_uid: int) -> None`
- Produces: `execute_effect(effect: dict, adapters: dict, policy: dict) -> dict`
- Produces: `advance_request(path: Path, adapters: dict, policy: dict) -> dict`
- Produces: `system_unit(action: str, unit: str) -> dict` and `user_unit(action: str, unit: str) -> dict`

- [ ] **Step 1: Write peer, allowlist, kill-order, and postcondition tests**

```python
def test_only_gateway_uid_can_submit_lifecycle_request():
    guardian.authorize_peer(991, gateway_uid=991)
    with unittest.TestCase().assertRaises(PermissionError):
        guardian.authorize_peer(1000, gateway_uid=991)


def test_gateway_and_guardian_cannot_enter_destructible_set():
    with unittest.TestCase().assertRaisesRegex(ValueError, "survival"):
        system_control.validate_destructible_units(
            ["cointelprofessional-gateway.service"])


def test_reset_kills_user_units_before_lemonade_start():
    events = run_effects_for("reset", fake_adapters())
    assert events.index("kill_user_units") < events.index("stop_lemonade")
    assert events.index("stop_lemonade") < events.index("start_lemonade")


def test_zero_exit_without_postcondition_is_failure():
    result = system_control.checked_action(run=lambda *_: completed(0),
                                           verify=lambda: False)
    assert result["ok"] is False
```

- [ ] **Step 2: Run guardian tests**

Run: `python3 -m unittest tests.test_survival_guardian tests.test_system_control -v`

Expected: FAIL because guardian adapters do not exist.

- [ ] **Step 3: Implement the immutable control boundary**

```python
SURVIVAL_UNITS = {
    "cointelprofessional-gateway.service",
    "cointelprofessional-guardian.service",
    "cointelprofessional-guardian.socket",
}
DESTRUCTIBLE_SYSTEM_UNITS = {"lemond.service"}
DESTRUCTIBLE_USER_UNITS = {
    "agent-models.service", "agent-inference-arbiter.service",
    "agent-fast-control.service", "agent-control-worker.service",
    "agent-notifier.service", "agent-ecosystem.service",
    "agent-ecosystem.path", "agent-ecosystem.timer", "agent-watchdog.service",
    "agent-watchdog.timer", "agent-resource-guard.service",
}
```

The user-manager adapter uses an explicit configured UID and
`systemctl --user --machine=david@.host`; tests assert the exact argv. Every action
captures bounded output and verifies active/inactive state plus cgroup emptiness.
`advance_request` writes the next durable phase before executing its effect and
records the verified result before reducing again.

- [ ] **Step 4: Run lifecycle and guardian tests and commit**

Run: `python3 -m unittest tests.test_survival_lifecycle tests.test_survival_guardian tests.test_system_control -v`

Expected: PASS with no real systemd calls.

```bash
git add survival/system_control.py survival/guardian.py \
  scripts/cointelprofessional-guardian tests/test_survival_guardian.py \
  tests/test_system_control.py
git commit -m "Implement typed lifecycle guardian"
```

### Task 5: Root-owned units and offline process integration

**Files:**
- Create: `services/system/cointelprofessional-survival.slice`
- Create: `services/system/cointelprofessional-gateway.service`
- Create: `services/system/cointelprofessional-guardian.socket`
- Create: `services/system/cointelprofessional-guardian.service`
- Create: `survival/systemd_notify.py`
- Create: `scripts/install-survival-plane`
- Create: `tests/integration/test_survival_processes.py`
- Modify: `docs/operations.md`

**Interfaces:**
- Consumes: entry points from Tasks 3 and 4
- Produces: root-owned installation under `/usr/local/lib/cointelprofessional-survival/`
- Produces: dedicated `cointelprofessional` user, private command socket group, and shared `agent_ecosystem_io` spool group
- Produces: `notify_systemd(message: str, socket_path: str | None = None) -> None`

- [ ] **Step 1: Write static and disposable-process failures**

```python
def test_survival_units_are_not_stoppable_by_guardian():
    text = Path("services/system/cointelprofessional-guardian.service").read_text()
    assert "cointelprofessional-gateway.service" not in destructible_units_from(text)


def test_gateway_supervisor_restarts_dead_poll_child():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        process = start_test_gateway(root, poll_child_exit_after=1)
        try:
            first, second = wait_for_two_child_pids(root)
            assert first != second
        finally:
            stop_process(process)
```

- [ ] **Step 2: Run static verification before unit creation**

Run: `python3 -m unittest tests.integration.test_survival_processes -v`

Expected: FAIL because the units and entry points are absent.

- [ ] **Step 3: Add hardened units and an idempotent installer**

The gateway unit must include `Type=notify`, `NotifyAccess=main`,
`User=cointelprofessional`,
`Restart=always`, `RestartSec=250ms`, `StartLimitIntervalSec=0`,
`WatchdogSec=10s`, `Slice=cointelprofessional-survival.slice`, and
`LoadCredential=telegram_bot_token:/etc/cointelprofessional/telegram_bot_token`.
The guardian is root-owned, enabled at `multi-user.target`, and also accepts
socket activation. It has its own `Restart=always` and `WatchdogSec=10s`, and is
restricted to the survival store, systemd control, and required read-only
repository/config paths.

`survival.systemd_notify` sends `READY=1` after initialization and `WATCHDOG=1` on
each healthy loop through the datagram path in `NOTIFY_SOCKET`. Gateway and guardian
tests use a temporary Unix datagram receiver and prove notifications stop when the
application loop is deliberately wedged.

The installer accepts no credentials on argv, creates directories with explicit
owners/modes, copies a root-owned code snapshot, verifies units with
`systemd-analyze verify`, and defaults to install-only. `--enable` is implemented but
is not used until Plan 5.

- [ ] **Step 4: Run offline process and unit verification**

Run: `python3 -m unittest tests.integration.test_survival_processes -v`

Expected: PASS without root or network.

Run: `systemd-analyze verify services/system/cointelprofessional-gateway.service services/system/cointelprofessional-guardian.socket services/system/cointelprofessional-guardian.service`

Expected: exit 0.

- [ ] **Step 5: Commit installable survival plane**

```bash
git add services/system survival/systemd_notify.py scripts/install-survival-plane \
  tests/integration/test_survival_processes.py docs/operations.md
git diff --cached --check
git commit -m "Package permanent Cointelprofessional survival services"
```
