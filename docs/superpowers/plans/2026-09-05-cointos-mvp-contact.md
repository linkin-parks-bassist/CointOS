# CointOS MVP Contact Plane Implementation Plan
> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
**Goal:** Replace the mixed Telegram/deep-control route with one responsive, resource-reserved, durable respond-or-dispatch path whose ordinary egress is owned by the permanent gateway.
**Architecture:** The gateway remains the only Telegram fingertip and writes authenticated inbound records. A user-owned worker reduces each record through the existing control-turn identity into one structured response or dispatch using R4 inference; it publishes immutable ordinary reply intents which the gateway authenticates against inbound identity and delivers separately from root-owned critical messages.
**Tech Stack:** Python 3 standard library, atomic JSON, `fcntl`, filesystem spools, systemd system/user units, R1 worker leases, R4 inference requests, existing survival guardian/reducer, and `unittest`.
**Spec:** `docs/superpowers/specs/2026-09-05-cointos-mvp-design.md`
## Global constraints
- Personal CointOS only; professional/customer material is outside scope.
- Use functions and plain data; no classes, actors, generic bus, or second task database.
- Preserve exact `RESTART`/`RESET`, the survival reducer/guardian, central timing, protected gateway identity, append-only events, and critical-outbox ownership unless a focused defect proves otherwise.
- After cutover the permanent gateway is the sole poller and Telegram egress adapter. `agent-telegram.service` and unconditional `agent-control-worker.service` are inactive rollback artifacts, never concurrent semantic routes.
- Reuse `control_turns` identity/delivery and `conversation` source-id idempotency, but convert once to canonical `respond|dispatch`; no active `deep_state` compatibility path remains.
- Every inference uses R4 `inference.request(request, root, clock) -> dict`. The `front` class owns its reserved physical sequence; direct HTTP is forbidden.
- R4 owns a configurable local inference endpoint; preserve `http://127.0.0.1:13305` only as the historical initial value, never a new hard-coded health/request port.
- Scheduler rank is trusted validated policy: Sole Survivor > Coin > small health inspectors > big health inspectors > other roles. Rank never lets the survivor or an inspector consume Coin's exclusive front sequence; capacity reservation and relative priority are distinct facts, and code roles cannot switch them.
- One dispatch creates at most one durable job. Role is nullable advice; `task_contract` owns authority.
- User-written ordinary intents are immutable and contain no trusted destination. The gateway derives chat/user/update identity from authenticated inbound state.
- Root-written `outbox/critical` remains separately owned; ordinary code cannot create, rename, mutate, or acknowledge it.
- Persist send intent before Telegram; delivery uncertainty is terminal for automatic replay.
- R1 owns drain/smoke exclusion. R7 pressure, emergency, lifecycle, and operator pauses remain stronger.
- Local microtasks take 2-5 minutes. Sol work uses `gpt-5.6-sol`, medium reasoning, isolated context, and 15-25 minute task budgets.
- Function tests end in `load_tests` with `unittest.FunctionTestCase`; run via `python3 -m unittest discover -s tests -p 'test_name.py' -v`.
- Tests never use live Telegram, models, systemd, accounts, credentials, installation, or runtime state.
- `scripts/install-survival-plane --enable` currently fails to stop the old poller; it is not a cutover transaction.
- `COINTELPROFESSIONAL_INSTALL_ROOT` is not hermetic because account operations remain unconditional. Never invoke the installer in host tests; use injected account/systemd fingertips or a disposable container.
- C5 may run when C1-C4 and R1-R4/R7 prerequisites pass; exhaustive health/autonomy and hostile-spool/crash review do not gate early contact.
## File ownership and dependency map
- `ecosystem/control_turns.py`: sole contact identity and state reducer.
- `ecosystem/fast_control.py`, `ecosystem/contact_status.py`: strict decision and factual input.
- `ecosystem/contact_worker.py`: inbound reduction, dispatch, reply publication.
- `survival/ordinary_outbox.py`, `survival/gateway.py`: intent linkage and sole egress.
- `survival/cutover.py`: fixed reversible unit operations over injected fingertips.
- `ecosystem/contact_acceptance.py`: R1/R7-gated evidence reducer, never a sender.
- A1 precedes C1. C1 precedes C2/C3. R4 precedes C2. C1-C3 plus R1/R7 precede C4. C4 plus R1-R4/R7 acceptance precedes C5.
---
### Task C1: Canonical turn and respond-or-dispatch result
**Owner:** Sol 5.6 medium owns schema/transitions. Local workers may take one isolated validator or fixture microtask; no concurrent `control_turns.py` writers.
**Files:**
- Modify: `ecosystem/control_turns.py`
- Modify: `ecosystem/cli.py`
- Modify: `ecosystem/conversation.py`
- Create: `tests/test_contact_turns.py`
- Modify: `tests/test_control_turns.py`
**Interfaces:**
- Preserve: `accept(update_id: int, chat_id: int, user_id: int, message: str) -> tuple[dict, bool]`
- Produce: `claim_decision(identifier: str, owner_identity: str, now: str) -> dict | None`
- Produce: `complete_decision(identifier: str, decision: dict, now: str) -> dict`
- Produce: `dispatch_once(identifier: str, task_contract: dict, enqueue: Callable[..., str], now: str) -> dict`
- Produce: `link_reply(identifier: str, reply_id: str, kind: str, now: str) -> dict`
- Produce: `convert_legacy_turn(value: dict) -> dict`
- Change: `cli.enqueue_task(..., idempotency_key: str | None = None, task_contract: dict | None = None) -> str`; C1 supplies the shared validated task contract, never role-derived authority.
- Exact decision fields: `reply`, `decision`, `task`, `role`, `constraints`.
- States: `decision_state=pending|claimed|completed|failed`, `dispatch_state=none|intended|enqueued`, `reply_state=pending|published|delivered|delivery_unknown`.
- [ ] **Step 1: Add a self-contained replay test**
```python
import tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from ecosystem import cli, control_turns
def test_dispatch_replay_enqueues_once():
    with tempfile.TemporaryDirectory() as temporary, patch.object(cli, "ROOT", Path(temporary)):
        turn, created = control_turns.accept(41, 7, 7, "inspect scheduler")
        assert created
        control_turns.claim_decision(turn["id"], "boot:12:3", "2026-09-05T00:00:00+00:00")
        control_turns.complete_decision(turn["id"], {
            "reply": "I’ll inspect it.", "decision": "dispatch",
            "task": "Inspect the scheduler stall", "role": None, "constraints": [],
        }, "2026-09-05T00:00:01+00:00")
        calls = []
        enqueue = lambda **value: calls.append(value) or "job-9"
        contract = {"objective": "Inspect the scheduler stall", "scope": {"workspace": str(Path(temporary)), "read_paths": [], "write_paths": []}, "authority_profile": "contact_requested", "acceptance": [], "budget": {"run_seconds": 300, "task_seconds": 900, "maximum_attempts": 1, "maximum_output_bytes": 65536, "maximum_evidence_items": 20, "maximum_children": 0}, "source_key": "telegram-41:dispatch", "parent_job_id": None, "stop_condition": "Report the bounded finding"}
        first = control_turns.dispatch_once(turn["id"], contract, enqueue, "2026-09-05T00:00:02+00:00")
        second = control_turns.dispatch_once(turn["id"], contract, enqueue, "2026-09-05T00:00:03+00:00")
    assert first["dispatch_job_id"] == second["dispatch_job_id"] == "job-9"
    assert len(calls) == 1 and calls[0]["idempotency_key"] == "telegram-41:dispatch"
def load_tests(loader, tests, pattern):
    return unittest.TestSuite([unittest.FunctionTestCase(test_dispatch_replay_enqueues_once)])
```
- [ ] **Step 2: Prove the interface is missing**
Run: `python3 -m unittest discover -s tests -p 'test_contact_turns.py' -v`
Expected: FAIL at `claim_decision`.
- [ ] **Step 3: Implement one reducer and bounded conversion**
```python
def dispatch_once(identifier, task_contract, enqueue, now):
    record = reserve_dispatch_intent(identifier, task_contract, now)
    if record["decision"]["decision"] != "dispatch" or record["dispatch_state"] == "enqueued":
        return record
    key = record["dispatch_idempotency_key"]
    job_id = enqueue(role=record["decision"]["role"], task=record["decision"]["task"],
                     source=f"telegram:{identifier}", idempotency_key=key,
                     task_contract=record["task_contract"])
    return _mutate(identifier, lambda value: value.update(
        dispatch_state="enqueued", dispatch_job_id=job_id, dispatched_at=now))
```
`convert_legacy_turn` accepts only the exact prior schema. Terminal history converts;
nonterminal legacy turns are previewed blockers and drain before conversion. Remove
reservation/deep-worker/disaster consumers at cutover; do not retain dual reads.
`reserve_dispatch_intent` persists the exact contract/key under the turn lock before
enqueue. A1's sole enqueue owner atomically creates-or-returns the job under its lock;
concurrent/restarted callers may repeat that idempotent call, never check then enqueue.
- [ ] **Step 4: Verify and commit**
Run: `python3 -m unittest discover -s tests -p 'test_contact_turns.py' -v`
Run: `python3 -m unittest discover -s tests -p 'test_control_turns.py' -v`
```bash
git add ecosystem/control_turns.py ecosystem/cli.py ecosystem/conversation.py tests/test_contact_turns.py tests/test_control_turns.py
git diff --cached --check && git commit -m "Define canonical CointOS contact turns"
```
**Acceptance:** One update identity has one decision, at most one task, and explicit reply state; conversion refuses active legacy work.
**Stop:** If enqueue cannot accept an idempotency key/task contract without changing R5 ownership, hand that mismatch to Astra rather than add a queue.
### Task C2: Bounded fast control through R4
**Owner:** Sol 5.6 medium owns prompt/schema/status judgment; local workers may add one validator or prompt-capture microtask.
**Files:**
- Create: `ecosystem/fast_control.py`
- Create: `ecosystem/contact_status.py`
- Modify: `config/model-policy.json`
- Create: `tests/test_fast_control.py`
- Create: `tests/test_contact_status.py`
**Interfaces:**
- Consume: `inference.request(request: dict, root: Path, clock: Callable[[], float]) -> dict`
- Produce: `contact_status(read_status: Callable[[], dict], now: Callable[[], float]) -> dict`
- Produce: `decision_prompt(message: str, history: list[dict], status: dict) -> list[dict]`
- Produce: `validate_decision(value: dict) -> dict`
- Produce: `decide(request_id: str, message: str, history: list[dict], status: dict, root: Path, clock: Callable[[], float], infer: Callable = inference.request) -> dict`
- [ ] **Step 1: Test reserved factual response**
```python
import tempfile, unittest
from pathlib import Path
from ecosystem import fast_control
def test_status_uses_front_request():
    captured = {}
    def infer(request, root, clock):
        captured.update(request)
        return {"content": '{"reply":"scheduler is healthy","decision":"respond","task":null,"role":null,"constraints":[]}'}
    with tempfile.TemporaryDirectory() as temporary:
        result = fast_control.decide("telegram-52", "scheduler status?", [],
            {"scheduler": {"health": "healthy", "observed_at": 10.0}},
            Path(temporary), lambda: 11.0, infer=infer)
    assert result["decision"] == "respond"
    assert captured["workload_class"] == "front"
    assert captured["request_id"] == "telegram-52:decision"
    assert "scheduler" in captured["messages"][-1]["content"]
def load_tests(loader, tests, pattern):
    return unittest.TestSuite([unittest.FunctionTestCase(test_status_uses_front_request)])
```
- [ ] **Step 2: Prove absence, then implement strict validation**
Run: `python3 -m unittest discover -s tests -p 'test_fast_control.py' -v`
Expected: FAIL because `ecosystem.fast_control` is absent.
```python
FIELDS = {"reply", "decision", "task", "role", "constraints"}
def validate_decision(value):
    if type(value) is not dict or set(value) != FIELDS or value["decision"] not in {"respond", "dispatch"}:
        raise ValueError("invalid contact decision")
    if type(value["reply"]) is not str or not value["reply"].strip():
        raise ValueError("empty contact reply")
    if value["decision"] == "dispatch" and (type(value["task"]) is not str or not value["task"].strip()):
        raise ValueError("dispatch requires task")
    if value["decision"] == "respond" and value["task"] is not None:
        raise ValueError("respond cannot create work")
    return value
```
Prompt rules: answer ordinary conversation; dispatch capable sustained work; include
only typed status and its age; never invent current facts/actions; allow nullable
role; prohibit generic opt-in tails. Invalid/timeout leaves the turn retryable until
gateway degraded deadline and never bypasses R4.
The model may describe a needed check without claiming it ran; it must not deny Coin's
known capabilities merely because this bounded decision call lacks the relevant tool.
`contact_status` is only a thin bounded adapter over the authoritative status projection (H4 when installed, existing factual readers before it); it adds age/size bounds but owns no subsystem schema, persistence, health reduction, or mirror.
- [ ] **Step 3: Verify R4, status, and decisions; commit**
Run: `python3 -m unittest discover -s tests -p 'test_fast_control.py' -v`
Run: `python3 -m unittest discover -s tests -p 'test_contact_status.py' -v`
Run: `python3 -m unittest discover -s tests -p 'test_inference*.py' -v`
```bash
git add ecosystem/fast_control.py ecosystem/contact_status.py config/model-policy.json tests/test_fast_control.py tests/test_contact_status.py
git diff --cached --check && git commit -m "Add reserved structured contact decisions"
```
**Acceptance:** Coin answers ordinary/status turns from bounded facts and dispatches real tasks while R4 owns the front sequence.
**Stop:** If R4 cannot prove the exclusive sequence or status requires mirrored state, repair that owner rather than weaken the prompt.
### Task C3: Inbox worker and gateway-owned ordinary egress
**Owner:** Sol 5.6 medium owns crash/delivery ordering; local workers may add isolated schema/replay tests.
**Files:**
- Create: `ecosystem/contact_worker.py`, `scripts/contact-worker`
- Create: `services/systemd/agent-contact-worker.service`
- Create: `survival/ordinary_outbox.py`
- Modify: `survival/telegram_api.py`, `survival/gateway.py`, `ecosystem/notifier.py`
- Create: `tests/test_contact_worker.py`, `tests/test_ordinary_outbox.py`
- Modify: `tests/test_survival_gateway.py`, `tests/test_notifier.py`
**Interfaces:**
- Produce: `ordinary_outbox.publish(root: Path, inbound: dict, kind: str, text: str, source_key: str, now: str) -> Path`
- Produce: `ordinary_outbox.validate_link(store: Path, intent: dict) -> tuple[dict, dict]`
- Produce: `process_inbox(path: Path, ecosystem_root: Path, survival_root: Path, infer: Callable, status: Callable, enqueue: Callable, clock: Callable) -> dict`
- Produce: `drain_ordinary_outbox(store: Path, send: Callable[[int, str], object], now: Callable[[], float]) -> int`
- Preserve: `drain_critical_outbox(store: Path, send: Callable) -> int`
- Intent fields: exact `schema_version`, `id`, `inbound_id`, `kind`, `text`, `source_key`, `created_at`; kind is `decision|task_result`.
- [ ] **Step 1: Test normal/fallback race and replay**
```python
import tempfile, unittest
from pathlib import Path
from survival import gateway, ordinary_outbox, telegram_api
def test_initial_reply_wins_once():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        accepted = {"schema_version": 1, "id": "telegram-8", "telegram_update_id": 8,
            "telegram_user_id": 7, "chat_id": 7, "text": "hello",
            "received_at": "2026-09-05T00:00:00+00:00"}
        telegram_api.store_inbound(root, accepted, 1.0, 2.0, boot_id="boot-a")
        ordinary_outbox.publish(root, accepted, "decision", "hello back",
                                "telegram-8:decision", "2026-09-05T00:00:01+00:00")
        sent = []
        send = lambda chat, text: sent.append((chat, text))
        gateway.drain_ordinary_outbox(root, send, lambda: 3.0)
        gateway.send_due_degraded_responses(root, send, 3.0, current_boot_id="boot-a")
        gateway.drain_ordinary_outbox(root, send, lambda: 4.0)
    assert sent == [(7, "hello back")]
def test_degraded_notice_does_not_suppress_later_decision():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        accepted = {"schema_version": 1, "id": "telegram-9", "telegram_update_id": 9,
            "telegram_user_id": 7, "chat_id": 7, "text": "status?", "received_at": "2026-09-05T00:00:00+00:00"}
        telegram_api.store_inbound(root, accepted, 1.0, 2.0, boot_id="boot-a")
        sent = []
        def send(chat, text):
            sent.append((chat, text))
            return False if len(sent) == 1 else None
        gateway.send_due_degraded_responses(root, send, 3.0, current_boot_id="boot-a")
        ordinary_outbox.publish(root, accepted, "decision", "the scheduler is healthy",
                                "telegram-9:decision", "2026-09-05T00:00:04+00:00")
        gateway.drain_ordinary_outbox(root, send, lambda: 4.0)
        gateway.drain_ordinary_outbox(root, send, lambda: 5.0)
    assert [text for _chat, text in sent] == [gateway.DEGRADED_REPLY, "the scheduler is healthy"]
def load_tests(loader, tests, pattern):
    return unittest.TestSuite([unittest.FunctionTestCase(test_initial_reply_wins_once),
        unittest.FunctionTestCase(test_degraded_notice_does_not_suppress_later_decision)])
```
- [ ] **Step 2: Prove absence, then implement one send authority**
Run: `python3 -m unittest discover -s tests -p 'test_ordinary_outbox.py' -v`
Expected: FAIL because `survival.ordinary_outbox` is absent.
```python
def validate_link(store, intent):
    inbound = telegram_api.read_inbox_entry(Path(store) / "inbox" / f"{intent['inbound_id']}.json")
    if intent["id"].split(":", 1)[0] != inbound["id"]:
        raise ValueError("ordinary reply identity mismatch")
    return inbound, intent
```
Publish exclusively and never mutate intents. The bounded degraded notice and the
substantive decision have separate identities (`telegram-N:degraded-notice` and
`telegram-N:decision`) and delivery records under one per-inbound `fcntl` lock. If a
decision intent/attempt exists first, suppress an unsent notice. If the notice was
sent or its delivery is unknown, allow exactly one later decision attempt; notice
state never marks the substantive turn complete. Crash after either `sending` becomes
unknown only for that identity, so neither identity replays. Gateway copies only the
decision's terminal observation to the inbox substantive acknowledgement. Task results
have further distinct linked identities. `contact_worker` validates inbox, drives C1/C2,
dispatches once, and publishes. `notifier` publishes `task_result`, never Telegram.
Critical paths and ownership remain unchanged.
Deduplicate only by immutable semantic source/message identity; never use fuzzy/normalized reply text to hide transitions or collapse decision/result.
- [ ] **Step 3: Verify all egress paths; commit**
Run: `python3 -m unittest discover -s tests -p 'test_contact_worker.py' -v`
Run: `python3 -m unittest discover -s tests -p 'test_ordinary_outbox.py' -v`
Run: `python3 -m unittest discover -s tests -p 'test_survival_gateway.py' -v`
Run: `python3 -m unittest discover -s tests -p 'test_notifier.py' -v`
```bash
git add ecosystem/contact_worker.py scripts/contact-worker services/systemd/agent-contact-worker.service survival/ordinary_outbox.py survival/telegram_api.py survival/gateway.py ecosystem/notifier.py tests/test_contact_worker.py tests/test_ordinary_outbox.py tests/test_survival_gateway.py tests/test_notifier.py
git diff --cached --check && git commit -m "Route canonical contact through the permanent gateway"
```
**Acceptance:** One update yields one substantive decision reply, at most one task and one linked result; only gateway sends; an earlier bounded notice never suppresses or duplicates the eventual decision.
**Stop:** Any caller-selected destination, critical mutation, or replay after `sending` blocks packaging.
### Task C4: Safe packaging, cutover, and offline lifecycle composition
**Owner:** Sol 5.6 medium owns unit/rollback ordering; local workers may perform static unit or fake-adapter tests.
**Files:**
- Modify: `scripts/install-survival-plane`
- Create: `survival/cutover.py`
- Modify: `services/system/cointelprofessional-gateway.service`, `services/system/cointelprofessional-guardian.service`
- Modify: `services/systemd/agent-contact-worker.service`, `config/survival-lifecycle.json`, `docs/operations.md`
- Create: `ecosystem/mvp_smoke.py`, `scripts/mvp_smoke`
- Create: `tests/test_contact_cutover.py`, `tests/integration/test_mvp_flow.py`
- Modify: `tests/integration/test_survival_processes.py`
**Interfaces:**
- Produce: `cutover.plan(active_units: set[str]) -> dict`
- Produce: `cutover.apply(plan: dict, systemctl: Callable[[str, str, str], dict]) -> dict`
- Produce: `cutover.rollback(record: dict, systemctl: Callable[[str, str, str], dict]) -> dict`
- Produce: `mvp_smoke.extend_scenarios(base: dict, additions: dict) -> dict`
- Produce: `mvp_smoke.run_scenario(name: str, scenarios: dict, adapters: dict, clock: dict) -> dict`
- Consume R1 `begin_drain`, `enter_smoke`, observed leases; compose existing gateway/guardian with fake adapters.
- [ ] **Step 1: Test exact cutover ordering**
```python
import unittest
from survival import cutover
def test_old_routes_stop_before_new_poller():
    calls = []
    def systemctl(scope, action, unit):
        calls.append((scope, action, unit)); return {"ok": True, "active": action == "start"}
    record = cutover.apply(cutover.plan({"agent-telegram.service", "agent-control-worker.service"}), systemctl)
    assert calls.index(("user", "stop", "agent-telegram.service")) < calls.index(
        ("system", "start", "cointelprofessional-gateway.service"))
    assert ("user", "stop", "agent-control-worker.service") in calls
    assert record["rollback"][0]["unit"] == "cointelprofessional-gateway.service"
def load_tests(loader, tests, pattern):
    return unittest.TestSuite([unittest.FunctionTestCase(test_old_routes_stop_before_new_poller)])
```
- [ ] **Step 2: Prove absence and implement reversible fingertips**
Run: `python3 -m unittest discover -s tests -p 'test_contact_cutover.py' -v`
Expected: FAIL because `survival.cutover` is absent.
Create `outbox/ordinary` David-owned/gateway-readable, not gateway-writable; gateway
writes only private delivery records. Package `ordinary_outbox.py`. Add contact worker
to lifecycle activity/destruction; remove rejected units from post-cutover active set.
Persist inverse operations before mutation and verify every observed unit state.
Start guardian/checkpoint/inference/contact prerequisites, stop and observe old poller,
then start gateway. Failure rolls back and proves exactly one poller.
- [ ] **Step 3: Add composed offline contact/lifecycle test**
Using temporary stores, `socket.socketpair`, injected send/infer/enqueue and fake
lifecycle adapters: accept ordinary input, decide, gateway-send, accept literal
`RESTART`, reach lifecycle completion, then reply again. Assert one send per response,
gateway health, and no real network/systemd/model calls.
`scripts/mvp_smoke` is the one CLI. C4 owns its dispatch contract and initial
`contact_offline` scenario. H/A/P/B extend the plain scenario mapping through
`extend_scenarios`, which rejects duplicate names; no plan creates another smoke
script, runner, registry, or integration file.
Never run `scripts/install-survival-plane` in host tests: install-root still performs
unconditional `getent/groupadd/useradd/usermod`. Test injected account/systemd
fingertips, or the full script only inside an explicitly disposable container.
- [ ] **Step 4: Verify offline only; commit**
Run: `python3 -m unittest discover -s tests -p 'test_contact_cutover.py' -v`
Run: `python3 -m unittest discover -s tests/integration -p 'test_mvp_flow.py' -v`
Run: `python3 -m unittest discover -s tests/integration -p 'test_survival_processes.py' -v`
Run: `python3 -m py_compile ecosystem/contact_worker.py ecosystem/fast_control.py ecosystem/contact_status.py survival/ordinary_outbox.py survival/cutover.py`
Run: `systemd-analyze verify services/system/cointelprofessional-gateway.service services/system/cointelprofessional-guardian.socket services/system/cointelprofessional-guardian.service services/system/cointelprofessional-checkpoint.service services/systemd/agent-contact-worker.service`
```bash
git add scripts/install-survival-plane survival/cutover.py ecosystem/mvp_smoke.py scripts/mvp_smoke services/system/cointelprofessional-gateway.service services/system/cointelprofessional-guardian.service services/systemd/agent-contact-worker.service config/survival-lifecycle.json docs/operations.md tests/test_contact_cutover.py tests/integration/test_mvp_flow.py tests/integration/test_survival_processes.py
git diff --cached --check && git commit -m "Package reversible CointOS contact cutover"
```
**Acceptance:** Offline ordinary contact and literal lifecycle share one route; rollback predates mutation; ordinary/critical ownership stays distinct.
**Stop:** Block on unreadable spool identity, unobserved user-manager group refresh, or rollback capable of zero/two pollers.
### Task C5: Early live contact acceptance under R1 smoke fence
**Owner:** Sol 5.6 medium prepares/reviews evidence; Astra coordinates. Only David-authorized execution may touch credentials, Telegram, installation, or services.
**Files:**
- Create: `ecosystem/contact_acceptance.py`
- Create: `tests/test_contact_acceptance.py`
- Modify: `ecosystem/mvp_smoke.py`, `scripts/mvp_smoke`, `tests/integration/test_mvp_flow.py`
- Modify: `docs/operations.md`, `docs/status.md`
**Interfaces:**
- Consume: `workload_control.begin_drain(root, owner, clock) -> dict`
- Consume: `workload_control.enter_smoke(root, owner, clock, observed_workers) -> dict`
- Consume: R7 snapshot with boot identity, OOM count, pressure, and GTT.
- Produce: `begin_contact_smoke(root: Path, owner: str, clock: Callable, workers: Callable, resources: Callable) -> dict`
- Produce: `evaluate_contact_smoke(record: dict, observations: list[dict]) -> dict`
- Terminal: `passed|failed_needs_rollback|failed_rolled_back|blocked`; no inferred success or rollback.
- [ ] **Step 1: Test worker drain and OOM gate**
```python
import tempfile, unittest
from pathlib import Path
from ecosystem import contact_acceptance
def test_active_worker_blocks_and_new_oom_fails():
    with tempfile.TemporaryDirectory() as temporary:
        blocked = contact_acceptance.begin_contact_smoke(Path(temporary), "astra", lambda: 5.0,
            workers=lambda: [{"lease_id": "local-1", "state": "running"}],
            resources=lambda: {"boot_id": "boot-a", "oom_count": 2, "pressure": "normal"})
        assert blocked["state"] == "blocked"
        failed = contact_acceptance.evaluate_contact_smoke(
            {"state": "running", "boot_id": "boot-a", "oom_count": 2},
            [{"kind": "ordinary_delivered"}, {"kind": "lifecycle_completed"},
             {"kind": "ordinary_delivered_after_lifecycle"},
             {"kind": "resource", "boot_id": "boot-a", "oom_count": 3}])
        rolled_back = contact_acceptance.evaluate_contact_smoke(failed,
            [{"kind": "rollback_observed", "old_release_active": True,
              "old_poller_only": True, "contact_healthy": True}])
    assert failed["state"] == "failed_needs_rollback"
    assert rolled_back["state"] == "failed_rolled_back"
def load_tests(loader, tests, pattern):
    return unittest.TestSuite([unittest.FunctionTestCase(test_active_worker_blocks_and_new_oom_fails)])
```
- [ ] **Step 2: Implement and test evidence-only reduction**
The pure reducer only requests rollback with `failed_needs_rollback`; it reaches
`failed_rolled_back` solely from a validated rollback receipt observing old release,
single old poller, and contact health. `scripts/mvp_smoke` performs effects through
injected adapters, closes R1 admission before observation, waits for local jobs and hosted
writers in smoke scope to finish/checkpoint; captures pre-state, rollback, health,
poller states, boot/OOM/GTT/pressure, and expected update IDs. It never reads/prints
credentials, sends Telegram, or derives delivery from service activity.
Run: `python3 -m unittest discover -s tests -p 'test_contact_acceptance.py' -v`
Expected: PASS for active-worker block, stale/missing evidence, OOM, wrong boot,
duplicate delivery, rollback, and success.
- [ ] **Step 3: Execute the authorized live sequence**
1. Begin R1 drain; wait for every local job and hosted writer touching smoke scope; record boot/OOM/GTT/pressure, units, release, and rollback.
2. Provision private credentials without exposing values; install the reviewed release; start prerequisites and perform C4 cutover.
3. David sends one ordinary turn; observe inbox -> decision -> intent -> gateway `delivered`; replay its record offline with no second job/send.
4. David sends literal `RESTART` or `RESET`, then one ordinary turn; observe lifecycle completion, gateway continuity, and ordinary recovery.
5. Confirm rejected consumers inactive, front responsive under one busy worker, OOM unchanged; record `passed` and release only smoke restriction.
Failure first records `blocked|failed_needs_rollback`; the driver applies the inverse, proves the old poller is sole after rollback, and keeps admission closed if health is uncertain.
Only that receipt reduces to `failed_rolled_back`; model-independent literal commands remain available throughout.
- [ ] **Step 4: Record evidence and commit implementation/docs**
```bash
git add ecosystem/contact_acceptance.py ecosystem/mvp_smoke.py scripts/mvp_smoke tests/test_contact_acceptance.py tests/integration/test_mvp_flow.py docs/operations.md docs/status.md
git diff --cached --check && git commit -m "Add gated early contact acceptance"
```
**Acceptance:** Ordinary contact replies before/after lifecycle; replay duplicates neither task nor send; rejected consumers are inactive; front survives busy work; OOM is unchanged; exercised rollback is observed.
**Stop:** This evidence makes early contact online. Record deferred hostile-spool, exhaustive health/autonomy, and crash matrices in the one hardening queue, not as a retroactive gate.
## Summary
C1 creates one durable decision/task identity; C2 uses the protected R4 front; C3 makes the gateway sole ordinary egress while preserving critical ownership; C4 packages a composed reversible cutover; C5 admits live contact only after R1 drain and R7 checks, without waiting for exhaustive autonomy review.
