# CointOS MVP Spontaneous Work Implementation Plan

## Original-thesis acceptance — 2026-09-07

A1–A3 remain the owners of extensible roles and spontaneous grounded discovery;
no separate scheduler per role or compulsory manufactured backlog. Role definitions,
validated access and schedule configuration should suffice for new applications.
A5/G2 must exercise the full composition: a role discovers useful work without a
fresh user task, runs under concurrent/contended admission, initiates authorized
remote contact via C3, and receives a reply through B4/Coin after its runner ends.
Generation and unsolicited egress are separate capabilities; neither is proven by
an ordinary reply or a prewritten task. The Reminder example probes the general
interfaces, not an additional bespoke MVP service. See the canonical spec/index.

> **For agentic workers:** Use superpowers:subagent-driven-development or superpowers:executing-plans for the assigned task only.

**Goal:** Let local agents discover useful work, contribute within distinct roles, and hand off results without waiting for a user task.

**Architecture:** One deterministic scheduler selects due scoped discovery jobs. Role descriptions remain Markdown, executable work remains existing jobs with explicit contracts, and observations/proposals remain ordinary notes. One validated enqueue boundary controls children, deduplication and authority.

**Tech Stack:** Python standard library, existing jobs/executor, local inference, Markdown, JSON configuration, systemd.

**Spec:** [MVP design](../specs/2026-09-05-cointos-mvp-design.md).

## Global constraints

- Read the spec and [swarm contract](2026-09-05-cointos-mvp-swarm.md).
- Coin availability, no OOM and seamless dynamic-context handovers remain mandatory.
- Add roles without scheduler/executor source edits. Role names never grant authority.
- Initial ambient scope is personal CointOS; exclude credentials, private conversation bodies and other projects.
- Candidate writes occur in isolated workspaces; activation requires Coin approval under P1-P4.
- Local work is one small, simple task per dispatch; no autonomous recursion or queue growth outside shared budgets.
- Use the function-test collector from the swarm contract; no classes or new dependencies.

## A1 — Explicit task contract and extensible role contexts

Post-MVP successor D11 builds on this context boundary: maintained repo orientation,
fresh trusted-within-scope dispatch briefs, Lecturer topic artifacts, independent
lecture audit tasks and durable topic Advisers. See [the bounded D11 plan](2026-09-08-cointos-context-knowledge.md)
and decision 0020. These are explicit intended work, not additions to A1 acceptance.
Use existing role/job/mailbox/budget contracts and D9 adapters; do not add special
scheduler branches or recurring role schedules during this documentation phase.

**Owner/budget:** Sol medium, 20 minutes. Local jobs: one role file or one specified validator/test.
**Depends on:** R1. R5 consumes this task's budget validator; do not create a reverse dependency.
**Files:** create `ecosystem/task_contracts.py`, `roles/janitor.md`, `roles/gardener.md`,
`roles/documenter.md`, `roles/innovator.md`, `roles/speculator.md`, `tests/test_mvp_task_contracts.py`;
modify `ecosystem/cli.py`, `ecosystem/roles.py`, `config/workspaces.json`, `roles/_base.md`.
**Interfaces:** `validate_task_contract(raw: dict) -> dict`;
`narrow_contract(parent: dict, child: dict) -> dict`;
extend `cli.enqueue_task(..., task_contract: dict | None = None) -> str` for all new producers.
At the existing durable execution claim, initialize `agent_generation=1`; increment
only for a genuinely new task attempt, never R6 context/model/process continuation.
Persist `logical_run_state: active|continuing|paused_for_resources|terminal` in the
job's existing execution record. R1 leases carry `job_id` and `agent_generation`;
B1 projects addressability from this record plus observed leases, not PID alone.
Unexpected process death remains `dead_unreconciled` evidence until the existing
recovery transition chooses continuation or termination; do not claim it healthy.
The same enqueue owner exposes `enqueue_child(parent_job: dict, child_contract: dict,
idempotency_key: str) -> str`; it atomically reserves the shared remaining budget and
creates or recovers one child job. Child contract is not the positional `role` argument
to `enqueue_task`.
Missing contracts on new executable work fail explicitly; update current producers in the same
integration change. Existing queued records are converted once from explicit source authority or
left visibly paused for review; never guess broad write authority from old prose.

- [ ] Write narrow-scope and unknown-role tests. This complete budget test needs no fixture:

```python
from ecosystem.task_contracts import validate_budget

def test_budget_is_explicit_and_positive():
    value = {"run_seconds": 300, "task_seconds": 900, "maximum_attempts": 2,
             "maximum_output_bytes": 65536, "maximum_evidence_items": 20,
             "maximum_children": 1}
    assert validate_budget(value) == value
    try:
        validate_budget({**value, "run_seconds": 0})
    except ValueError:
        pass
    else:
        raise AssertionError("zero run budget accepted")
```

  Public `validate_budget(raw: dict) -> dict` is owned here and consumed by R5.
- [ ] Run `python3 -m unittest discover -s tests -p 'test_mvp_task_contracts.py' -v`.
- [ ] Validate absolute workspace paths, explicit read/write sets, objective, acceptance, budget,
  source key, parent identity and stop condition. Child scope/authority must be a subset and
  budget drawn from the remaining parent allocation. Reject path escapes after canonicalization.

```python
if not set(child["scope"]["write_paths"]) <= set(parent["scope"]["write_paths"]):
    raise ValueError("child widens write scope")
if child["budget"]["task_seconds"] > parent["remaining_task_seconds"]:
    raise ValueError("child exceeds remaining shared budget")
```

  Paths in that example are validated canonical scope roots, not unchecked strings;
  nested permitted paths use explicit containment checks at the path fingertip.
- [ ] Write five role descriptions using the existing mission/evidence/permissions/budget/handoff
  shape. Janitor handles notes/artifact organization; Gardener small code cleanup; Documenter
  grounded descriptions; Innovator proposals only; Speculator observations/questions only.
  Base context explains inspect -> contribute -> finish, including useful partial work and
  honest no-op. A temporary new role resolves through the same role loader without editing code.
- [ ] Update enqueue callers and run existing role/intake/verification checks. Remove fixed
  role-to-capability predicates in favor of task requirements in coordination with R2. Commit
  integration only when all current task producers supply an explicit contract.
**Acceptance/stop:** a new role is addable as data; unknown advisory role neither rejects a valid
contract nor widens permissions; child contract cannot outgrow its parent.

## A2 — Bounded environmental inspection with evidence references

**Owner/budget:** Sol medium, 15 minutes. Local child: read pagination/check tests.
**Depends on:** A1, R5.
**Files:** create `ecosystem/evidence.py`, `tests/test_mvp_evidence.py`; modify
the executor's discovery-tool adapter in `ecosystem/executor.py` and `roles/_base.md`.
**Interfaces:** `read_evidence(scope: dict, relative_path: str, cursor: int, limits: dict) -> dict`;
`record_contribution(root: Path, job: dict, relative_path: str, text: str) -> dict`.
Result fields: `path`, `digest`, `observed_at`, `text`, `next_cursor`, `truncated`, `items_read`.
Limits: remaining `maximum_bytes` and `maximum_items`; count across calls, not per call only.

- [ ] Add the containment example and bounded-tail test:

```python
from pathlib import Path
from tempfile import TemporaryDirectory
from ecosystem.evidence import read_evidence

def test_evidence_reader_rejects_escape():
    with TemporaryDirectory() as tmp:
        scope = {"workspace": tmp, "read_paths": [str(Path(tmp) / "agent_notes")],
                 "write_paths": []}
        try:
            read_evidence(scope, "../outside", 0, {"maximum_bytes": 2048, "maximum_items": 1})
        except ValueError:
            pass
        else:
            raise AssertionError("scope escape accepted")
```

- [ ] Run `python3 -m unittest discover -s tests -p 'test_mvp_evidence.py' -v`.
- [ ] Implement canonical-path validation including symlinks, bounded file reads and event-tail
  paging, observation time/digest, and explicit truncation. Evidence discovery uses supplied
  non-secret scope roots and bounded runtime projections; it cannot scan all `/home/david`.

```python
remaining = limits["maximum_bytes"]
chunk = stream.read(remaining + 1)
truncated = len(chunk) > remaining
text = chunk[:remaining]
```

  Decode at this fingertip and preserve byte cursor correctness; UTF-8 continuation boundaries
  must not silently lose data. A source modified between pages invalidates the digest/cursor.
- [ ] Expose these bounded tools to discovery runs. Do not retain an unrestricted shell/read
  bypass in that profile. Code workers receive a different explicit candidate-workspace
  authority. Record output under the assigned candidate note path with job/agent identity.
- [ ] Test actual temporary files, changed source, empty result and symlink escape; commit only
  evidence reader and its adapter. Do not build search indexes or a new knowledge database.
**Acceptance/stop:** finite inspection returns useful references; budget/permission exhaustion
produces a partial contribution and cannot expand into a repository-wide audit.

## A3 — Scoped spontaneous scheduling and useful GPU work

**Owner/budget:** Sol medium, 20 minutes. Local children: selector test cases and config entries.
**Depends on:** A1-A2, R1-R7, H1.
**Files:** create `ecosystem/autonomy.py`, `config/autonomy.json`, `scripts/autonomy_tick`,
`services/systemd/agent-autonomy.service`, `tests/test_mvp_autonomy.py`;
modify `ecosystem/watchdog.py`, `config/watchdog.json`, systemd activation catalogue.
**Interfaces:** `select_discovery(policy: dict, history: dict, jobs: list[dict], now: float) -> dict | None`;
`tick(root: Path, clock: dict, enqueue: Callable) -> dict`.
Each policy entry has `scope_id`, `role`, `authority_profile`, `interval_seconds`,
`weight`, `budget`, `read_paths`, `write_paths`. Stable `source_key` is scope/role/generation.

- [ ] Write deduplication without fixed role names:

```python
from ecosystem.autonomy import select_discovery

def test_pending_scope_role_does_not_spawn_again():
    entry = {"scope_id": "notes", "role": "documenter", "interval_seconds": 300,
             "weight": 1, "enabled": True}
    policy = {"entries": [entry]}
    jobs = [{"scope_id": "notes", "role": "documenter", "state": "running"}]
    assert select_discovery(policy, {}, jobs, 600) is None
```

- [ ] Run `python3 -m unittest discover -s tests -p 'test_mvp_autonomy.py' -v`.
- [ ] Implement due/overdue selection with stable staggering, age fairness and no catch-up storm.
  Under one claim lock, inspect current jobs, choose one entry, create one job with source-key
  idempotency, and record the generation. Crash after enqueue must recover from the same key.

```python
if any(job.get("scope_id") == entry["scope_id"] and job.get("role") == entry["role"]
       and job["state"] in {"queued", "ready", "running", "awaiting_verification"}
       for job in jobs):
    continue
```

  Shared R1/R7 admission blocks launch during pressure, emergency, drain, smoke or pause.
  Existing useful ready work can run immediately; discovery intervals do not throttle it.
- [ ] Seed Janitor, Gardener, Documenter, Innovator, Speculator, Chunker and Auditor entries for
  CointOS using the same configuration shape. Remove recurring Steward enqueue and its broad
  inspect-everything prompt. Move useful task-card content into bounded scope descriptions;
  delete unused selection code/card files after a consumer search, preserving durable evidence
  in current notes. Avoid a second monitor scheduler; H1 remains deterministic supervision.
- [ ] Test adding a temporary `cartographer` role entry without code edits, missed intervals,
  replay, global pause and no eligible work. Verify a fake enqueue receives a complete contract.
**Acceptance/stop:** one due scope produces a valid bounded job; no human message is needed;
duplicate/pause/resource exclusions hold. Live activation waits for M1.

## A4 — Meaningful contributions, follow-ups and independent completion

**Owner/budget:** Sol medium, 20 minutes. Local child: one terminal-result validator/test.
**Depends on:** A1-A3, existing verification, P1 candidate isolation.
**Files:** create `ecosystem/contributions.py`, `tests/test_mvp_contributions.py`;
modify `ecosystem/verification.py`, `ecosystem/cli.py`, `ecosystem/executor.py` at result boundaries.
**Interfaces:** `validate_contribution(result: dict, task_contract: dict) -> dict`;
`observe_contribution(candidate_root: Path, result: dict, task_contract: dict) -> dict`;
`apply_contribution(root: Path, job: dict, observed_result: dict, enqueue_child: Callable) -> dict`.
Validation is schema/authority only. Observation resolves paths under the candidate,
reads actual bytes and returns `artifacts: [{path, digest}]` plus result metadata.
Verification and application consume that observed record, never claimed path strings alone.
Results contain `outcome: observation|proposal|changed|partial|no_work`, `summary`,
`evidence_refs`, `artifact_paths`, `checks`, and nullable `child_request`.
These describe an existing job's output; observations/proposals do not get separate lifecycles.

- [ ] Write this valid no-task contribution plus artifact/scope and parent-budget tests:

```python
from ecosystem.contributions import validate_outcome

def test_speculation_need_not_become_a_task():
    result = {"outcome": "observation", "summary": "Investigate whether queue age tracks latency",
              "evidence_refs": ["notes/queue-observation.md"],
              "artifact_paths": ["notes/queue-observation.md"], "checks": [], "child_request": None}
    assert validate_outcome(result)["child_request"] is None
```

  `validate_outcome(raw: dict) -> dict` is the schema-only public helper owned here.
- [ ] Run `python3 -m unittest discover -s tests -p 'test_mvp_contributions.py' -v`.
- [ ] Validate actual artifact existence/digest and scope at the filesystem fingertip. Read-only
  roles cannot report candidate code changes as authorized. `changed` needs evidence of the
  intended invariant/checks, not just a file path. A partial run preserves its handoff without
  marking its unfinished task completed. Verifier reviews the exact output/candidate digest.

```python
if result["child_request"] is not None:
    child = narrow_contract(job["task_contract"], result["child_request"])
    enqueue_child(job, child, idempotency_key=job["id"] + ":child:0")
```

  Perform child claim and remaining-budget reservation atomically before enqueue; replay cannot
  create or spend twice. Chunker/Speculator/Innovator cannot dispatch merely through prose;
  their profile yields a note for an authorized selector. Other tasks may request a narrower
  authorized child. A completed parent cannot leave an unowned child.
- [ ] Replace verification prompts that require reading the complete executor transcript with
  a bounded evidence bundle and optional scoped expansion. Eliminate Lead's approval-for-every-
  review ritual from the new route; artifact checks plus one independent verifier suffice.
- [ ] Test no-work, grounded note, partial handoff, valid code candidate, repeated child request,
  fabricated artifact and wrong-digest verifier. Commit only the owning boundaries.
**Acceptance/stop:** a bounded contribution advances shared knowledge or work; no recursive task
storm or misleading completion, and the next agent has enough evidence to continue.

## A5 — Live spontaneous cycle and restart continuity

**Owner/budget:** coordinator, 15-minute observation window after focused tests. Sol/local workers
are stopped before the smoke fence is acquired, then only test-owned jobs are admitted.
**Depends on:** A1-A4, C5, H4-H5, P4, R7, B4 live communication.
**Files:** extend `tests/integration/test_mvp_flow.py` and `scripts/mvp_smoke` (owned by C5/P4);
record sanitized evidence in `agent_notes/mvp_acceptance.md` and factual `docs/status.md`.
**Interfaces:** smoke scenarios `autonomy`, `handoff`, `approval`, `rollback` consume existing
job/incident/candidate identities. They do not mutate arbitrary queued work.

- [ ] Add a fake-clock integration case: one due Documenter/Gardener source creates one task,
  writes a real scoped artifact in a temporary candidate, gets an independent verdict, and
  produces the expected contribution/approval request. Verify replay does not duplicate it.
- [ ] Run `python3 -m unittest discover -s tests/integration -p 'test_mvp_flow.py' -v` offline.
- [ ] Under the smoke fence, seed a test-owned known small maintenance finding; allow the
  configured discovery path to find it, run a real local job, observe its output and verifier,
  and obtain approval through Coin before activation. Observe a second scheduled contribution
  without another user task; a grounded observation is sufficient, manufactured churn is not.
- [ ] Interrupt one test-owned run at a durable boundary and demonstrate same-job continuation,
  including a smaller context allocation through R6. Verify no terminal context error, no new
  OOM, responsive Coin and no unmanaged local inference after teardown.
- [ ] Release only the smoke fence when health is known. Record exactly which cycles ran and
  what remains deferred. Do not call the whole MVP online until index M1-M3 all pass.
**Acceptance/stop:** the running machine independently discovers, works, records, verifies and
asks for approval; interruptions preserve meaningful continuity. Stop after two useful cycles.
