---
status: green
revised_at: "2026-10-04T03:24:30+11:00"
checked_at: '2026-10-04T03:24:36+11:00'
---

Agent completion is one receipt-driven lifecycle owned by `cointos/lifecycle.py`. Live evidence is tracked in `what/is/the/live/acceptance/evidence/for/cointos.md`.

**Layers.**

1. **Runner facts.** `opencode.watch` follows a run's unit files and returns only execution facts: the last OpenCode step finish marker and the client exit code (plus a runner error, if any). Session and activity events update the agent card; a session is recorded on the task only while that run owns it. These facts are diagnostics written into a retry note; they never decide completion.
2. **Receipts and delivery.** Every bounded assignment that is not cancelled ends with exactly one typed receipt `{run, disposition, summary, evidence, at}`, recorded on its task.
   - **Run identity.** The run identity is the agent id, carried as `COINTOS_AGENT` next to `COINTOS_TASK_ID` in the run's environment, so the CLI sends both.
   - **Who submits which receipt.** `cointos finish --complete EVIDENCE | --blocked BLOCKER` (POST `/api/finish` `{task, run, outcome, detail}`) is the receipt for every kind except an integrator's completion; the dispositions each kind may submit are data in `schema.KINDS`. An integrator's receipt is its verified `cointos land`/`cointos incorporate` (disposition `complete`, evidence = the acceptance) or `cointos return` (disposition `returned`).
   - **Blocked work and recovery.** An integrator may also `finish --blocked`. That fails it and its worker, and routes the failed worker item to one bounded manager pass instead of respawning. Exhausted worker retries use the same route. The manager receives the original assignment, worker receipt evidence and failure detail. It gets its own configured reasoning and default generation budget rather than worker record overrides, and no report phrase decides routing. A manager may revise the brief or replace the work. A blocked or exhausted manager escalates to the user without another automatic pass for that unchanged failure. Completing a manager revision preserves the revised item's waiting/queued state rather than accepting failed work.
   - **Duplicates and run ownership.** A repeated identical receipt from the same run returns the recorded one (lost reply). A different receipt, or one from any run other than the task's current run, is refused. Queue proposals, holds, revisions, cancellations and attention requests are checked against the same run ownership. Human holds use the stable `user` identifier; startup normalizes older unscoped human labels to it while retaining scoped manager task IDs, so replacement preserves the user's hold/release authority.
   - **Cancellation.** The user, or the owning project's running manager, can end an assignment without a receipt through `cointos cancel`. Its runs are released, its tasks (with their integrations and decompositions) are marked failed with `cancelled`, and its queue record is deleted.
   - **Delivery.** A successful terminal CLI command prints and flushes its receipt, then acknowledges `receipt-delivered` with those exact identities. The daemon validates the recorded receipt and asynchronously stops that managed run. A landing validation that already returned the worker is also terminal: the CLI confirms the run's recorded receipt, flushes the error, then acknowledges delivery. Releasing a run revokes its gateway key, and the gateway refuses (410) any later model request carrying it, so a stopping process cannot spend lane time as the user.
   - **Snapshots** follow conversation reachability, not the presence of a historical task record. Startup and periodic lifecycle reconciliation remove caches of terminal tasks without surviving runs, including accepted workers whose run ended while they were still in review. A terminal task's still-active run keeps its cache until release. In-flight transfers remain charged and finish before discarded files are removed; interrupted transfer copies are cold after daemon replacement. Conversation history and retained branch artifacts are independent of these disposable caches.

3. **Evidence.** Each area's focused coverage:
   - ownership and the reducer: `tests/test_agent_completion.py`;
   - terminal delivery: `tests/test_cli_terminal.py`;
   - conversation reachability: `tests/test_snapshots.py`;
   - exact landing and incorporation: `tests/test_landing.py`;
   - manager proposals and prompts: `tests/test_handoffs.py`;
   - holds, revisions and cancellation: `tests/test_revision.py`;
   - directed kill/resume: `tests/test_kill.py`;
   - ended-run key refusal: `tests/test_gateway_disconnect.py`.

   Live evidence establishes ordinary receipt-driven unit retirement, directed hold/resume, automatic same-session process-death replacement, and stale-run refusal against a newer active run. Remaining live paths belong to the acceptance leaf and plan.

The proofs are split so each stays well inside the proof runner's per-proof timeout.

Run ownership, receipts, recovery routing and delivery hold in the reducer tests.

Proof:

```bash
cd "$(git rev-parse --show-toplevel)" && python3 -m unittest -q tests.test_agent_completion
```

Terminal delivery, snapshot reachability, manager proposals and ended-run key refusal hold.

Proof:

```bash
cd "$(git rev-parse --show-toplevel)" && python3 -m unittest -q tests.test_cli_terminal tests.test_snapshots tests.test_handoffs tests.test_gateway_disconnect
```

Exact landing, implementation progress, integration, incorporation and the landing commands hold.

Proof:

```bash
cd "$(git rev-parse --show-toplevel)" && python3 -m unittest -q tests.test_landing.Gate tests.test_landing.ImplementationProgress tests.test_landing.IntegrationStage tests.test_landing.Incorporation tests.test_landing.Commands
```

The test-contract landing gate holds.

Proof:

```bash
cd "$(git rev-parse --show-toplevel)" && python3 -m unittest -q tests.test_landing.TestContractStage
```
