---
status: green
revised_at: "2026-10-09T01:04:08+11:00"
checked_at: "2026-10-07T17:03:03+11:00"
---

Agent completion is one receipt-driven lifecycle owned by `cointos/lifecycle.py`. Live evidence is tracked in `what/is/the/live/acceptance/evidence/for/cointos.md`.

**Layers.**

1. **Runner facts.** `opencode.watch` follows a run's unit files and returns only execution facts: the last OpenCode step finish marker and the client exit code (plus a runner error, if any). Session and activity events update the agent card; a session is recorded on the task only while that run owns it. These facts are diagnostics written into a retry note; they never decide completion.
2. **Receipts and delivery.** Every bounded assignment that is not cancelled ends with exactly one typed receipt `{run, disposition, summary, evidence, at}`, recorded on its task. The receipt is the sole account of the work: a worker's summary is what its integrator reads and what the landing commit preserves.
   - **Run identity.** The run identity is the agent id, carried as `COINTOS_AGENT` next to `COINTOS_TASK_ID` in the run's environment. `client.call` sends both as the request's `caller` whenever a command runs inside a run; the API resolves it once (`api.caller`, and `api.running` for an action that needs the task's current run). The user's own commands carry no caller.
   - **Who submits which receipt.** `cointos finish --complete ACCOUNT | --blocked BLOCKER` (POST `/api/finish` `{outcome, detail}` with its caller) is the receipt for every kind except an integrator's completion; the dispositions each kind may submit are data in `schema.KINDS`. An integrator's receipt is its verified `cointos land`/`cointos incorporate` (disposition `complete`, evidence = the acceptance) or `cointos return` (disposition `returned`). `lifecycle.evidence` checks a receipt against the task's artifacts, and a refusal states what it saw: the uncommitted files, how many commits the branch is ahead of main, production files in a test packet, an unchecked packet, or that a decomposition changed nothing.
   - **A run ends; the assignment does not.** Only a run of the assignment itself can submit its work, so no run's end is a verdict on that work. A run that dies, stalls or exhausts its budget leaves its branch and files, and the task waits for its next run; after exhaustion that run starts a fresh session (`lifecycle.retry_fresh`, at most `recovery.fresh_retries` times) whose first job is to submit work already complete, or to report blocked with what remains when the rest will not fit.
   - **Blocked work and recovery.** A worker's blocked receipt goes to review for assessment, but no stage can land from it: completion checks have not passed. The integrator returns ready work for complete submission or finishes blocked. An integrator's `finish --blocked` fails it and its worker, and the failed worker item gets one bounded manager pass instead of a respawn. A worker item whose fresh runs are exhausted, or a test-contract brief the dispatch check refuses before any run (`spawner.dispatch`), fails the same way. The manager receives the original assignment, worker receipt evidence and failure detail (`queues.blocker`). It gets its own configured reasoning and default generation budget rather than worker record overrides, and no report phrase decides routing. A manager may revise the brief (naming finished branch work lets its worker submit it) or replace the work. A blocked or exhausted manager escalates to the user without another automatic pass for that unchanged failure. Completing a manager revision preserves the revised item's queued state rather than accepting failed work.
   - **Duplicates and run ownership.** A repeated identical receipt from the same run returns the recorded one (lost reply). A different receipt, or one from any run other than the task's current run, is refused. Queue proposals, holds, revisions, cancellations, messages and operator requests are checked against the same run ownership. Human holds use the stable `user` identifier.
   - **Cancellation.** The user, or the owning project's running manager, can end an assignment without a receipt through `cointos cancel TASK...`. A task with a queue record withdraws it: its runs are released, its tasks (with their integrations and decompositions) are marked failed with `cancelled`, and the record is deleted. A live task without a record (a garden, audit, scout or operator) just ends, for the user only.
   - **Delivery.** A successful terminal CLI command prints and flushes its receipt, then acknowledges `receipt-delivered` as its caller. The daemon validates the recorded receipt and asynchronously stops that managed run. A landing validation that already returned the worker is also terminal: the CLI confirms the run's recorded receipt, flushes the error, then acknowledges delivery. Releasing a run revokes its gateway key, and the gateway refuses (410) any later model request carrying it.
   - **Snapshots** follow conversation reachability, not historical task records: reconciliation removes caches of terminal tasks without surviving runs, while a still-active run keeps its cache until release (`what/is/the/architecture/of/cointos.md` owns transfers).

3. **Evidence.** `tests/test_agent_completion.py` (ownership, reducer, refusals), `test_recovery.py` (budgets, exhaustion, recovery packets), `test_cli_terminal.py` (delivery), `test_snapshots.py` (reachability), `test_landing.py` (landing, packets, incorporation, commands), `test_handoffs.py` (proposals, prompts), `test_revision.py` (holds, revisions, cancellation), `test_kill.py` (kill/resume) and `test_gateway_disconnect.py` (ended-run keys). Live evidence establishes ordinary receipt-driven unit retirement, directed hold/resume, automatic same-session process-death replacement, and stale-run refusal against a newer active run; remaining live paths belong to the acceptance leaf and plan.

Run ownership, receipts, recovery routing and delivery hold in the reducer tests.

Proof:

```bash
cd "$(git rev-parse --show-toplevel)" && python3 -m unittest -q tests.test_agent_completion
```

An exhausted run's assignment continues fresh, the continuing run can submit the finished work, and a worker item whose fresh runs are exhausted reaches a manager with its packet.

Proof:

```bash
cd "$(git rev-parse --show-toplevel)" && python3 -m unittest -q tests.test_recovery.Budgets
```

Terminal delivery, snapshot reachability, manager proposals and ended-run key refusal hold.

Proof:

```bash
cd "$(git rev-parse --show-toplevel)" && python3 -m unittest -q tests.test_cli_terminal tests.test_snapshots tests.test_handoffs tests.test_gateway_disconnect
```

Exact landing, test-packet acceptance, incorporation and the landing commands hold.

Proof:

```bash
cd "$(git rev-parse --show-toplevel)" && python3 -m unittest -q tests.test_landing.Gate tests.test_landing.Packets tests.test_landing.Incorporation tests.test_landing.Commands
```
