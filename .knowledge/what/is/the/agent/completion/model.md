---
status: green
revised_at: "2026-09-30T13:07:38+10:00"
checked_at: "2026-09-30T00:38:37+10:00"
---

Agent completion is one receipt-driven lifecycle owned by `cointos/lifecycle.py`. Live evidence is tracked in `what/is/the/live/acceptance/evidence/for/cointos.md`.

**Layers.**

1. **Runner facts.** `opencode.watch` follows a run's unit files and returns only execution facts: the last OpenCode step finish marker and the client exit code (plus a runner error, if any). Session and activity events update the agent card; a session is recorded on the task only while that run owns it. These facts are diagnostics written into a retry note; they never decide completion.
2. **Receipts and delivery.** Every bounded assignment ends with exactly one typed receipt `{run, disposition, summary, evidence, at}` recorded on its task. The run identity is the agent id, carried as `COINTOS_AGENT` next to `COINTOS_TASK_ID` in the run's environment, so the CLI sends both. `cointos finish --complete EVIDENCE | --blocked BLOCKER` (POST `/api/finish` `{task, run, outcome, detail}`) is the receipt for every kind except an integrator's completion; the dispositions each kind may submit are data in `schema.KINDS`. An integrator's receipt is its verified `cointos land`/`cointos incorporate` (disposition `complete`, evidence = the acceptance) or `cointos return` (disposition `returned`). An integrator may also `finish --blocked`, which fails it and its worker and routes the failed worker item to one bounded manager pass instead of respawning. Exhausted worker retries use the same route. The manager receives the original assignment, worker receipt evidence and failure detail; no report phrase decides routing. A manager may revise the brief or replace the work; a blocked or exhausted manager escalates to David without another automatic pass for that unchanged failure. Completing a manager revision preserves the revised item's waiting/queued state rather than accepting failed work. A repeated identical receipt from the same run returns the recorded one (lost reply); a different one, or one from any run other than the task's current run, is refused. Queue proposals, holds, revisions and attention requests are checked against the same run ownership. A successful terminal CLI command prints and flushes its receipt, then acknowledges `receipt-delivered` with those exact identities; the daemon validates the recorded receipt and asynchronously stops that managed run. A landing validation that already returned the worker is also terminal: the CLI confirms the run's recorded receipt, flushes the error, then acknowledges delivery.
3. **Evidence.** Focused ownership and reducer coverage lives in `tests/test_agent_completion.py`, terminal delivery in `tests/test_cli_terminal.py`, conversation reachability in `tests/test_snapshots.py`, exact landing/incorporation in `tests/test_landing.py`, manager proposals and prompts in `tests/test_handoffs.py`, holds/revisions in `tests/test_revision.py`, and directed kill/resume in `tests/test_kill.py`. Live evidence establishes ordinary receipt-driven unit retirement and directed hold/resume; remaining live paths belong to the acceptance leaf and plan.
Proof:

```bash
cd "$(git rev-parse --show-toplevel)" && python3 -m unittest -q tests.test_agent_completion tests.test_cli_terminal tests.test_snapshots tests.test_landing tests.test_handoffs
```
