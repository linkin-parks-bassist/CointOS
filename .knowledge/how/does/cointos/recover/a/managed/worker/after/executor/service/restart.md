---
status: "unverified"
created_at: "2026-09-17T12:24:30+10:00"
scope: "project local"
source: "ecosystem/executor.py and installed live service restart qualification 2026-09-17"
---

`recover_abandoned_jobs()` closes a managed runner whose owning executor service disappeared after inference reservation once the process group is proved absent. It cancels the proxy request, records the observed dead process group, and reuses `close_runner_round()` so backend termination, credential revocation, inference release, and worker quiescence retain their existing evidence requirements.

After verified closure, a durable cancellation marker wins and terminalizes the job as `cancelled`. Otherwise recovery reads the exact OpenCode session from either the job or the observable output's `worker_view_ready` event. A found session returns the job to `ready` with `logical_run_state: continuing`, increments its preemption count, and records `executor service restarted`; the next executor generation launches with `--session` and the same session identifier. If backend termination is not yet observable or no exact session is available, recovery retains `reconciliation_required` rather than releasing resources falsely or replaying uncertain work.

Installed live qualification killed only the active `agent-ecosystem.service` executor while job `task-a8fb4c1c58a647c7` held Qwen3.8. The first recovery pass retained reconciliation until termination evidence became available; the next pass recovered session `ses_f52d75868ffevd43LBnP23G16y`, generation 2 ran with that same session on fresh worker and inference leases, and the disposable job was subsequently cancelled with no owned process or lease remaining. The exercise also showed that the observable session event may reach the durable log before the parent copies it into the job, so restart recovery must read both sources.

Focused source evidence: `python3 -m py_compile ecosystem/executor.py`; `python3 -m unittest tests.test_preemption tests.test_mvp_task_contracts` passed 13 checks. No new regression test was added. Requalify after changing executor recovery, runner close ordering, observable session events, proxy termination evidence, or the systemd service boundary.
