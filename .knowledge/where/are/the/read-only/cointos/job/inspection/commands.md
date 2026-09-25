---
status: green
revised_at: "2026-09-26T03:34:12+10:00"
---

Use source `scripts/cointos-job-info TASK_ID` for one durable job’s orchestration state, runner process identity, timestamps, process close-out, usage, session identifier, and log path. Use `scripts/cointos-jobs` to list active jobs, `--recent N` for recent jobs, and `--state STATE` for explicit state filters. Both accept `--json` and `--root`; neither reads or prints task prompts or worker output. Shared read-only derivation lives in `ecosystem/job_inspection.py`.

The source inspector reads the managed child’s actual `executor_pid` and `executor_start_ticks` and compares them with `/proc` before calling it alive. The first installed version mistakenly read nonexistent `runner_pid` fields and showed `not_registered` for a healthy running worker. The corrected `ecosystem/job_inspection.py` uses `executor_pid` and `executor_start_ticks`; source and installed copies now match. Its exact-process-identity behavior is covered by `does/cointos/job/inspection/verify/exact/runner/identity.md`. Recheck a current job before interpreting `alive` or `not_registered`.
