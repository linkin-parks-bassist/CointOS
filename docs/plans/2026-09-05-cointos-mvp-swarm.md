# CointOS MVP Worker Coordination Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development or superpowers:executing-plans. The coordinator assigns one task or named subtask; do not execute the entire suite from a worker prompt.

**Goal:** Make the MVP tasks safe to distribute to local workers, and to Sol-medium workers under a hosted coordinator, while preserving smoke-test control.

**Architecture:** Astra owns design, task admission, integration and final acceptance. Sol workers own bounded implementation slices; local workers perform short concrete pieces in isolated scopes. Worker kind follows the dispatcher: a hosted coordinator may run Sol workers; a local coordinator dispatches local workers only and never spawns or enqueues hosted-model workers. Shared interfaces are fixed in the spec and owning task before parallel work begins.

**Tech Stack:** Codex collaboration tools, Git worktrees, existing local OpenCode/Lemonade tooling, plain durable handoff records and R1 worker leases.

**Spec:** [MVP design](../specs/2026-09-05-cointos-mvp-design.md).

## Global constraints for every packet

- Read `/home/david/AGENTS.md`, repository `AGENTS.md`, and `/home/david/ARCHITECTURAL_MANIFESTO.md` in full.
- Personal CointOS scope only. No credentials, private conversation bodies or other-project context.
- Functions and plain data; lowercase snake_case; preserve external API spelling.
- Coin available, no OOM, seamless dynamic-context handovers. Sole Survivor > Coin > small health inspector > large health inspector > other roles; Coin reserve is independent of rank.
- Preserve all existing dirty work; one reviewed snapshot is the implementation base.
- Worker writes only its assigned files/worktree. Never import mutable worker code into live services.
- No model load/unload, live inference test, Telegram transmission, service action, credential access, push or merge unless specifically assigned to the coordinator-owned live task and already authorized by David.
- Record agent name, task ID, exact base, changed files, evidence, output, remaining work and stops.
- A process exit alone is not success. An incomplete attempt returns a bounded useful handoff.

## S0 — Establish the exact source and task ledger

**Owner/budget:** coordinator, 15 minutes; no model or service changes.
**Depends on:** David approving this concrete plan for execution.
**Files:** assigned implementation worktrees; ignored `state/mvp_build/` ledger;
`docs/status.md` and applicable semantic knowledge leaves for sanitized durable facts only.
**Interfaces:** each ledger assignment records `task_id`, `agent_name`, `worker_kind`,
`base_revision`, `workspace`, `write_paths`, `depends_on`, `deadline`, `lease_id`,
`state`, `handoff_path`, `review_result`.

- [ ] Read `git status --short --branch`, `git diff --stat`, `git ls-files --others --exclude-standard`,
  and `git worktree list --porcelain`. Inspect only task-related diffs. Current planning base
  began at `12b1c19` plus existing dirty work; do not assume that commit contains all working code.
- [ ] Select the coherent source snapshot needed by the first tasks, preserving all unrelated
  edits in place. Make an explicit path/digest manifest. Include required untracked source
  deliberately; never use `git add .` or copy ignored runtime/credential trees. Commit only
  reviewed source on the implementation topic branch; record unresolved overlapping edits.
- [ ] Create isolated worktrees with non-overlapping writers. Use the environment's worktree
  mechanism or `git worktree add` under `/home/david/.worktrees/` after inspecting existing
  paths. Do not switch/rewrite the live checkout underneath user services.
- [ ] Establish focused baseline checks against the exact snapshot using temporary state roots.
  Existing unrelated failing tests become separately recorded findings. Tests which threaten
  ordinary operation, OOM safety or rollback block the affected task; unrelated debt does not
  become an exhaustive bootstrap gate. Do not execute the current installer against the host
  merely because `COINTELPROFESSIONAL_INSTALL_ROOT` is set: account operations are not isolated.
- [ ] Register every writer and local inference run. Until R1 exists, the coordinator is the
  explicit admission owner: no local task starts while a smoke task is pending; wait for
  every owned local process/request to finish and observe idle backend before smoke.
**Acceptance/stop:** exact source and file ownership are known; no unmanaged worker or silently
discarded dirty edit. Then dispatch only dependency-ready tasks from the index.

## Q1 — Standard parsing, owned validation and safe configuration reload

**Owner/budget:** Sol medium, 20 minutes. Local child: JSON reload or invalid-value tests.
**Depends on:** S0. Other tasks add only the semantic validator for their own family.
**Files:** create `survival/configuration.py`, `tests/test_mvp_configuration.py`;
modify `survival/time_policy.py`, `ecosystem/time_policy.py`, `config/time.cfg` only to
share the accepted-snapshot/reload operation; preserve standard-library parsing.
**Interfaces:** `load_json_policy(path: Path, validate: Callable) -> dict`;
`adopt_policy(active: dict, proposed: dict, validate: Callable, clock: dict) -> tuple[dict, str | None]`.
Accepted snapshot fields: `schema_version`, `values`, `digest`, `activated_at`, `source_path`.
Validator receives parsed values and raises ValueError for invalid semantics.

- [ ] Test rejection preserves the complete previous snapshot:

```python
from survival.configuration import adopt_policy

def test_invalid_policy_never_partially_applies():
    active = {"schema_version": 1, "values": {"run_seconds": 300},
              "digest": "a" * 64, "activated_at": "old", "source_path": "policy.json"}
    def validate(values):
        if set(values) != {"run_seconds"} or type(values["run_seconds"]) is not int or values["run_seconds"] <= 0:
            raise ValueError("invalid run_seconds")
    result, error = adopt_policy(active, {"run_seconds": -1}, validate,
                                 {"boot_id": "b", "monotonic": 10, "utc": "new"})
    assert result == active
    assert error == "invalid run_seconds"
```

- [ ] Run `python3 -m unittest discover -s tests -p 'test_mvp_configuration.py' -v`.
- [ ] Keep ConfigParser for INI and strict standard JSON decoding for JSON. Extract only shared
  snapshot adoption, hashing and visible rejection handling; validators remain at the family
  owners named in the spec. Avoid a plugin/schema interpreter or a new parser dependency.

```python
try:
    validate(proposed)
except ValueError as error:
    return active, str(error)
```

  Successful adoption validates the entire family, computes a canonical digest and atomically
  publishes its snapshot. No accepted snapshot at boot is explicit failure; no guessed defaults.
- [ ] Test valid/invalid reload, duplicate JSON keys, nonfinite values, unknown keys and failed
  publication. In-flight lease deadlines retain their original snapshot; tighter resources
  request drain/continuation under R7/R6. Direct operator edits and approved agent changes use
  the same validator. No raw configuration string may choose privileged service/path operations.
- [ ] Run new tests and existing `test_time_policy.py`; inspect no duplicated key parsing in
  consumers. Commit only named files. R1 then consumes the accepted snapshots.
**Acceptance/stop:** files remain easy to edit; owners receive validated meaningful policy;
invalid edits leave the last accepted whole policy active and visibly report the reason.

## Worker selection and task sizes

| Work | Worker | Limit |
| --- | --- | --- |
| Ambiguous architecture, cross-plan decisions, activation and smoke ownership | Astra/coordinator | One bounded decision or smoke scenario |
| State integration, privilege-facing glue, concrete module ownership | GPT-5.6 Sol, medium | 15-25 minutes; one task, then handoff |
| Parser/reducer case, one role description, test fixture, exact adapter change, static extraction | Largest safely feasible qualified local model/context | small, simple; one independently checkable outcome |
| Independent review | Different worker from implementer, usually Sol medium | 5-10 minutes, assigned invariant/diff only |

The Sol rows apply only under a hosted coordinator. A local coordinator assigns
the same work to the largest safely feasible qualified local model/context, and
every owner/budget line in the owning plans that names Sol is read that way under
local dispatch.

Local workers are the default for plentiful concrete jobs. The coordinator records
why a chunk needs hosted judgment; do not leave all implementation to hosted models.
Begin with one local inference worker at a time; a hosted coordinator may add at
most two Sol writers with disjoint scopes. These are initial resource policy, not
hard-coded population limits.

Choose the largest task-qualified local model fitting the fresh envelope, then the
largest safe context for it, including load and handoff reserves. Verify metadata and
actual per-sequence allocation. Model/context choice is a lease, not a permanent
assignment. Do not bypass safety to make a preferred size fit; explain exclusions.
The current planning extraction used the already loaded 27B/131072 allocation and
did not establish that it is the maximum safe future choice.

Each Sol task has local substeps: after fixing the interface, offload independent
fixture/reducer/parser/role work. Local outputs land in separate patches/worktrees;
one integrator owns shared files. Local workers never independently select broader
files or create a recursive swarm. If a chunk cannot yield a useful
artifact, split at a smaller verified boundary before admission.

## Exact hosted packet template

Only a hosted coordinator issues this packet. A local coordinator dispatches local
packets only; it never issues a hosted packet or spawns a hosted-model worker.

Use the actual available collaboration tool; this is the requested model/effort,
not a recommendation to substitute a different model:

```json
{
  "task_name": "mvp_r1",
  "model": "gpt-5.6-sol",
  "reasoning_effort": "medium",
  "fork_turns": "none",
  "message": "Assigned name: <name>. Task R1 only. Read workspace/repo instructions, manifesto, MVP spec, swarm contract and R1 task. Base <revision>; worktree <absolute path>; write only <exact paths>. Deliver <observable outcome>; consume/produce the signatures in R1. Budget <minutes>, stop after acceptance or a useful partial handoff. No live model/service/Telegram/credential/publication actions. Tests use temporary roots. Offload only coordinator-approved local substeps through registered worker leases; do not create overlapping writers. Return exact changed paths, commands/results, commit, unresolved blocker and durable handoff. Do not execute other plan tasks."
}
```

The bracketed packet values are filled from the task ledger at dispatch, not left
for the worker to infer. Every code task ends in one coherent local commit after
focused tests and diff review. No worker pushes or merges. The repository-specific
publication rule requires explicit approval, so this plan has no automatic push step.

## Exact local packet fields

```text
assigned_name: chosen by coordinator and recorded
task_id: parent task plus one local substep identifier
input_revision: exact accepted parent revision
read_paths: explicit source/test/instruction files
write_paths: one small disjoint set, or empty for extraction
contract: exact consuming/producing signatures and concrete examples
deliverable: one patch, test result, role file or evidence extraction
acceptance: exact bounded commands/assertions
model_lease: selected model, backend, per-sequence context, output reserve
budget: explicit item/output limits
stop: acceptance reached, budget reached, drain requested, or named blocker
handoff: changed paths, evidence, partial result, next step; no broad rereading
authority: no new model loads, service changes, root, publication or other projects
```

Large context is available capacity, not permission to stuff every note into a
prompt. Supply the task contract and minimal relevant evidence. A worker writes a
compact handoff before its deadline; the coordinator reassigns continuation as a
new bounded chunk of the same meaningful task. R6 handles runtime context turnover.

## Smoke handshake — mandatory for every live test

1. Coordinator announces the scenario and affected files/services; close worker
   admission through R1 before enumerating active workers.
2. Ask current local runs to finish their short chunk or checkpoint. Codex waits.
   Do not unload a model from under an active worker or start the test beside it.
3. Observe worker terminal/checkpoint state, process-group exit, backend request
   completion and released inference leases. Also wait for hosted writers touching
   the test's source/config. Read-only hosted analysis may continue.
4. Enter the exclusive smoke lease only after every required observation passes.
   A deadline/unknown owner gives a named blocker, not permission to continue.
5. Snapshot active model allocation, independent pause/resource/lifecycle gates,
   old release and poller identities. Only the smoke owner may change test models.
6. Run one bounded scenario. Preserve Coin's front and the desktop reserve; fake
   pressure/OOM inputs are preferable to provoking a real kernel OOM.
7. Verify final health and test-process exit, restore the intended model set,
   and release only the smoke gate. Pressure/emergency/operator pause remain owned
   by their own state. If health is unknown, keep worker admission closed and report.
8. Resume spawning only after the coordinator records the gate outcome.

## Test and review convention

New Python tests are plain functions and use the existing standard-library collector
pattern, not a new class hierarchy or dependency:

```python
import inspect
import unittest

def load_tests(_loader, _tests, _pattern):
    functions = [value for name, value in globals().items()
                 if name.startswith("test_") and inspect.isfunction(value)]
    return unittest.TestSuite(unittest.FunctionTestCase(value) for value in functions)
```

Use `python3 -m unittest discover -s tests -p 'test_mvp_<owner>.py' -v` per task.
The function collector must actually discover a positive test count. Each new
boundary has a concrete failing example in its task; add the named real failure
cases, not tests mirroring incidental implementation. Run existing affected modules
as well. An offline integration checkpoint runs the combined route before a live
scenario; the full suite runs once for an integrated milestone, not after every
local patch. Repeat only for new changes/failures/relevant uncertainty.

Reviewer checks the assigned invariant, exact diff, tests and contract. One bounded
independent review per meaningful task is sufficient; substeps share that gate.
Block on ordinary-operation failure, OOM/contact/continuity violation or unsafe
rollback. Record broader hardening separately with evidence and owner. Do not
recreate the old endless final-review loop. A genuinely incompatible conception is
replaced at its owning boundary; local symptom patches are not progress.

## File ownership and integration

Shared hotspots are `ecosystem/cli.py`, `executor.py`, `models.py`, `inference.py`,
`survival/gateway.py`, `guardian.py`, `scripts/install-survival-plane`, timing
validators and service catalogues. Only one integrator writes each at a time.
Other workers return patches based on exact revisions. Rebase/reconcile under the
integrator, run the affected composition tests, then publish the next base to the
ledger. Do not let parallel tasks silently invent different signatures.

Completion handoff: assigned name/task, base and commit, exact artifacts, tests and
actual counts, fulfilled acceptance, partial state, resource/worker lease release,
and one smallest next step. Keep logs/runtime state out of Git. The coordinator
synthesizes reviewed evidence without redoing every worker's entire investigation.
