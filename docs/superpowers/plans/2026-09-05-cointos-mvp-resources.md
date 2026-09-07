# CointOS MVP Resource and Execution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build one mechanically enforced resource, worker, inference, budget, continuation, and recovery path which keeps Coin available, prevents OOM, and makes context turnover seamless.

**Architecture:** Plain durable records and functions form the contract. `workload_control.py` owns worker admission/smoke exclusion; `models.py` interprets verified model facts; `inference_capacity.py` owns physical leases; `inference_proxy.py` is the sole backend HTTP authority; the executor and `continuation.py` own bounded execution/context transitions. Existing pressure/emergency mechanisms compose through the gate.

**Tech Stack:** Python 3 standard library, JSON/JSONL durable records, `fcntl`, `/proc`, systemd observations, Lemonade OpenAI-compatible HTTP, OpenCode JSON events, `unittest`.

**Spec:** `docs/superpowers/specs/2026-09-05-cointos-mvp-design.md`

## Global Constraints

- Concurrent agents and contention-driven slot/model time-sharing are core MVP.
  Reuse backend slots, batching and load/unload; no second model server, fixed
  one-work-model rule or blanket busy check in place of admission.
- Coin stays available; no OOM; context handover is independently mandatory and never becomes a terminal context-overflow result.
- Software is functions over plain data. Add no classes, hidden mutable object state, actor framework, or new database.
- Use lowercase `snake_case`; preserve external API spelling only where required.
- A prompt is not enforcement. Every inference and worker request needs a durable lease and mechanical budget.
- Roles are advisory labels. Model qualification consumes explicit task requirements; validated priority configuration orders Sole Survivor 1000, Coin 900, small health 800, large health 700, and every other/default role below 700 without role-switch code.
- Context is any backend-supported quantum inside the current envelope; do not encode `context_candidates` as architecture.
- Parameter count, model bytes, host RAM, GTT, KV, prompt, tool, output, and handoff demand remain distinct facts.
- Unknown or stale safety evidence defers explicitly. Preserve the 32 GiB protected
  host reserve and 12 GiB load-transient reserve. The configured GTT capacity is the
  configured 100 GiB target. Reconcile conflicting allocation readings and preserve
  their provenance; do not silently change the target or guess unreadable values.
- Interrupt a local run only when a GPU-involving smoke test is ready and competing for the GPU; then require a durable completion/checkpoint handoff and observed process/request exit before smoke. Resource guardians retain authority to stop a run to prevent OOM or loss of host responsiveness. The execution budget specified below governs managed CointOS task slicing after R5; it is not a limit on local implementation workers during bring-up.
- Sol implementation/review work uses `gpt-5.6-sol`, `reasoning_effort: medium`, isolated context, and one 15–25 minute bounded objective.
- Hosted read-only analysis may continue during smoke. Every hosted writer touching smoke-covered files/services must finish and be observed before smoke.
- The work gate may add restrictions but may not clear pressure, emergency, lifecycle, operator, or deployment pauses.
- Keep root emergency mechanics independent of the inference arbiter. Exactly one Sole Survivor owns actual-OOM recovery.
- Extract only owning admission/budget/continuation responsibilities from the existing controller/executor; do not rewrite the repository.
- Main MVP plans own health, autonomy, approval, activation, rollback, and deployment. This plan exposes contracts to them but does not implement those concerns.
- Tests are module-level functions with `load_tests`/`unittest.FunctionTestCase`; run `python3 -m unittest discover -s tests -p 'test_*.py'`.

## File Map and Dependency Order

### Reconciled obligations at the existing owners

These qualify the task contracts below. Fixed-partition examples are valid for
that backend mode, not the complete concurrent interface. Astra binds revised
implementation-only packets to real source/interfaces; local workers do not plan
cross-owner changes. Existing accepted components remain usable, not blanket closure.

| Owner | Required contract and evidence |
| --- | --- |
| Q1/R2/R3 | One `config/inference.cfg` slot/context policy using existing configparser, global defaults and model overrides; remove duplicate slot authorities at activation. Requested policy and observed capacity stay distinct. |
| R2: `ecosystem/models.py` | Qualify native 262144 Qwen context and align `config/executor-opencode.json` with actual allocation. Separate per-request context from aggregate KV/cache; equal division applies only to fixed partitions. Prefer Qwen normally, 4B for contingency. |
| R3: `ecosystem/inference_capacity.py` | Atomic reservation keyed by backend incarnation/model/slot; numeric slot IDs on different backends do not collide. Count resident weights/pools once, not once per agent. |
| R4: `ecosystem/inference_proxy.py` | Complete R4-PRECISE: release one request while another remains busy. Handler capacity follows supported concurrency/control needs, not a hidden four-handler ceiling. |
| R1/R5: worker gate, scheduler, executor | Agent/session lifetime differs from inference-slot lifetime; tool/queue waits do not monopolize slots. N+1 agents on N slots all progress under priority, aging and bounded quanta. |
| R2–R6: selection, admission, execution, continuation | Ordinary memory contention triggers eligible checkpoint/drain, observed request release, unload/load and later resumption. Prefer reuse without starving nonresident demand. Honor explicit operator protection and contingency capacity; do not globally pause unrelated backends. R6 supplies durable continuation where KV restore is unsupported. |
| R7 | Pressure/emergency containment composes with these paths; ordinary model replacement is not a fabricated pressure incident. |

Parent acceptance includes focused overlap, independent release, same-number slots
on distinct backends, oversubscription progress, memory-contended eviction/resume,
and policy resizing that does not mutate live allocations underneath their owners.
G2 requires bounded live overlap and model-turnover evidence too. Controlled smaller
memory budgets exercise contention without host OOM. This is a contract revision;
the historical function examples below are not already a complete implementation
packet for these additional cases.

| Task | Files | Responsibility | Depends on |
| --- | --- | --- | --- |
| R1 | create `ecosystem/workload_control.py`, `tests/test_workload_control.py`; modify `config/time.cfg` | Global gate, caller/process identity, leases, drain, smoke fence | Q1 configuration |
| R2 | modify `ecosystem/models.py`, `config/model-policy.json`, `config/resource-policy.json`; create `tests/test_model_admission.py` | Verified task-qualified model/context routes | R1 request schema |
| R3 | create `ecosystem/inference_capacity.py`, `tests/test_inference_capacity.py`, `config/scheduling.json`; modify `config/resource-policy.json` | Physical capacity and trusted priority policy | R1, R2 only |
| R4 | create `ecosystem/inference_proxy.py`, proxy script/unit, `tests/test_inference_enforcement.py`; modify consumers, model policy and lifecycle allowlist | Sole authenticated backend HTTP/SSE authority | R1–R3 |
| R8 | create `ecosystem/operator_session.py`, `scripts/cointos-opencode`, `tests/test_operator_session.py`; modify R1/R3/resource policy | Explicit lease for user-driven agent sessions, protected model/context ownership and Coin-only preemption | R1–R4 |
| R5 | create `ecosystem/execution_budget.py`, `tests/test_execution_budget.py`; modify `ecosystem/executor.py`, `ecosystem/scheduler.py`, `config/time.cfg` | Budgets, priority consumption, stoppability, fairness | A1 task contracts, R4, R8 |
| R6 | create `ecosystem/continuation.py`, `tests/test_continuation.py`; modify `ecosystem/executor.py` | Destination-sized, backend-neutral context continuation | R2–R5 |
| R7 | modify `ecosystem/resource_control.py`, `tests/test_resource_control.py` | Pressure/OOM/recovery composition | R1–R6 |

---
### R1: Global Work Gate, Worker Leases, and Smoke Exclusion

**Files:**
- Create: `ecosystem/workload_control.py`
- Create: `tests/test_workload_control.py`
- Modify: `config/time.cfg`

**Interfaces:**
- Consumes: Q1 atomic last-known-good configuration snapshots; `root: Path`; callable monotonic/wall clock; durable resource/lifecycle/operator state records.
- Produces:

```python
def acquire_worker(root: Path, request: dict, clock) -> dict
def register_process(root: Path, lease_id: str, pid: int, process_start_ticks: int, clock) -> dict
def begin_drain(root: Path, owner: dict, clock) -> dict
def observe_workers(root: Path, observed_workers: list[dict], clock) -> dict
def enter_smoke(root: Path, owner: dict, clock, observed_workers: list[dict]) -> dict
def end_smoke(root: Path, owner: dict, outcome: dict, clock) -> dict
def release_worker(root: Path, lease_id: str, outcome: dict, clock) -> dict
def admission_reasons(resource_state: dict, lifecycle_state: dict, work_state: dict) -> list[str]
```
`request` carries supplied plain `job_id` and `agent_generation` without importing A1: S0's coordinator ledger supplies implementation-worker identity before A1 exists; A1 supplies later runtime-job identity. Process identity is separate. A local caller acquires `starting`, registers PID/start identity, then may request inference. Never-started ordinary runtime jobs are not B1 roster recipients; a starting implementation lease is valid. Release may leave the logical run continuing/paused; `dead_unreconciled` is never healthy.
**Worker allocation:** Sol-medium owns the durable state/locking review (20 minutes). Local workers may write isolated test cases after interfaces are fixed. The coordinator is the only writer to `workload_control.py` during integration.

- [ ] **Step 1: Add discoverable gate tests (local, small and simple)**

```python
import tempfile
from pathlib import Path
import unittest
from ecosystem import workload_control
def test_drain_closes_acquisition_before_snapshot():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary); clock = lambda: 10.0
        workload_control.begin_drain(root, {"owner_identity": "smoke:one"}, clock)
        request = {"workload_class": "work", "model_id": "model-a",
            "context_tokens": 32768, "max_output_tokens": 2048,
            "deadline_monotonic": 300.0, "owner_identity": "codex:one",
            "job_id": "task-one", "agent_generation": 1,
            "caller_handle": "codex-call:one", "request_id": "request-one",
            "stop_method": "process_group"}
        result = workload_control.acquire_worker(root, request, clock)
        assert result["state"] == "deferred" and "drain" in result["reasons"]
def test_gate_cannot_clear_pressure_or_lifecycle_pause():
    reasons = workload_control.admission_reasons(
        {"mode": "pressure"}, {"paused": True}, {"mode": "open"})
    assert reasons == ["resource:pressure", "lifecycle:paused"]
def load_tests(_loader, _tests, _pattern):
    functions = (test_drain_closes_acquisition_before_snapshot,
                 test_gate_cannot_clear_pressure_or_lifecycle_pause)
    return unittest.TestSuite(unittest.FunctionTestCase(item) for item in functions)
```

- [ ] **Step 2: Run the focused collector (local, 2 minutes)**

Run: `python3 -m unittest discover -s tests -p 'test_workload_control.py' -v`
Expected: FAIL because `ecosystem.workload_control` does not exist.

- [ ] **Step 3: Implement the minimal durable state and lock (Sol-medium, 15–25 minutes)**

Use `fcntl.flock` on `state/workload-control.lock`. Under that lock, atomically write one `state/workload-control.json` containing `mode`, `generation`, `owner`, and leases keyed by `lease_id`. Derive lease IDs from validated `request_id` plus generation; reject duplicate identity with different content. `begin_drain` changes `open -> draining` before returning any active lease snapshot.

```python
def admission_reasons(resource_state, lifecycle_state, work_state):
    reasons = []
    if resource_state.get("mode") != "normal":
        reasons.append(f"resource:{resource_state.get('mode', 'unknown')}")
    if lifecycle_state.get("paused"):
        reasons.append("lifecycle:paused")
    if work_state.get("mode") in {"draining", "smoke"}:
        reasons.append(f"work:{work_state['mode']}")
    return reasons
```

- [ ] **Step 4: Add process/hosted observation tests (local, small and simple)**

Add `test_starting_lease_blocks_smoke_and_inference_until_pid_registration`, `test_pid_reuse_is_not_completion`, `test_checkpoint_without_process_and_request_exit_blocks_smoke`, `test_hosted_writer_blocks_covered_smoke`, and `test_failed_smoke_does_not_clear_pressure`. Pass explicit observations for handle or `(pid, start_ticks)`, process alive, inference requests active, writer and paths. Smoke requires checkpoint when requested plus observed process-group and inference-request exit.

- [ ] **Step 5: Add timing policy and verify R1 (Sol-medium, 15 minutes)**

Add `[workload] maximum_run_seconds = 300`, `wrapup_seconds = 30`, and `termination_grace_seconds = 15` to `config/time.cfg`. These are deadlines for requested actions; only `observe_workers` may establish completion. Run the focused collector, then:

Run: `python3 -m unittest discover -s tests -p 'test_workload_control.py' -v`
Expected: PASS with all R1 tests collected.

- [ ] **Step 6: Commit R1**

```bash
git add ecosystem/workload_control.py tests/test_workload_control.py config/time.cfg
git commit -m "feat: add global worker admission and smoke fence"
```
### R2: Validated Model and Arbitrary Context Selection

**Files:**
- Modify: `ecosystem/models.py`
- Modify: `config/model-policy.json`
- Modify: `config/resource-policy.json`
- Create: `tests/test_model_admission.py`

**Interfaces:**
- Consumes: R1 request fields plus `requirements` (`required_capabilities`, `minimum_context_tokens`, `preferred_model_ids`); verified registry/live allocation records; resource policy.
- Produces:

```python
def safe_routes(inventory: dict, policy: dict, request: dict) -> list[dict]
def choose_route(routes: list[dict], request: dict) -> dict
def validate_route(route: dict, fresh_inventory: dict, policy: dict, request: dict) -> dict
```
Each route records `model_id`, verified `parameter_count`, `model_bytes`, `advertised_context_tokens`, `backend_context_tokens`, `parallel_sequences`, `context_tokens_per_sequence`, `prompt_tokens`, `tool_tokens`, `max_output_tokens`, `handoff_tokens`, KV estimate and exclusion reasons.
**Worker allocation:** Sol-medium owns metadata semantics and selection review (20 minutes). Local workers may independently add one synthetic-envelope test each.

- [ ] **Step 1: Write selection tests without role predicates (local, 5 minutes)**

```python
from ecosystem.models import safe_routes, choose_route
import unittest
def test_new_role_uses_explicit_requirements_without_code_change():
    inventory = {"models": [
        {"id": "small", "parameter_count": 4_000_000_000,
         "size_bytes": 3_000_000_000, "labels": ["tool-calling"],
         "context": 100000, "supported_context_quantum": 1024, "loaded": False},
        {"id": "large", "parameter_count": 27_000_000_000,
         "size_bytes": 18_000_000_000, "labels": ["tool-calling", "coding"],
         "context": 131072, "supported_context_quantum": 1024, "loaded": False}],
        "resource_envelope": {"maximum_model_bytes": 20_000_000_000,
                              "maximum_context_tokens": 98304}}
    request = {"role": "documenter", "requirements": {
        "required_capabilities": ["coding"], "minimum_context_tokens": 32768},
        "max_output_tokens": 4096}
    route = choose_route(safe_routes(inventory, {}, request), request)
    assert route["model_id"] == "large"
    assert route["context_tokens_per_sequence"] == 98304
def load_tests(_loader, _tests, _pattern):
    return unittest.TestSuite((unittest.FunctionTestCase(
        test_new_role_uses_explicit_requirements_without_code_change),))
```

- [ ] **Step 2: Run focused collector (local, 2 minutes)**

Run: `python3 -m unittest discover -s tests -p 'test_model_admission.py' -v`
Expected: FAIL because the new functions are absent.

- [ ] **Step 3: Replace candidate-list and role policy (Sol-medium, 20 minutes)**

Validate registry types and provenance; do not infer parameters or capabilities from names. Filter by explicit task capabilities first. Among qualified safe models, prefer greatest verified `parameter_count`; use `model_bytes` only for the envelope. For each model, compute the largest backend-supported quantum no larger than its advertised maximum and current envelope. Record why every larger model/context was excluded. Missing parameter metadata cannot win the “largest” comparison and is reported, not guessed.

- [ ] **Step 4: Add fresh-validation and reserve tests (local, small and simple)**

Add `test_parameter_count_and_model_bytes_are_distinct`, `test_non_candidate_context_quantum_is_allowed`, `test_total_context_is_divided_across_sequences`, `test_prompt_tool_output_and_handoff_are_reserved`, `test_loaded_model_rechecks_current_pressure`, `test_stale_inventory_defers`, and `test_validate_route_closes_route_load_race`. Build dictionaries inline as above; patch no live endpoints.

- [ ] **Step 5: Remove duplicate semantic routes and verify R2 (Sol-medium, 15 minutes)**

Delete `fallback`, `admitted_or_substitute`, hard-coded `required_labels`/`role_compatible`, and the architectural use of `dynamic_models.context_candidates`; update their old tests to explicit requirement records. Keep a temporary configuration parser only long enough to reject stale configuration, not as a second route.

Run: `python3 -m unittest discover -s tests -p 'test_model_admission.py' -v`
Expected: PASS.

- [ ] **Step 6: Commit R2**

```bash
git add ecosystem/models.py config/model-policy.json config/resource-policy.json tests/test_model_admission.py tests/test_resource_control.py
git commit -m "refactor: validate model and arbitrary context routes"
```
### R3: Physical Front and Work Inference Reservation

**Files:**
- Create: `ecosystem/inference_capacity.py`
- Create: `tests/test_inference_capacity.py`
- Create: `config/scheduling.json`
- Modify: `config/resource-policy.json`

**Interfaces:**

```python
def resource_envelope(host: dict, resident_models: list[dict], active_leases: list[dict], policy: dict) -> dict
def effective_priority(policy: dict, role: str | None, execution_profile: str | None, authority_profile: str, age_seconds: float) -> int
def realize_context_tokens(route: dict, parallel_sequences: int) -> dict
def reserve_sequence(root: Path, request: dict, inventory: dict, clock) -> dict
def release_sequence(root: Path, lease_id: str, observed: dict, clock) -> dict
```
The Coin front sequence remains an exclusive physical allocation even when Sole Survivor has higher scheduler priority. A lease records class, proxy identity, model/context/output allocation, backend sequence, expiry, preemption method, and observed release.
**Worker allocation:** Sol-medium owns the envelope/front isolation review. Local workers write arithmetic tests only.

- [ ] **Step 1: Write physical-capacity tests (local, 5 minutes)**

```python
from ecosystem.inference_capacity import resource_envelope
import unittest
def test_work_cannot_consume_reserved_front_sequence():
    policy = {"front_sequences": 1, "total_sequences": 2,
              "protected_host_bytes": 32 * 1024**3,
              "load_transient_bytes": 12 * 1024**3}
    result = resource_envelope(
        {"available_host_bytes": 80 * 1024**3, "gtt_used_bytes": 20 * 1024**3},
        [], [{"workload_class": "work", "backend_sequence": 1}], policy)
    assert result["available_work_sequences"] == 0
    assert result["reserved_front_sequences"] == 1
def load_tests(_loader, _tests, _pattern):
    return unittest.TestSuite((unittest.FunctionTestCase(
        test_work_cannot_consume_reserved_front_sequence),))
```
- [ ] **Step 2: Confirm failure (local, 2 minutes):** run `python3 -m unittest discover -s tests -p 'test_inference_capacity.py' -v`; expect import failure.

- [ ] **Step 3: Implement byte accounting and transactional sequence reservation (Sol-medium, 20 minutes)**

Account resident model bytes once, active per-sequence KV/prompt/tool/output/handoff demand, load transient, host reserve, GTT boundary, and unknown facts. `realize_context_tokens` maps selected `context_tokens_per_sequence` to lease `context_tokens` and backend `ctx_size = context_tokens * parallel_sequences`, rejecting inconsistent totals. Validate Q1's accepted scheduling snapshot; compute trusted bounded priority. Under R1 lock order, keep front/work proxy identity distinct.

- [ ] **Step 4: Add boundary tests and verify R3 (local, small and simple)**

Add `test_realized_context_maps_per_sequence_to_backend_total`, `test_front_proxy_cannot_be_claimed_by_survivor_or_work`, `test_priority_bands_match_validated_policy`, `test_caller_priority_is_ignored`, `test_aging_cannot_cross_band`, `test_high_priority_arrival_preempts_work_lease`, and `test_release_requires_observed_sequence_end`. Run only `test_inference_capacity.py` here.

- [ ] **Step 5: Commit R3**

```bash
git add ecosystem/inference_capacity.py tests/test_inference_capacity.py config/resource-policy.json config/scheduling.json
git commit -m "feat: reserve physical front inference capacity"
```
### R4: Enforce Every Inference Consumer

**Files:**
- Create: `ecosystem/inference_proxy.py`, `scripts/inference_proxy`, `services/systemd/agent-inference-proxy.service`, `tests/test_inference_enforcement.py`
- Modify: `ecosystem/inference.py`, `ecosystem/identity.py`, `ecosystem/presentation.py`, `ecosystem/control_agent.py`, `ecosystem/telegram.py`, `ecosystem/models.py`, `ecosystem/executor.py`, `config/executor-opencode.json`, `config/model-policy.json`, `config/survival-lifecycle.json`, `tests/test_survival_lifecycle.py`

**Interfaces:**

```python
def request(request: dict, root: Path, clock) -> dict
def cancel(root: Path, lease_id: str, clock) -> dict
def issue_proxy_credential(root: Path, lease: dict, credential_sink, clock) -> dict
def revoke_proxy_credential(root: Path, lease_id: str, observed_end: dict, clock) -> dict
def opencode_environment(root: Path, inference_lease: dict, credential: bytes) -> dict
def authorize_proxy_request(root: Path, metadata: dict, body: dict, clock) -> dict
def handle_proxy_request(root: Path, metadata: dict, body: dict, backend_request, clock) -> dict
def read_proxy_request(connection, limits: dict) -> tuple[dict, dict]
def forward_proxy_response(connection, upstream, lease: dict, observe, clock) -> dict
def serve_one_connection(connection, root: Path, config: dict, clock) -> None
def serve_proxy(root: Path, config: dict, clock) -> None
```
`inference.request` owns semantic messages/tools/format and decoded nonstream result; it talks only to the configurable loopback proxy. The proxy owns authentication, HTTP framing, backend socket/body, SSE bytes, cancellation and closure observation. Authorization bearer digest uniquely resolves persisted lease/owner/request/run binding; optional identity headers must match it. Body model, realized context, output and stream mode must equal the lease. Refusal never calls `backend_request`. Only `inference_proxy.py` owns ordinary completions; privileged `resource_control.py` retains emergency load/unload.
**Worker allocation:** One Sol-medium integrator owns consumer migration. Local workers independently search/test one consumer each; never concurrently edit a shared consumer.

- [ ] **Step 1: Add a functional refusal test (local, 5 minutes)**

```python
import tempfile
from pathlib import Path
import unittest
from ecosystem.inference_proxy import handle_proxy_request
def test_unauthenticated_request_never_reaches_backend():
    backend_calls = []
    with tempfile.TemporaryDirectory() as temporary:
        result = handle_proxy_request(Path(temporary),
            {"authorization": "", "lease_id": "missing", "owner_identity": "worker:one"},
            {"model": "model-a", "max_tokens": 128},
            lambda request: backend_calls.append(request), lambda: 10.0)
    assert result["status"] == 401
    assert backend_calls == []
def load_tests(_loader, _tests, _pattern):
    return unittest.TestSuite((unittest.FunctionTestCase(
        test_unauthenticated_request_never_reaches_backend),))
```
- [ ] **Step 2: Confirm failure (local, 2 minutes):** run `python3 -m unittest discover -s tests -p 'test_inference_enforcement.py' -v`; expect missing proxy module.

- [ ] **Step 3: Implement authenticated proxy admission (Sol-medium, 20 minutes)**

Validate Q1 policy: initial proxy/backend bases `http://127.0.0.1:13306/v1` and `http://127.0.0.1:13305/v1`, 65536 header bytes, 16777216 body bytes, 65536 stream chunks and four connections. Use `urllib.parse.urlsplit`, require `http`, loopback `ipaddress`, `/v1`, and no credentials/query/fragment. Generate `secrets.token_bytes(32)` per run; persist only SHA-256 digest plus owner/lease/run generation. Deliver raw bytes once through `credential_sink`, never logs/environment. Reject before backend unless starting lease and registered process both validate.

- [ ] **Step 4: Build the class-free server and service (Sol-medium, 20 minutes)**

Implement `serve_proxy` with `socket.create_server`, bounded `ThreadPoolExecutor`, bounded read through `\r\n\r\n`, `email.parser.BytesHeaderParser`, required single numeric `Content-Length`, and `http.client.HTTPConnection` upstream; reject transfer encoding, duplicate length and oversized headers/body. Four handlers allow Coin beside an ordinary stream. The user unit runs `scripts/inference_proxy`, has no `PartOf`/`Requires` on executor or gateway, and is guardian-restartable by an exact `control_services` allowlist entry.

```python
import concurrent.futures
import socket

def serve_proxy(root, config, clock):
    with socket.create_server((config["host"], config["port"])) as listener, \
         concurrent.futures.ThreadPoolExecutor(max_workers=config["connections"]) as pool:
        while True:
            connection, _address = listener.accept()
            pool.submit(serve_one_connection, connection, root, config, clock)
```

`serve_one_connection` is a plain function: read one bounded `POST /v1/chat/completions`, call `handle_proxy_request`, forward one response, close. It never implements keep-alive, chunked client upload, routing beyond that exact path, or another protocol.

- [ ] **Step 5: Migrate consumers, deliver credentials, and stream SSE (Sol-medium, 20 minutes)**

Move identity, presentation, control, Telegram, routing, verification and OpenCode to `inference.request`. `credential_sink(secret: bytes) -> None` is called once. For OpenCode, `opencode_environment` writes anonymous `os.memfd_create` JSON containing proxy `baseURL` and bearer `apiKey`, returns `OPENCODE_CONFIG=/proc/self/fd/<n>` plus `pass_fds=(n,)`; parent closes after spawn. Other runners inherit a pipe FD and only its number in environment. Rotate each runner lease/resume, not logical agent generation. For SSE, write upstream status, `Content-Type: text/event-stream`, `Connection: close`, then use `select.select` and `HTTPResponse.read1(65536)`/flush without buffering. Cancellation, timeout or downstream close closes upstream; retain credential until request and run closure are observed, then revoke digest/FD. B2 uses the same boundary. Presentation is not ACK.

- [ ] **Step 6: Add enforcement tests (local, small and simple)**

Add `test_body_limit_refuses_without_backend_call`, `test_released_or_mismatched_lease_never_calls_backend`, `test_unregistered_starting_lease_is_refused`, `test_opencode_memfd_is_inherited_and_secret_absent_from_environment`, `test_sse_chunks_forward_without_buffering`, `test_cancel_closes_upstream_before_revoke`, `test_ordinary_stream_does_not_block_coin_connection`, `test_guardian_allowlist_includes_proxy_without_gateway_dependency`, `test_messaging_uses_same_proxy_contract`, and `test_forwarded_result_is_not_ack`. Use fake sockets/streams and injected backend; no live calls.

- [ ] **Step 7: Run focused collector and commit R4**

Run: `python3 -m unittest discover -s tests -p 'test_inference_enforcement.py' -v`
Expected: PASS; refusal tests prove no backend request occurs before admission.

```bash
git add ecosystem/inference_proxy.py ecosystem/inference.py ecosystem/identity.py ecosystem/presentation.py ecosystem/control_agent.py ecosystem/telegram.py ecosystem/models.py ecosystem/executor.py scripts/inference_proxy services/systemd/agent-inference-proxy.service config/executor-opencode.json config/model-policy.json config/survival-lifecycle.json tests/test_inference_enforcement.py tests/test_survival_lifecycle.py
git commit -m "refactor: enforce one admitted inference path"
```
### R5: Mechanical Budgets, Stoppability, and Fairness

**Files:**
- Create: `ecosystem/execution_budget.py`, `tests/test_execution_budget.py`
- Modify: `ecosystem/executor.py`, `ecosystem/scheduler.py`, `config/time.cfg`

**Interfaces:**

```python
def account_usage(budget: dict, usage: dict, event: dict) -> dict
def budget_outcome(budget: dict, usage: dict, now_monotonic: float) -> dict
def record_budget_handoff(outcome: dict, artifact: dict) -> dict
def stop_process_group(pid: int, wrapup_seconds: float, grace_seconds: float, observe) -> dict
```
Consumes A1's `task_contracts.validate_budget(raw) -> dict`, `validate_task_contract(raw) -> dict`, and `narrow_contract(parent, child) -> dict`; R5 does not duplicate schema validation. A rollover is not an attempt failure; cumulative task budget remains authoritative.
**Worker allocation:** Sol-medium owns contract/state integration. Local workers implement isolated arithmetic/process-observation tests.

- [ ] **Step 1: Write a complete budget test (local, 5 minutes)**

```python
from ecosystem.execution_budget import budget_outcome
import unittest
def test_output_limit_yields_partial_handoff():
    budget = {"run_seconds": 300, "task_seconds": 900,
              "maximum_attempts": 3, "maximum_output_bytes": 100,
              "maximum_evidence_items": 4, "maximum_children": 1}
    usage = {"run_started": 0.0, "task_started": 0.0, "attempts": 1,
             "output_bytes": 101, "evidence_items": 1, "children": 0}
    result = budget_outcome(budget, usage, 10.0)
    assert result == {"state": "checkpoint_required",
                      "reason": "maximum_output_bytes"}
def load_tests(_loader, _tests, _pattern):
    return unittest.TestSuite((unittest.FunctionTestCase(
        test_output_limit_yields_partial_handoff),))
```
- [ ] **Step 2: Confirm failure (local, 2 minutes):** run `python3 -m unittest discover -s tests -p 'test_execution_budget.py' -v`; expect missing `execution_budget`.

- [ ] **Step 3: Integrate A1 validation and add accounting (Sol-medium, 15 minutes)**

Require A1-validated contracts at dispatch and account all six fields without re-parsing. Charge `task_seconds` only for observed `running` intervals; approval, queue, drain and pause waits cost no running budget. Consume R3's trusted priority helper; unknown roles stay below 700 and aging cannot cross bands.

- [ ] **Step 4: Extract process enforcement from executor (Sol-medium, 20 minutes)**

Replace fixed 1800 seconds with task budget. At 300 seconds request 30-second wrap-up, then SIGTERM and observe matching PID/start identity for 15 seconds before SIGKILL. Exhaustion first persists `checkpoint_required`; only `record_budget_handoff` may produce `partial_handoff_ready`, after verifying a nonempty durable artifact bound to job/generation. A timer never proves completion.

- [ ] **Step 5: Add budget/fairness tests (local, small and simple)**

Add `test_missing_handoff_stays_checkpoint_required`, `test_verified_handoff_enters_partial_handoff_ready`, `test_approval_wait_does_not_consume_task_seconds`, `test_running_interval_consumes_task_seconds`, `test_pid_reuse_is_not_killed`, `test_scheduler_consumes_effective_priority`, `test_survivor_preempts_work_without_starving_coin`, and `test_short_jobs_rotate_without_starvation`.

- [ ] **Step 6: Run focused collector and commit R5**

Run `python3 -m unittest discover -s tests -p 'test_execution_budget.py' -v`. Expected: PASS; no full-suite run in R5.

```bash
git add ecosystem/execution_budget.py ecosystem/executor.py ecosystem/scheduler.py config/time.cfg tests/test_execution_budget.py tests/test_executor.py tests/test_scheduler.py
git commit -m "feat: enforce task contracts and execution budgets"
```
### R6: Seamless Context Continuation Across Models and Windows

**Files:**
- Create: `ecosystem/continuation.py`, `tests/test_continuation.py`
- Modify: `ecosystem/executor.py`

**Interfaces:**

```python
def observe_context_usage(adapter_event: dict, lease: dict) -> dict
def context_transition(job: dict, usage: dict, rollover_fraction: float) -> dict
def handoff_budget(destination_lease: dict) -> dict
def prepare_continuation(job: dict, handoff: dict | None, artifacts: dict, destination_lease: dict) -> dict
```
**Worker allocation:** Sol-medium owns the state-machine review. Local workers add crash-boundary cases with synthetic JSONL.

- [ ] **Step 1: Write model/window transfer test (local, 5 minutes)**

```python
from ecosystem.continuation import prepare_continuation
import unittest
def test_task_identity_survives_smaller_destination():
    job = {"id": "task-one", "agent_generation": 7, "context_generation": 2}
    destination = {"model_id": "smaller", "context_tokens": 16384,
                   "prompt_tokens": 8000, "handoff_tokens": 2000,
                   "tool_tokens": 2000, "max_output_tokens": 4384}
    result = prepare_continuation(
        job, {"summary": "bounded", "token_count": 1800},
        {"evidence_paths": ["logs/task-one.context-2.jsonl"]}, destination)
    assert result["id"] == "task-one" and result["agent_generation"] == 7
    assert result["context_generation"] == 3 and result["model_id"] == "smaller"
def load_tests(_loader, _tests, _pattern):
    return unittest.TestSuite((unittest.FunctionTestCase(
        test_task_identity_survives_smaller_destination),))
```
- [ ] **Step 2: Confirm failure (local, 2 minutes):** run `python3 -m unittest discover -s tests -p 'test_continuation.py' -v`; expect missing `continuation`.

- [ ] **Step 3: Implement explicit idempotent transitions (Sol-medium, 20 minutes)**

Implement `running -> handoff_requested -> handoff_durable -> continuation_ready`. Preserve `job_id` and `agent_generation` through context/model change, process restart and `paused_for_resources`; increment only context generation. A genuinely new A1 attempt increments agent generation. Reserve destination prompt/output/tool/handoff before handoff; archive evidence by reference. Missing semantic handoff remains visibly continuable.

- [ ] **Step 4: Add arbitrary-window/crash tests (local, small and simple)**

Add `test_rollover_precedes_backend_limit`, `test_handoff_fits_destination_prompt_budget`, `test_model_switch_preserves_agent_generation`, `test_process_restart_preserves_agent_generation`, `test_new_attempt_increments_agent_generation`, `test_paused_for_resources_remains_addressable_without_lease`, `test_missing_handoff_is_visible_and_continues`, and `test_context_overflow_is_never_terminal`.

- [ ] **Step 5: Remove monolithic duplicate transitions and verify R6 (Sol-medium, 15 minutes)**

Have `executor.py` call `continuation` functions and delete its inline handoff/rollover state mutation after tests pass. Preserve durable OpenCode session/event parsing as the adapter. Run only `python3 -m unittest discover -s tests -p 'test_continuation.py' -v` here.

- [ ] **Step 6: Commit R6**

```bash
git add ecosystem/continuation.py ecosystem/executor.py tests/test_continuation.py tests/test_executor.py
git commit -m "refactor: make context continuation backend neutral"
```
### R7: Compose Pressure, Actual OOM, and Deterministic Recovery

**Files:**
- Modify: `ecosystem/resource_control.py`
- Modify: `tests/test_resource_control.py`

**Interfaces:**
- Consumes: R1 drain/gate state, R3/R4 sequence leases, R5 checkpoint outcome, R6 continuation state, existing `resource_snapshot`, `confirmed_threshold`, and emergency phases.
- Produces existing `tick() -> dict`, with durable lease reconciliation and independently observed reopen conditions.

**Worker allocation:** Sol-medium owns the final cross-contract review (25 minutes). Local workers add isolated reducer cases only.

- [ ] **Step 1: Add pressure ordering test (local, 5 minutes)**

```python
import unittest
from unittest.mock import patch
from ecosystem import resource_control
def test_pressure_closes_gate_before_checkpoint():
    events = []
    with patch("ecosystem.resource_control.workload_control.begin_drain",
               side_effect=lambda *args: events.append("gate") or {"mode": "draining"}), \
         patch("ecosystem.resource_control.checkpoint_running_jobs",
               side_effect=lambda *args: events.append("checkpoint") or []), \
         patch("ecosystem.resource_control._stop_user_units", return_value={"ok": True}), \
         patch("ecosystem.resource_control.unload_dynamic_models", return_value=[]), \
         patch("ecosystem.resource_control.save_state"):
        resource_control.enter_pressure({"mode": "normal"}, {"at": "now"})
    assert events == ["gate", "checkpoint"]
def load_tests(_loader, _tests, _pattern):
    return unittest.TestSuite((unittest.FunctionTestCase(
        test_pressure_closes_gate_before_checkpoint),))
```
- [ ] **Step 2: Confirm failure (local, 2 minutes):** run `python3 -m unittest discover -s tests -p 'test_resource_control.py' -v`; expect missing gate composition.

- [ ] **Step 3: Compose normal-to-pressure without weakening existing reactions (Sol-medium, 20 minutes)**

Close R1 first, checkpoint R5/R6 state, stop clients, observe matching process/sequence release, then unload. Sustained healthy samples may request reopen, but effective admission remains closed while any lifecycle/operator/smoke restriction exists.

- [ ] **Step 4: Keep actual OOM distinct and survivor-exclusive (Sol-medium, 20 minutes)**

An increment in boot-bound `oom_kill` enters emergency immediately, preserves Coin's physical front slot, preempts/reconciles replaceable running leases, and admits exactly the recorded highest-priority Sole Survivor. Pre-OOM pressure never fabricates OOM. Survivor assertions cannot reopen; deterministic host/GTT/swap/PSI, Coin contact, process, and lease observations pass independently. Root recovery never depends on R4.

- [ ] **Step 5: Add recovery tests (local, small and simple)**

Add `test_pressure_is_not_oom`, `test_one_new_oom_latches_exactly_one_survivor`, `test_survivor_preempts_work_but_not_coin_front`, `test_recovery_reconciles_leases_before_reopen`, `test_reopen_cannot_clear_lifecycle_pause`, `test_survivor_claim_cannot_replace_observed_health`, and `test_pending_context_continues_after_pressure`.

- [ ] **Step 6: Run focused resource collector (Sol-medium, 15 minutes)**

Run: `python3 -m unittest discover -s tests -p 'test_resource_control.py' -v`
Expected: PASS. No test deliberately causes host pressure, loads a model, or contacts a service.

- [ ] **Step 7: Commit R7**

```bash
git add ecosystem/resource_control.py tests/test_resource_control.py
git commit -m "feat: compose worker leases with survival recovery"
```
## Interface Dependency Crosscheck

- R1 owns worker/gate identity without importing A1: S0 or A1 supplies plain job/generation facts; R1 validates them and owns `acquire_worker`, `register_process`, drain/observe/smoke and release. B1 reads authoritative job/R1 state rather than keeping a shadow roster.
- R2 owns model choices: `safe_routes`, `choose_route`, and fresh `validate_route`; it consumes explicit A1 task requirements and R1 request facts.
- R3 owns physical facts: `resource_envelope`, `effective_priority`, `realize_context_tokens`, and sequence reserve/release; R4 and R5 consume them.
- R4 owns ordinary HTTP: semantic `request`/`cancel`, credential issue/revoke, OpenCode memfd environment, proxy authorization/handling/service. B2 calls `request`; only R7's privileged lifecycle bypass remains.
- R5 owns running-budget effects: `account_usage`, `budget_outcome`, verified `record_budget_handoff`, and process-group stop; A1 alone validates task/budget schema.
- R6 owns context state: usage observation, transition, destination handoff budget, and continuation while preserving A1 job/agent generation.
- R7 composes existing `tick()` pressure/emergency phases with R1–R6; it neither owns ordinary inference nor depends on the proxy for root recovery.
## Final Resource Slice Verification

- [ ] **Static contract review (Sol-medium, 20 minutes):** confirm every new signature above matches consumers; no hard-coded role branch or fixed context candidate remains; all user-plane inference reaches R4; root emergency remains independent.
- [ ] **Collector review (local, 2 minutes):** run `python3 -m unittest discover -s tests -p 'test_*.py'` and retain exact count/output as evidence.
- [ ] **Endpoint scan (local, 2 minutes):** run `rg -n '/v1/(chat/completions|load|unload)' ecosystem` and verify completions exist only in `inference_proxy.py`; privileged emergency load/unload remain only in `resource_control.py`.
- [ ] **State-machine scan (local, 2 minutes):** run `rg -n 'context_overflow|handoff_requested|continuation_ready|partial_handoff_ready' ecosystem tests` and verify overflow is assertion/input evidence, never a terminal task state.
- [ ] **Diff review (Sol-medium, 15 minutes):** run `git diff --check` and `git status --short`; inspect only R1–R7 files and reject unrelated changes.

Stop each implementation packet at its scoped checks and independent diff review.
Parent closure also requires the reconciled obligations above; historical tests
alone cannot close it. Live loading and acceptance are separately scoped,
operator-authorized runs, not unit-test effects. The coordinator carries their
evidence into G2. Services, credentials, Telegram and release activation do not
change merely because a worker implements this plan.
