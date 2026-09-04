# Cointelprofessional Priority Fast Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route ordinary Telegram messages through a mechanically reserved small-model lane which replies promptly and makes one validated respond-or-dispatch decision.

**Architecture:** A filesystem-backed inference arbiter owns all Lemonade chat requests and reserves one of two small-model sequences for contact. A separate fast-control worker consumes the permanent gateway spool, supplies bounded conversation and subsystem facts, validates one structured decision, and emits a durable response plus at most one idempotent job.

**Tech Stack:** Python 3, atomic JSON files, `fcntl`, forked subprocess workers, Lemonade HTTP, systemd user services, and `unittest`.

**Spec:** `docs/superpowers/specs/2026-09-04-cointelprofessional-survival-control-design.md`

## Global Constraints

- Telegram polling never waits for inference or delivery presentation.
- One small-model sequence is physically unavailable to non-front requests.
- Only a schema-valid `dispatch` result can enqueue work.
- Fast failure yields an honest survival-plane response and a recoverable turn, never silence or a false action claim.
- Roles in dispatch decisions are optional advisory labels.
- Every inference request has a durable identity, lane, deadline, state, and explicit delivery result.
- New function-style test modules end with the repository's existing `load_tests`
  collector so `unittest` discovers every `test_*` function.

---

### Task 1: Durable prioritized inference requests

**Files:**
- Create: `ecosystem/inference_queue.py`
- Create: `tests/test_inference_queue.py`

**Interfaces:**
- Produces: `enqueue(lane: str, request: dict, deadline_monotonic: float, root: Path = ROOT) -> str`
- Produces: `claim_next(root: Path, active: dict[str, int]) -> dict | None`
- Produces: `complete(request_id: str, response: dict, root: Path = ROOT) -> None`
- Produces: `fail(request_id: str, error: str, root: Path = ROOT) -> None`
- Produces: `recover_abandoned(root: Path = ROOT) -> int`

- [ ] **Step 1: Write queue ordering, reserve, expiry, and recovery tests**

```python
def test_front_claims_reserved_capacity_while_background_is_active(root):
    background = enqueue_request(root, "background", created=1)
    front = enqueue_request(root, "front", created=2)
    claimed = inference_queue.claim_next(root, active={"background": 1, "front": 0})
    assert claimed["id"] == front


def test_second_background_cannot_consume_front_reserve(root):
    enqueue_request(root, "background", created=1)
    assert inference_queue.claim_next(root, active={"background": 1, "front": 0}) is None


def test_dead_claim_owner_returns_request_to_queue(root):
    request = claimed_request(root, owner_identity="dead")
    assert inference_queue.recover_abandoned(root) == 1
    assert read_request(root, request)["state"] == "queued"
```

- [ ] **Step 2: Run and confirm missing queue failure**

Run: `python3 -m unittest tests.test_inference_queue -v`

Expected: FAIL because the inference queue is absent.

- [ ] **Step 3: Implement explicit lanes and capacity**

```python
LANE_PRIORITY = {"front": 10000, "recovery": 9000, "control": 7000,
                 "routing": 6000, "presentation": 3000, "background": 1000}
MAX_ACTIVE = 2
MAX_NON_FRONT_ACTIVE = 1


def eligible(record: dict, active: dict[str, int], now: float) -> bool:
    if record["deadline_monotonic"] <= now:
        return False
    if sum(active.values()) >= MAX_ACTIVE:
        return False
    non_front = sum(count for lane, count in active.items() if lane != "front")
    return record["lane"] == "front" or non_front < MAX_NON_FRONT_ACTIVE
```

Sort by descending lane priority then ascending creation sequence, never filename.
Claim under one `fcntl` lock and persist a boot/PID/start-time owner identity.

- [ ] **Step 4: Run queue tests and commit**

Run: `python3 -m unittest tests.test_inference_queue -v`

Expected: PASS.

```bash
git add ecosystem/inference_queue.py tests/test_inference_queue.py
git commit -m "Add reserved inference request queue"
```

### Task 2: Inference arbiter and client migration

**Files:**
- Modify: `ecosystem/inference.py`
- Create: `ecosystem/inference_arbiter.py`
- Create: `scripts/inference-arbiter`
- Create: `services/systemd/agent-inference-arbiter.service`
- Modify: `ecosystem/control_agent.py`
- Modify: `ecosystem/models.py`
- Modify: `ecosystem/identity.py`
- Modify: `ecosystem/presentation.py`
- Test: `tests/test_inference_arbiter.py`
- Test: `tests/test_local_intent.py`

**Interfaces:**
- Produces: `direct_chat(...) -> dict` as the arbiter's only Lemonade HTTP adapter
- Changes: `chat(..., lane: str = "background", request_id: str | None = None) -> dict`
- Produces: `run_once(root: Path = ROOT, infer: Callable = direct_chat) -> int`

- [ ] **Step 1: Write two-sequence and migrated-lane tests**

```python
def test_arbiter_runs_front_while_background_is_blocked(root):
    blocked = blocking_infer()
    start_arbiter(root, infer=blocked["infer"])
    background_id = inference_queue.enqueue("background", request(), deadline(30), root)
    blocked["wait_started"](background_id)
    front_id = inference_queue.enqueue("front", request(), deadline(5), root)
    blocked["release"](front_id, {"content": "hello"})
    assert wait_result(root, front_id)["content"] == "hello"
    assert read_request(root, background_id)["state"] == "running"


def test_router_submits_routing_lane():
    captured = {}
    models.route(job(), inventory(), infer=lambda **kwargs: captured.update(kwargs) or valid_route())
    assert captured["lane"] == "routing"
```

- [ ] **Step 2: Run arbiter tests**

Run: `python3 -m unittest tests.test_inference_arbiter tests.test_local_intent -v`

Expected: FAIL because `lane` and the arbiter do not exist.

- [ ] **Step 3: Split direct HTTP from queued client and migrate all callers**

```python
def chat(model, messages, max_tokens, timeout, temperature=0.35, tools=None,
         response_format=None, lane="background", request_id=None):
    request = build_request(model, messages, max_tokens, temperature, tools,
                            response_format)
    identifier = inference_queue.enqueue(
        lane, request, time.monotonic() + timeout, request_id=request_id)
    return inference_queue.wait(identifier, timeout)
```

The arbiter forks at most two HTTP workers and admits at most one non-front worker.
Assign `control`, `routing`, `presentation`, or `background` explicitly at every
call site. The systemd unit belongs to `control.slice`, restarts on failure, and is
part of the destructible set.

- [ ] **Step 4: Run inference and existing model tests**

Run: `python3 -m unittest tests.test_inference_queue tests.test_inference_arbiter tests.test_local_intent tests.test_resource_control tests.test_identity -v`

Expected: PASS with every mocked inference call observing its expected lane.

- [ ] **Step 5: Commit the arbiter**

```bash
git add ecosystem/inference.py ecosystem/inference_arbiter.py scripts/inference-arbiter \
  services/systemd/agent-inference-arbiter.service ecosystem/control_agent.py \
  ecosystem/models.py ecosystem/identity.py ecosystem/presentation.py \
  tests/test_inference_arbiter.py tests/test_local_intent.py
git commit -m "Reserve inference capacity for Cointelprofessional"
```

### Task 3: Structured fast respond-or-dispatch decision

**Files:**
- Create: `ecosystem/fast_control.py`
- Create: `tests/test_fast_control.py`
- Modify: `config/model-policy.json`

**Interfaces:**
- Produces: `decision_prompt(message: str, history: list[dict], status: dict) -> list[dict]`
- Produces: `validate_decision(value: dict) -> dict`
- Produces: `decide(message: str, history: list[dict], status: dict, infer: Callable = chat) -> dict`

- [ ] **Step 1: Write decision schema and no-dispatch tests**

```python
def test_conversation_decision_cannot_create_work():
    result = fast_control.decide("lol", [], {}, infer=returns_json(
        {"reply": "yeah, fair", "decision": "respond"}))
    assert result == {"reply": "yeah, fair", "decision": "respond",
                      "task": None, "role": None, "constraints": []}


def test_dispatch_requires_a_task_but_not_a_role():
    result = fast_control.validate_decision(
        {"reply": "I’ll investigate.", "decision": "dispatch",
         "task": "Find the scheduler stall", "role": None, "constraints": []})
    assert result["role"] is None
    with unittest.TestCase().assertRaisesRegex(ValueError, "task"):
        fast_control.validate_decision({"reply": "ok", "decision": "dispatch"})


def test_model_receives_front_lane_and_compact_status():
    captured = {}
    fast_control.decide("status?", [], {"scheduler": {"health": "healthy"}},
                        infer=capturing_infer(captured))
    assert captured["lane"] == "front"
    assert captured["response_format"] == {"type": "json_object"}
```

- [ ] **Step 2: Run and observe missing decision module**

Run: `python3 -m unittest tests.test_fast_control -v`

Expected: FAIL because `ecosystem.fast_control` does not exist.

- [ ] **Step 3: Implement strict plain-data decisions**

```python
DECISIONS = {"respond", "dispatch"}


def validate_decision(value: dict) -> dict:
    if set(value) - {"reply", "decision", "task", "role", "constraints"}:
        raise ValueError("unknown decision fields")
    reply = value.get("reply")
    decision = value.get("decision")
    if not isinstance(reply, str) or not reply.strip() or decision not in DECISIONS:
        raise ValueError("invalid reply or decision")
    task = value.get("task")
    if decision == "dispatch" and (not isinstance(task, str) or not task.strip()):
        raise ValueError("dispatch requires task")
    return normalized_decision(reply, decision, task, value.get("role"),
                               value.get("constraints", []))
```

The prompt states that roles are optional and that only work requiring sustained
reasoning, machine action, or specialist capability should dispatch.

- [ ] **Step 4: Run decision tests and commit**

Run: `python3 -m unittest tests.test_fast_control -v`

Expected: PASS.

```bash
git add ecosystem/fast_control.py tests/test_fast_control.py config/model-policy.json
git commit -m "Let the fast control model decide dispatch"
```

### Task 4: Fast-control spool worker and durable delivery

**Files:**
- Create: `ecosystem/fast_worker.py`
- Create: `scripts/fast-control-worker`
- Create: `services/systemd/agent-fast-control.service`
- Modify: `survival/records.py`
- Modify: `survival/gateway.py`
- Modify: `ecosystem/conversation.py`
- Modify: `ecosystem/cli.py`
- Modify: `ecosystem/control_runtime.py`
- Test: `tests/test_fast_worker.py`
- Test: `tests/test_control_turns.py`

**Interfaces:**
- Consumes: survival `inbox/*.json`, `fast_control.decide`, and `control_runtime.fast_status_summary()`
- Produces: survival `outbox/*.json` linked to update ID
- Produces: `process_message(path: Path, infer: Callable, status: Callable) -> dict`

- [ ] **Step 1: Write end-to-end respond, dispatch, replay, and failure tests**

```python
def test_respond_writes_reply_without_job(root, survival_root):
    path = write_inbound(survival_root, 101, "hello")
    result = fast_worker.process_message(path, infer=responding_model(), status=lambda: {})
    assert result["decision"] == "respond"
    assert no_agent_jobs(root)
    assert read_outbox(survival_root, 101)["message"] == "hello back"


def test_dispatch_replay_creates_exactly_one_job(root, survival_root):
    path = write_inbound(survival_root, 102, "inspect scheduler")
    for _ in range(2):
        fast_worker.process_message(path, infer=dispatching_model(role=None), status=lambda: {})
    jobs = agent_jobs(root)
    assert len(jobs) == 1
    assert jobs[0]["idempotency_key"] == "telegram-102:dispatch"


def test_timeout_leaves_recoverable_turn_for_gateway_fallback(root, survival_root):
    path = write_inbound(survival_root, 103, "are you alive?")
    result = fast_worker.process_message(path, infer=timeout_model(), status=lambda: {})
    assert result["state"] == "failed"
    assert read_inbound(survival_root, 103)["state"] == "failed"
    assert read_inbound(survival_root, 103)["recoverable"] is True
```

- [ ] **Step 2: Run and observe missing worker failure**

Run: `python3 -m unittest tests.test_fast_worker tests.test_control_turns -v`

Expected: FAIL because the spool worker is absent.

- [ ] **Step 3: Implement one idempotent message transaction**

```python
def process_message(path, infer=fast_control.decide,
                    status=control_runtime.fast_status_summary):
    turn = records.claim_inbound(path, owner_identity=process_identity())
    history = conversation.recent(turn["user_id"], max_messages=6,
                                  max_characters=2500)
    decision = infer(turn["text"], history, status())
    if decision["decision"] == "dispatch":
        cli.enqueue_task(decision["role"], decision["task"],
                         source=f"telegram:{turn['user_id']}",
                         idempotency_key=f"{turn['id']}:dispatch")
    records.enqueue_reply(turn, decision["reply"])
    records.complete_inbound(path, decision)
    return decision
```

Ordering must make replay safe at every crash boundary. Conversation append uses a
source ID derived from the Telegram update and delivery phase.

- [ ] **Step 4: Run focused and regression tests**

Run: `python3 -m unittest tests.test_fast_worker tests.test_fast_control tests.test_control_turns tests.test_conversation tests.test_inference_arbiter -v`

Expected: PASS.

- [ ] **Step 5: Commit fast-control integration**

```bash
git add ecosystem/fast_worker.py scripts/fast-control-worker \
  services/systemd/agent-fast-control.service survival/records.py survival/gateway.py \
  ecosystem/conversation.py ecosystem/cli.py ecosystem/control_runtime.py \
  tests/test_fast_worker.py \
  tests/test_control_turns.py
git commit -m "Connect Telegram ingress to priority fast control"
```
