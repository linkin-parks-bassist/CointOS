# CointOS MVP Live Messaging Implementation Plan

## Original-thesis acceptance — 2026-09-07

B1–B3 preserve logical agent/conversation origin across slot waits and model swaps.
Internal delivery to a completed exact run remains unavailable: do not silently
reassign that address. Separately, C3/Coin may authorize a new continuation tied to
the original work/conversation when David replies after completion. B4 must prove
that unsolicited outbound contact and this admitted continuation compose without
keeping the old inference process alive. Telegram remains a transport fingertip;
roles and scheduler consume transport-independent identities. A5/G2 consumes this
evidence alongside slot oversubscription and memory-contended model turnover.

> **For agentic workers:** Use superpowers:subagent-driven-development or superpowers:executing-plans for the assigned task only. Follow the swarm contract's ownership, worker-lease, test, and review rules.
**Goal:** Give live CointOS agents durable direct, role, global, and Coin communication with truthful low-latency observation and authorized control.
**Architecture:** A transport-independent mailbox stores immutable envelopes and publish-time recipient snapshots derived from existing jobs plus R1 leases. Runner, inference-proxy, and tool adapters expose messages at real asynchronous boundaries; plain reducers apply status/wrap-up/cancel without OOP actors, while this typed mailbox is the one real live-message bus.
**Tech Stack:** Python standard library, atomic JSON/JSONL, `fcntl`, existing jobs, R1 leases, R4 inference proxy, R5 budgets, R6 handoffs, and `unittest`.
**Spec:** `docs/specs/2026-09-05-cointos-mvp-design.md`; execution rules: `docs/plans/2026-09-05-cointos-mvp-swarm.md`; historical working evidence remains in Git.
## Global constraints
- Coin available, no OOM, and seamless dynamic—including smaller—context handover remain binding.
- The mailbox is justified at process/inference/tool boundaries. Ordinary in-process collaboration remains direct functions over plain data; do not grow the one typed live bus into actor objects or autonomous message entities.
- Existing jobs and R1 worker leases project the live roster. Never add an authoritative agent database or mirrored lifecycle.
- `logical_run_id` is stable `job_id + agent_generation`, never PID/session/context. It survives R6 context/model/process swaps and resource pauses. A1's started `active|continuing|paused_for_resources` generation remains addressable between runner leases; a genuinely new task attempt receives a new ID. Unexpected process death is visibly unreconciled until existing recovery resolves it, not falsely healthy/completed.
- Queued-never-started jobs are not recipients. Recipient identities are resolved once at publish time. Completion before observation becomes terminal `undelivered_recipient_completed`; never silently reassign to another run/name/role.
- Addresses are exact `run`, `role`, `global`, or `coin`. Initial kinds are exact `information`, `request_status`, `wrap_up`, `cancel`, `handoff`, `announcement`.
- Every envelope preserves stable sender and target identity, creation time, trusted effective priority, causal/source key, payload, publish-time recipients, and retention deadline.
- Delivery is idempotent per recipient. `presented` means a runner inserted it at a safe boundary; `acknowledged` requires an explicit agent ACK, or an authorized controller durably observing a control request. Neither means obedience, completion, agreement, or success.
- Message priority cannot promote an ordinary sender above its installed role/profile band. Only an owning task/coordinator/recovery authority may send `wrap_up|cancel`; role labels and model text confer no control authority.
- Sole Survivor > Coin > small health inspectors > large health inspectors > other roles; Coin's physical reserved inference sequence remains exclusive regardless of rank.
- Bounds for payload bytes, publish fan-out, per-run pending count, and retention are validated data in `config/messaging.json`, not prompt instructions.
- Do not store Telegram bodies, credentials, or professional/customer content in Git. Runtime envelopes live under ignored state.
- R4 proxy/runner injection occurs at the earliest safe boundary. If the current OpenCode/backend request cannot be interrupted, state remains `queued`, never falsely delivered; urgent authorized control uses bounded cancellation/checkpoint policy.
- Local tasks use the largest task-qualified model and context that fresh R2/R3 admission allows, with output/handoff reserve. Local chunks are small and simple; Sol work is medium reasoning, isolated, 15-25 minutes.
- Before any live smoke, R1 closes admission, asks local jobs to finish/checkpoint, and Codex waits for process/request/lease completion. C5 early contact does not depend on this plan; B4 must pass before final A5 complete-MVP acceptance.
- Tests use temporary roots and injected adapters only; no live inference, Telegram, systemd, services, credentials, or runtime state.
- New tests use the swarm `load_tests`/`FunctionTestCase` collector and `python3 -m unittest discover`.
## Ownership and dependencies
- `ecosystem/messaging.py`: immutable schema, address resolution, publish, delivery and acknowledgement reducer.
- `ecosystem/live_roster.py`: read-only projection from jobs and R1 leases.
- `ecosystem/message_adapter.py`: runner/proxy/tool boundary fetch and actual observation.
- `ecosystem/message_control.py`: authority and control-state reduction over R1/R5/R6.
- `config/messaging.json`: bounds, retention, kinds, addresses, trusted priority policy.
- B1 depends on A1 and R1. B2 depends on B1 and R4. B3 depends on B1-B2 and R1/R5/R6. B4 depends on B1-B3 and C5; A5 depends on B4, while C5 does not depend on messaging.
---
### Task B1: Durable envelopes, address resolution, and per-recipient delivery
**Owner/budget:** Sol medium, 20 minutes. Local workers may implement one validator/reducer test after interfaces are fixed.
**Files:**
- Create: `ecosystem/live_roster.py`, `ecosystem/messaging.py`, `config/messaging.json`
- Create: `tests/test_mvp_live_roster.py`, `tests/test_mvp_messaging.py`
- Modify: `ecosystem/cli.py` only to initialize ignored mailbox directories.
**Interfaces:**
- `logical_run_id(job_id: str, agent_generation: int) -> str`
- `project_live_roster(jobs: list[dict], leases: list[dict], now: float) -> list[dict]`
- `resolve_address(address: dict, roster: list[dict], coin_recipient: dict) -> list[str]`
- `validate_draft(draft: dict, policy: dict) -> dict`
- `publish(root: Path, draft: dict, roster: list[dict], coin_recipient: dict, policy: dict, clock: dict) -> dict`
- `delivery_state(root: Path, message_id: str, recipient_id: str) -> dict`
- `mark_observed(root: Path, message_id: str, recipient_id: str, boundary_id: str, clock: dict) -> dict`
- Envelope fields: `schema_version`, `message_id`, `source_key`, `sender`, `address`, `recipients`, `kind`, `priority`, `payload`, `created_at`, `created_monotonic`, `boot_id`, `retention_deadline_monotonic`, `causal_parent_id`.
- Recipient state: `queued|presented|acknowledged|undelivered_recipient_completed|expired`; presentation, explicit ACK, and later result retain separate boundary IDs/times.
- `sender` is `{logical_run_id, job_id, agent_generation, role, authority_profile}`; Coin/system coordinator/recovery senders use validated installed identities, not model-supplied labels.
- Address forms: `{"kind":"run","target":"task-x:g2"}`, `{"kind":"role","target":"auditor"}`, `{"kind":"global","target":"*"}`, `{"kind":"coin","target":"coin"}`.
- Initial policy values: `maximum_payload_bytes=16384`, `maximum_fanout=32`, `maximum_pending_per_recipient=128`, `retention_seconds=604800`; validators own later changes.
- [ ] Write roster/snapshot/replay tests, including this complete case:
```python
import tempfile, unittest
from pathlib import Path
from ecosystem import messaging

def test_role_snapshot_excludes_queued_and_does_not_reassign():
    roster = [
        {"logical_run_id": "task-a:g1", "job_id": "task-a", "agent_generation": 1,
         "role": "auditor", "state": "running", "authority_profile": "work"},
    ]
    draft = {"source_key": "task-s:g1:message:1",
             "sender": {"logical_run_id": "task-s:g1", "job_id": "task-s",
                        "agent_generation": 1, "role": "worker", "authority_profile": "work"},
             "address": {"kind": "role", "target": "auditor"}, "kind": "information",
             "priority": 3, "payload": {"text": "check the queue"}, "causal_parent_id": None}
    policy = {"maximum_payload_bytes": 16384, "maximum_fanout": 32,
              "maximum_pending_per_recipient": 128, "retention_seconds": 604800}
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        first = messaging.publish(root, draft, roster, {"logical_run_id": "coin"}, policy,
                                  {"boot_id": "b", "monotonic": 1.0, "utc": "x"})
        second = messaging.publish(root, draft, roster + [{"logical_run_id": "task-b:g1",
            "job_id": "task-b", "agent_generation": 1, "role": "auditor",
            "state": "running", "authority_profile": "work"}], {"logical_run_id": "coin"},
            policy, {"boot_id": "b", "monotonic": 2.0, "utc": "y"})
    assert first["recipients"] == second["recipients"] == ["task-a:g1"]

def load_tests(loader, tests, pattern):
    return unittest.TestSuite([unittest.FunctionTestCase(test_role_snapshot_excludes_queued_and_does_not_reassign)])
```
- [ ] Run `python3 -m unittest discover -s tests -p 'test_mvp_messaging.py' -v`; expect missing-module failure.
- [ ] Project roster from A1's started job generation/state plus R1 process observations. R4 inference and R1 runner leases may end during a recorded R6 continuation without removing the address. Never-started queued jobs and terminal generations are absent. Unexpected dead/expired owners are unavailable pending bounded reconciliation, never a completed or healthy run by inference; retain queued mail for that generation. Never persist a separate roster. Sort/deduplicate recipient snapshots; reject empty direct/role targets explicitly, bound broadcasts before publication, and derive message ID from stable source key.
```python
recipients = tuple(sorted(set(resolve_address(draft["address"], roster, coin_recipient))))
if len(recipients) > policy["maximum_fanout"]:
    raise ValueError("message fanout exceeds policy")
message_id = "message-" + hashlib.sha256(draft["source_key"].encode()).hexdigest()[:24]
```
- [ ] Atomically publish immutable envelope before per-recipient `queued` delivery records. Replay must match sender/address/kind/payload and exact original recipients. Expiry/completion reducers are idempotent; never delete append-only audit causality when pruning expired payloads.
- [ ] Run both new test modules; cover direct/role/global/Coin, duplicate publish, crash cuts, payload/fan-out/pending/retention bounds, completed-before-observation, reboot expiry, sender spoof, and stable ID across R6 context swaps. Commit only named files after review.
```bash
git add ecosystem/live_roster.py ecosystem/messaging.py ecosystem/cli.py config/messaging.json tests/test_mvp_live_roster.py tests/test_mvp_messaging.py
git diff --cached --check && git commit -m "Add durable live message envelopes"
```
**Acceptance/stop:** Every publish has one immutable recipient snapshot and one state per recipient; roster comes only from job+lease truth. Stop if R1 lacks generation/live-owner facts—fix that contract, not a shadow registry.
### Task B2: Live runner, inference-proxy, and tool boundary adapters
**Owner/budget:** Sol medium, 20 minutes. Local workers may implement one fake-boundary test or exact tool schema.
**Files:**
- Create: `ecosystem/message_adapter.py`, `ecosystem/message_tools.py`
- Create: `tests/test_mvp_message_adapter.py`, `tests/test_mvp_message_tools.py`
- Modify: `ecosystem/executor.py` at its existing event/tool loop.
- Modify: `ecosystem/inference_proxy.py` at R4's admitted request/response boundary.
**Interfaces:**
- `pending(root: Path, logical_run_id: str, limit: int, clock: dict) -> list[dict]`
- `prepare_injection(root: Path, logical_run_id: str, boundary_id: str, capacity_bytes: int, clock: dict) -> dict`
- `commit_presentation(root: Path, injection: dict, presented_message_ids: list[str], clock: dict) -> list[dict]`
- `send_message(root: Path, sender: dict, address: dict, kind: str, payload: dict, priority: int, source_key: str, dependencies: dict) -> dict`
- `acknowledge_messages(root: Path, logical_run_id: str, boundary_id: str, message_ids: list[str], clock: dict) -> list[dict]`
- Boundary kinds: `before_inference`, `after_inference`, `before_tool`, `after_tool`, `runner_tick`.
- [ ] Write an actual-observation test:
```python
import tempfile, unittest
from pathlib import Path
from ecosystem import message_adapter, message_tools, messaging
def seed_message(root):
    roster = [{"logical_run_id": "task-a:g1", "job_id": "task-a", "agent_generation": 1,
               "role": "worker", "state": "running", "authority_profile": "work"}]
    sender = {"logical_run_id": "task-s:g1", "job_id": "task-s", "agent_generation": 1,
              "role": "worker", "authority_profile": "work"}
    draft = {"source_key": "task-s:g1:message:1", "sender": sender,
             "address": {"kind": "run", "target": "task-a:g1"}, "kind": "information",
             "priority": 1, "payload": {"text": "wrap soon"}, "causal_parent_id": None}
    policy = {"maximum_payload_bytes": 16384, "maximum_fanout": 32,
              "maximum_pending_per_recipient": 128, "retention_seconds": 604800}
    return messaging.publish(root, draft, roster, {"logical_run_id": "coin"}, policy,
                             {"boot_id": "b", "monotonic": 1.0, "utc": "w"})

def test_presentation_is_not_ack_until_agent_explicitly_observes():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        envelope = seed_message(root)
        message_id = envelope["message_id"]
        injection = message_adapter.prepare_injection(root, "task-a:g1", "tool-7", 4096,
                                                      {"boot_id": "b", "monotonic": 2.0, "utc": "x"})
        assert messaging.delivery_state(root, message_id, "task-a:g1")["state"] == "queued"
        message_adapter.commit_presentation(root, injection, [message_id],
                                            {"boot_id": "b", "monotonic": 3.0, "utc": "y"})
        assert messaging.delivery_state(root, message_id, "task-a:g1")["state"] == "presented"
        message_tools.acknowledge_messages(root, "task-a:g1", "tool-7", [message_id],
                                           {"boot_id": "b", "monotonic": 4.0, "utc": "z"})
        assert messaging.delivery_state(root, message_id, "task-a:g1")["state"] == "acknowledged"

def load_tests(loader, tests, pattern):
    return unittest.TestSuite([unittest.FunctionTestCase(test_presentation_is_not_ack_until_agent_explicitly_observes)])
```
- [ ] Run `python3 -m unittest discover -s tests -p 'test_mvp_message_adapter.py' -v`; expect missing-module failure.
- [ ] Implement fetch as read-only. `prepare_injection` selects bounded messages but leaves them queued. After exact IDs/payload enter the next model/tool/control input, `commit_presentation` records only `presented`; crash before it causes safe redelivery. The agent explicitly invokes `acknowledge_messages` after observing content. For authorized controls only, the controller may ACK when it durably accepts the request into B3 state.
- [ ] Add the transport-independent tools to admitted runs. `send_message` snapshots recipients through B1; `acknowledge_messages` verifies caller logical run and boundary. Messages entering during an in-flight uninterruptible OpenCode request stay visibly queued. `ecosystem/inference_proxy.py` checks before request, after response, and at tool calls; it does not mutate the original prompt.
- [ ] Run both new modules plus focused executor/R4 tests. Cover arrival during inference/tool, capacity truncation without loss, crash between injection/commit, completed target, invalid ACK recipient, and no fake ACK on enqueue/fetch. Commit after independent review.
```bash
git add ecosystem/message_adapter.py ecosystem/message_tools.py ecosystem/executor.py ecosystem/inference_proxy.py tests/test_mvp_message_adapter.py tests/test_mvp_message_tools.py
git diff --cached --check && git commit -m "Inject messages at live runner boundaries"
```
**Acceptance/stop:** A live run is presented a message at the earliest safe boundary and explicitly acknowledges observation; presentation alone is not ACK. Stop if an adapter exposes no boundary—record queued limitation and add controlled B3 cancellation rather than lie.
### Task B3: Status, wrap-up, cancel, handoff, and resource integration
**Owner/budget:** Sol medium, 25 minutes. Split pure authority/reducer tests from runner integration; local chunks are small and simple.
**Files:**
- Create: `ecosystem/message_control.py`, `tests/test_mvp_message_control.py`
- Modify: `ecosystem/workload_control.py`, `ecosystem/execution_budget.py`, `ecosystem/continuation.py` at their owning control boundaries.
- Modify: `config/messaging.json`, `roles/_base.md`, `docs/operations.md`.
**Interfaces:**
- `effective_message_priority(sender: dict, requested: int, policy: dict) -> int`
- `authorize_control(sender: dict, recipient: dict, kind: str, ownership: dict, policy: dict) -> None`
- `reduce_control(run: dict, message: dict, event: dict, policy: dict) -> tuple[dict, list[dict]]`
- `apply_control(root: Path, logical_run_id: str, message: dict, adapters: dict, clock: dict) -> dict`
- Effects: `report_status`, `request_wrap_up`, `request_checkpoint`, `cancel_inference`, `stop_process`, `publish_handoff`, `finish`.
- [ ] Write authority/priority tests:
```python
import unittest
from ecosystem.message_control import authorize_control, effective_message_priority

def test_role_label_cannot_cancel_or_jump_band():
    sender = {"logical_run_id": "task-x:g1", "role": "sole_survivor",
              "authority_profile": "work", "priority_band": [100, 199]}
    recipient = {"logical_run_id": "task-y:g1", "job_id": "task-y"}
    policy = {"control_authorities": ["coordinator", "recovery"], "maximum_local_priority": 99}
    assert effective_message_priority(sender, 9999, policy) == 199
    try:
        authorize_control(sender, recipient, "cancel", {"owner_run_id": "task-z:g1"}, policy)
    except PermissionError:
        pass
    else:
        raise AssertionError("model role label granted cancel authority")

def load_tests(loader, tests, pattern):
    return unittest.TestSuite([unittest.FunctionTestCase(test_role_label_cannot_cancel_or_jump_band)])
```
- [ ] Run `python3 -m unittest discover -s tests -p 'test_mvp_message_control.py' -v`; expect missing-module failure.
- [ ] Implement kind semantics: `information|announcement` adds bounded context; `handoff` preserves causal/source identity; `request_status` publishes one concise progress/checkpoint reply without implying success; `wrap_up` closes scope expansion and requests R6 durable handoff; `cancel` requests handoff/checkpoint then bounded R4 cancellation/process stop. ACK is recorded when the control loop validates/persists the request, while outcome remains separate.
```python
def reduce_control(run, message, event, policy):
    if message["kind"] == "cancel":
        authorize_control(message["sender"], run, "cancel", run["ownership"], policy)
        return {**run, "control_state": "cancel_requested"}, [
            {"kind": "request_checkpoint"}, {"kind": "cancel_inference"},
            {"kind": "stop_process"}]
    raise ValueError("unsupported control reduction")
```
- [ ] Owner means exact task owner identity; coordinator/recovery are installed authority profiles. Validate from R1 lease/task contract, not message fields. Ordinary priority stays inside its role band. No label, payload, announcement, or global address grants control or clones work.
- [ ] R1 drain publishes authorized `wrap_up` to each live run, waits for actual observation plus durable R6 checkpoint, then uses R5's 30-second wrap-up and 15-second termination grace. If OpenCode cannot interrupt, keep command queued until the R4 proxy returns unless the authorized bounded cancellation fingertip stops the request; terminal state must be recoverable/failed, never dead `running`.
- [ ] Run message-control, R1, R5, R6, and executor focused tests. Cover status response, wrap-up timeout, cancellation during uninterruptible inference, completed recipient, sender crash, restart, context swap, unauthorized owner, and causal handoff. Commit named files only.
```bash
git add ecosystem/message_control.py ecosystem/workload_control.py ecosystem/execution_budget.py ecosystem/continuation.py config/messaging.json roles/_base.md docs/operations.md tests/test_mvp_message_control.py
git diff --cached --check && git commit -m "Integrate authorized live message controls"
```
**Acceptance/stop:** Authorized control yields observed request plus separate truthful outcome; drain never equates enqueue with ACK. Stop if cancellation can lose the R6 handoff or bypass stronger pressure/lifecycle policy.
### Task B4: Offline composition and bounded live communication smoke
**Owner/budget:** Coordinator owns live smoke; Sol medium owns offline composition. Local workers finish/checkpoint before the smoke fence, then only test-owned runs are admitted.
**Files:**
- Create: `tests/integration/messaging_flow.py`, `tests/integration/test_mvp_messaging_flow.py`
- Modify: shared `ecosystem/mvp_smoke.py`, `scripts/mvp_smoke` and `tests/integration/test_mvp_flow.py` through C4's `extend_scenarios`/`run_scenario` contract.
- Modify: `docs/operations.md`, `docs/status.md`, and applicable semantic knowledge leaves with sanitized facts only.
**Interfaces:**
- Smoke scenario: `messaging` consumes R1 fence, R2/R3 route, R4 requests, R5 budgets, R6 continuation, C3 Coin address, and B1-B3.
- Result fields: `scenario`, `sender_run_id`, `recipient_snapshot`, `observed_message_ids`, `acknowledged_at`, `control_outcomes`, `context_transitions`, `resource_before`, `resource_after`, `state`.
- [ ] Add one complete offline flow using temporary jobs/leases, fake runner boundaries, fake inference requests, and no services:
```python
import tempfile, unittest
from pathlib import Path
import messaging_flow

def test_offline_flow_preserves_run_across_smaller_context():
    with tempfile.TemporaryDirectory() as temporary:
        result = messaging_flow.run_offline(
            Path(temporary),
            runs=[{"logical_run_id": "task-a:g1", "context_tokens": 32768},
                  {"logical_run_id": "task-b:g1", "context_tokens": 65536}],
            successor={"logical_run_id": "task-a:g1", "context_tokens": 16384},
            clock={"boot_id": "b", "monotonic": 1.0, "utc": "x"})
    assert result["state"] == "passed"
    assert result["context_transitions"][0]["logical_run_id"] == "task-a:g1"
    assert len(result["observed_message_ids"]) == len(set(result["observed_message_ids"]))

def load_tests(loader, tests, pattern):
    return unittest.TestSuite([unittest.FunctionTestCase(test_offline_flow_preserves_run_across_smaller_context)])
```
`messaging_flow.run_offline` is a test-support function in `tests/integration/messaging_flow.py`; add that file to B4 ownership. It exchanges direct information/handoff, role/global snapshots, C3 Coin intent, status, authorized wrap-up/cancel, completed-before-observation, and the shown context transition.
- [ ] Run `python3 -m unittest discover -s tests/integration -p 'test_mvp_messaging_flow.py' -v`. Then run affected B1-B3 modules separately and assert positive test counts. Expected: all pass offline; no network/model/systemd calls.
- [ ] Acquire R1 smoke fence. Codex announces scope, stops new admission, asks every local job to finish its current chunk, waits for process groups/R4 requests/leases, and waits for hosted writers touching smoke files. Unknown owner blocks smoke. Preserve Coin reserve and resource/lifecycle/operator restrictions.
- [ ] Admit two short test-owned logical runs using the largest qualified model/context that fresh R2/R3 evidence permits, including output/handoff reserve. They may use available concurrent slots or alternate requests as capacity opens; this messaging proof does not require D10's post-MVP scheduled state swapping (decision 0019). Exercise direct, role-local, global, and Coin addresses during inference and tool use; observe explicit ACK after presentation, not publication or injection.
- [ ] Send authorized `request_status`, then `wrap_up` to one run and `cancel` to the other. Observe bounded status, R6 handoff/checkpoint, R5 stop outcome, terminal lease/process state, and no silent recipient reassignment. If mid-generation interruption is unsupported, record queued delay and demonstrate the controlled authorized cancellation boundary truthfully.
- [ ] Continue one logical run through a smaller safe context allocation and verify the same task/generation address receives pending mail exactly once. Confirm Coin remains responsive, no unmanaged inference, no OOM increment, bounds honored, and final health known; release only smoke fence.
- [ ] Record sanitized IDs/timings/outcomes. B4 passes before A5 final autonomous cycles but does not delay C5 early contact. Any ordinary-operation/OOM/contact/continuity failure returns to its owner; deferred transport/security hardening enters the single queue.
```bash
git add tests/integration/messaging_flow.py tests/integration/test_mvp_messaging_flow.py ecosystem/mvp_smoke.py scripts/mvp_smoke tests/integration/test_mvp_flow.py docs/operations.md docs/status.md .knowledge
git diff --cached --check && git commit -m "Prove bounded live agent messaging"
```
**Acceptance/stop:** Live agents and Coin exchange all address classes; actual observations and control outcomes are distinct; wrap-up/cancel preserve recoverable work; context swap preserves logical identity; resource/contact invariants hold. Stop after one bounded successful flow, not exhaustive adversarial transport review.
## Summary
B1 establishes immutable envelopes from the existing job/lease truth. B2 makes real runner/tool/proxy observation—not enqueue—the ACK boundary. B3 gives authorized status/wrap-up/cancel semantics integrated with drain, budgets, and handoff. B4 proves communication across live inference/tool/context boundaries before final A5, without making it an early-contact prerequisite.
