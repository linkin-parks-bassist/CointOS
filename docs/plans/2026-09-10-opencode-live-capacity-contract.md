# OpenCode Live Capacity Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every managed or plain interactive OpenCode launch derive compatible limits from the live backend and reject unprovable capacity before inference.

**Architecture:** Extend the existing backend-layout representation into one pure, version-bound effective-capacity record. Feed that record through one ephemeral OpenCode configuration encoder used by both CointOS workers and a non-recursive `opencode` wrapper; classify `finish: length` as incomplete at the outcome boundary.

**Tech Stack:** Python 3 standard library, plain data/functions, Bash launcher fingertip, OpenCode 1.18.x, Lemonade 11.9.x, unittest/pytest-compatible function tests.

**Spec:** `docs/specs/2026-09-10-opencode-live-capacity-contract-design.md`

## Global Constraints

- This repository is personal orchestration infrastructure; do not copy professional task contents into it.
- Do not use classes or hidden mutable object state.
- Runtime capacity comes from fresh, incarnation-bound backend evidence; missing evidence fails closed.
- Preserve append-only runtime JSONL and never store credentials or prompts in capacity attestations.
- Do not activate wrappers, restart Lemonade, or alter live model allocation without David's explicit approval at the activation gate.
- Treat `finish: "length"`, context overrun, transport error, and successful semantic completion as distinct outcomes.

---

### Task 1: Pure effective-capacity representation

**Files:**
- Create: `ecosystem/opencode_capacity.py`
- Create: `tests/test_opencode_capacity.py`

**Interfaces:**
- Consumes: normalized records from `context_layout.observed_context_layout(...)`, backend/model incarnation evidence, an OpenCode version-capability record, policy output reserve, observation time, and prompt estimate.
- Produces: `effective_inference_capacity(observation, client_capability, policy, now) -> dict` and explicit `ValueError` failures.

- [ ] **Step 1: Write failing tests for the canonical record**

Cover exact model/incarnation identity, fixed and shared per-request context, client version, effective output, rollover threshold, observation identity/time, and evidence reference.

- [ ] **Step 2: Run the focused tests and confirm the missing module failure**

Run: `python3 -m pytest tests/test_opencode_capacity.py -q`

- [ ] **Step 3: Implement the smallest pure constructor and validators**

Use functions over copied plain dictionaries. Reject booleans as integers, unknown keys needed for authority, non-positive capacities, output not smaller than context, stale observations, and prompt-plus-output overflow.

- [ ] **Step 4: Add disagreement and provenance tests**

Cover model mismatch, backend-incarnation mismatch, unqualified OpenCode version, configured values exceeding effective values, absent evidence, and shared-pool values which are incorrectly multiplied or divided.

- [ ] **Step 5: Run focused tests**

Run: `python3 -m pytest tests/test_opencode_capacity.py tests/test_context_layout.py -q`

- [ ] **Step 6: Commit the pure boundary**

```bash
git add ecosystem/opencode_capacity.py tests/test_opencode_capacity.py
git commit -m "feat: derive opencode capacity from live evidence"
```

### Task 2: Version-qualified OpenCode capability

**Files:**
- Create: `config/opencode-capabilities.json`
- Create: `ecosystem/opencode_client.py`
- Create: `tests/test_opencode_client.py`
- Modify: `docs/operations.md`

**Interfaces:**
- Consumes: the literal output of `/home/david/.opencode/bin/opencode --version` and the checked-in qualification catalogue.
- Produces: `qualified_opencode_capability(version_text, catalogue) -> dict`; no default for unknown versions.

- [ ] **Step 1: Write failing tests for exact version binding**

Require OpenCode 1.18.30 to resolve to its observed 32000-token output ceiling. Reject unknown, malformed, duplicate, or non-positive entries.

- [ ] **Step 2: Run the focused test and confirm failure**

Run: `python3 -m pytest tests/test_opencode_client.py -q`

- [ ] **Step 3: Implement the reader and checked-in qualification**

Keep the file a capability catalogue, not desired model policy. Document the evidence command and date without embedding session contents.

- [ ] **Step 4: Document the requalification procedure**

Specify a bounded fake-endpoint or request-capture probe for a new OpenCode version. Do not infer the cap from `context / 3` or force a full-length live generation.

- [ ] **Step 5: Run focused tests**

Run: `python3 -m pytest tests/test_opencode_client.py tests/test_opencode_capacity.py -q`

- [ ] **Step 6: Commit the client capability boundary**

```bash
git add config/opencode-capabilities.json ecosystem/opencode_client.py tests/test_opencode_client.py docs/operations.md
git commit -m "feat: qualify opencode output capability by version"
```

### Task 3: Fresh backend-capacity observation adapter

**Files:**
- Modify: `ecosystem/models.py`
- Modify: `ecosystem/context_layout.py`
- Modify: `tests/test_model_admission.py`
- Modify: `tests/test_context_layout.py`

**Interfaces:**
- Consumes: Lemonade health records, exact backend launch command, `/props` or `/slots` metadata, monotonic observation time, and backend process identity.
- Produces: `observe_opencode_backend_capacity(...) -> dict | None`, suitable for the pure constructor and bound to one backend incarnation.

- [ ] **Step 1: Write failing projection tests at the current observation owner**

Extend the existing `models._observed_resident_record(...)` fixture path. Assert its
verified record carries sufficient backend process/incarnation, observation-time,
allocation-mode, per-request-context, aggregate-pool, and provenance facts for the
capacity constructor. Do not create a duplicate HTTP/process observer.

- [ ] **Step 2: Write failing fixed-layout and shared-layout adapter tests**

Use literal captured-shaped fixtures with secrets and paths removed. Assert per-request context separately from aggregate pool and trained maximum.

- [ ] **Step 3: Run the focused tests and confirm the missing projection**

Run: `python3 -m pytest tests/test_model_admission.py tests/test_context_layout.py -q`

- [ ] **Step 4: Implement the narrow observation projection**

Reuse `observed_context_layout`; add identity/freshness fields at the observation boundary. Return explicit absence for contradictions rather than choosing a convenient source.

- [ ] **Step 5: Run backend and policy tests**

Run: `python3 -m pytest tests/test_model_admission.py tests/test_context_layout.py tests/test_inference_policy.py -q`

- [ ] **Step 6: Commit the live observation adapter**

```bash
git add ecosystem/models.py ecosystem/context_layout.py tests/test_model_admission.py tests/test_context_layout.py
git commit -m "feat: observe effective opencode backend capacity"
```

### Task 4: One ephemeral OpenCode configuration encoder

**Files:**
- Modify: `ecosystem/inference_proxy.py`
- Modify: `tests/test_inference_enforcement.py`
- Modify: `config/executor-opencode.json`

**Interfaces:**
- Consumes: an `effective_inference_capacity` record plus base non-capacity OpenCode configuration.
- Produces: `opencode_environment(...)` with an anonymous config whose selected model limits exactly equal the effective record.

- [ ] **Step 1: Write failing tests proving static limits cannot escape**

Seed base configuration with deliberately excessive context/output values. Assert the memfd contains only effective values and preserves unrelated permissions/provider options.

- [ ] **Step 2: Run the focused tests and confirm current behavior permits independent lease values**

Run: `python3 -m pytest tests/test_inference_enforcement.py -q`

- [ ] **Step 3: Refactor the encoder to accept the validated record**

Keep credential population and ownership unchanged. Do not add a second config writer.

- [ ] **Step 4: Remove authoritative capacity claims from the base managed catalogue**

Retain names and non-capacity configuration only where OpenCode schema permits. If schema requires placeholder limits, make the encoder reject use before replacement and test that invariant.

- [ ] **Step 5: Run focused proxy and capacity tests**

Run: `python3 -m pytest tests/test_inference_enforcement.py tests/test_opencode_capacity.py tests/test_opencode_client.py -q`

- [ ] **Step 6: Commit the common encoder**

```bash
git add ecosystem/inference_proxy.py tests/test_inference_enforcement.py config/executor-opencode.json
git commit -m "refactor: encode one validated opencode capacity"
```

### Task 5: Validate managed launches against live capacity

**Files:**
- Modify: `ecosystem/executor.py`
- Modify: `tests/test_executor.py`
- Modify: `tests/test_inference_capacity.py`

**Interfaces:**
- Consumes: admitted inference lease, fresh observed backend record, and qualified OpenCode capability.
- Produces: validated effective record before `opencode_environment`; no child process or inference request on disagreement.

- [ ] **Step 1: Write failing no-spawn tests**

Cover stale evidence, changed backend incarnation, model mismatch, lease context above live cap, and lease output above 32000 for OpenCode 1.18.30.

- [ ] **Step 2: Run focused tests and confirm the current gap**

Run: `python3 -m pytest tests/test_executor.py tests/test_inference_capacity.py -q`

- [ ] **Step 3: Wire the preflight at the final pre-spawn boundary**

Acquire observations before creating the gate or credential. Persist only sanitized failure facts through existing audit owners.

- [ ] **Step 4: Prove matched launches preserve existing behavior**

Assert command construction, observable launcher use, credential ownership, cancellation, and release behavior are unchanged after successful validation.

- [ ] **Step 5: Run focused executor/proxy tests**

Run: `python3 -m pytest tests/test_executor.py tests/test_inference_capacity.py tests/test_inference_enforcement.py -q`

- [ ] **Step 6: Commit managed-launch validation**

```bash
git add ecosystem/executor.py tests/test_executor.py tests/test_inference_capacity.py
git commit -m "feat: validate worker capacity before opencode launch"
```

### Task 6: Plain `opencode` launcher

**Files:**
- Create: `scripts/opencode`
- Create: `ecosystem/interactive_opencode.py`
- Create: `tests/test_interactive_opencode.py`
- Modify: `docs/operations.md`

**Interfaces:**
- Consumes: original OpenCode arguments/environment, selected model, live backend observation, client qualification, and base user configuration.
- Produces: an `exec` of `/home/david/.opencode/bin/opencode` with an anonymous validated config; nonzero diagnostic before exec on failure.

- [ ] **Step 1: Write failing argument and failure-boundary tests**

Use a fake raw executable and fake observation source. Test exact argument, cwd, stdin/stdout/stderr, exit, and signal behavior; prove no recursive PATH lookup.

- [ ] **Step 2: Write failing configuration-preservation tests**

Preserve plugins, MCP, presentation, and provider names from a fixture while replacing selected-model capacity. Reject ambiguous model selection and unavailable backend identity.

- [ ] **Step 3: Run the focused tests and confirm the launcher is absent**

Run: `python3 -m pytest tests/test_interactive_opencode.py -q`

- [ ] **Step 4: Implement the launcher fingertip**

Keep Bash to locating the repository and `exec python3`; keep observation, validation, and config construction in ordinary functions. Do not mutate `/home/david/.config/opencode/opencode.json`.

- [ ] **Step 5: Document installation without activating it**

Specify replacing `/home/david/.local/bin/opencode` only at the later activation gate, retaining `/home/david/.opencode/bin/opencode` as the raw versioned executable and providing an explicit diagnostic/raw escape command.

- [ ] **Step 6: Run focused tests**

Run: `python3 -m pytest tests/test_interactive_opencode.py tests/test_opencode_capacity.py tests/test_opencode_client.py -q`

- [ ] **Step 7: Commit the inactive launcher**

```bash
git add scripts/opencode ecosystem/interactive_opencode.py tests/test_interactive_opencode.py docs/operations.md
git commit -m "feat: prepare live-validated interactive opencode launcher"
```

### Task 7: Length-stop outcome semantics

**Files:**
- Modify: `ecosystem/executor.py`
- Modify: `ecosystem/resource_control.py`
- Modify: `tests/test_executor.py`
- Modify: `tests/test_resource_control.py`
- Create: `tests/fixtures/opencode_length_stop.jsonl`

**Interfaces:**
- Consumes: OpenCode JSONL step-finish/message events.
- Produces: normalized semantic outcome distinguishing `completed`, `tool_boundary`, `length_incomplete`, `context_overrun`, and `transport_failed`.

- [ ] **Step 1: Add a minimal sanitized Quill-shaped length fixture**

Include `finish: "length"`, positive usage, and process return code zero without retaining generated RTL or professional contents.

- [ ] **Step 2: Write failing semantic-outcome tests**

Assert length cannot mark a job complete or release it as successful. Assert transport 200 and process zero do not override the finish reason.

- [ ] **Step 3: Run focused tests and observe the misleading success path**

Run: `python3 -m pytest tests/test_executor.py tests/test_resource_control.py -q`

- [ ] **Step 4: Implement the normalized outcome and persistence**

Preserve the OpenCode session and emit a visible incomplete boundary. Do not add automatic continuation in this task.

- [ ] **Step 5: Run focused continuation and executor tests**

Run: `python3 -m pytest tests/test_executor.py tests/test_resource_control.py tests/test_preemption.py -q`

- [ ] **Step 6: Commit semantic termination handling**

```bash
git add ecosystem/executor.py ecosystem/resource_control.py tests/test_executor.py tests/test_resource_control.py tests/fixtures/opencode_length_stop.jsonl
git commit -m "fix: preserve opencode length stops as incomplete"
```

### Task 8: Full verification and activation gate

**Files:**
- Modify: `docs/operations.md`
- Modify: `docs/status.md`
- Modify: `agent_notes/0024-opencode-live-capacity-contract.md`

**Interfaces:**
- Consumes: all prior task results and a deliberately bounded live backend observation.
- Produces: verified but inactive release candidate, followed only with separate approval by installation of the plain-command wrapper.

- [ ] **Step 1: Run the complete test suite**

Run: `python3 -m pytest -q`

- [ ] **Step 2: Inspect the exact diff and executable modes**

Run: `git diff --check && git status --short && git diff --stat`

- [ ] **Step 3: Run an unprivileged fake-endpoint integration probe**

Prove both launch paths issue identical selected-model limits and failed preflight issues no request.

- [ ] **Step 4: Perform the bounded live read-only preflight**

Display the loaded model/incarnation, fixed/shared layout, per-request context, OpenCode version cap, effective output, and rollover point. Do not launch inference yet.

- [ ] **Step 5: Stop for David's activation approval**

Present the derived live record, test evidence, exact symlink change proposed for `/home/david/.local/bin/opencode`, rollback command, and any incompatibility. Do not change the symlink or services without explicit approval.

- [ ] **Step 6: After approval, activate and test plain and managed launches**

Use short deterministic prompts, inspect captured request limits and finish reasons, and verify no service/model restart was needed. Restore the prior symlink immediately if command resolution or signal propagation differs.

- [ ] **Step 7: Consolidate operations and agent notes**

Record observed versions, active command resolution, live capacity evidence, acceptance results, and remaining uncertainty. Remove superseded capacity claims rather than appending contradictions.

- [ ] **Step 8: Commit activation documentation separately**

```bash
git add docs/operations.md docs/status.md agent_notes/0024-opencode-live-capacity-contract.md
git commit -m "docs: record live opencode capacity activation"
```
