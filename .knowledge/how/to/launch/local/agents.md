---
scope: project local
source: "installed/source Python import behavior and task-4894b791ecbcbafc contract 2026-09-17"
review_when: Recheck when the observable launcher, installed scheduler, viewer pool, or task-intake contract changes.
status: "unverified"
updated_at: "2026-09-17T15:01:51+10:00"
---

Launch managed local agents through the installed CointOS runtime at `/home/david/.CointOS`, because `ecosystem.cli.ROOT` is derived from the imported package location. Running the source checkout `./scripts/ecosystem enqueue` creates an inert job under the checkout ignored `state/`; it does not enter the installed scheduler.

When importing the installed package from Python, run with working directory `/home/david/.CointOS` (or otherwise ensure the installed package precedes the current checkout on `sys.path`). Merely setting `PYTHONPATH=/home/david/.CointOS` while the process working directory is the source checkout still imports the source `ecosystem` first through `sys.path[0]` and initializes inert checkout state.

For a source-checkout task, call installed `ecosystem.cli.enqueue_task` with a validated task contract whose canonical workspace and read/write paths point at `/home/david/Projects/CointOS`, then start `agent-ecosystem.service`. The exact required contract fields are `acceptance`, `authority_profile`, `budget`, `objective`, `parent_job_id`, `requirements`, `scope`, `source_key`, and `stop_condition`. Keep local worker tasks simple and closed-ended. Default ordinary work does not request an independent verifier.

Every managed launch wraps OpenCode with installed `scripts/opencode_observable.py`. Its durable viewer record is under `~/.CointOS/state/worker-views/TASK-TIMESTAMP.json` and contains the loopback URL, retained session id, server PID, and exact `opencode attach ... --session ...` command. The executor log is under `~/.CointOS/logs/runs/TASK.opencode.log`. Closing a viewer must not stop the worker.

The current manually supervised capacity practice is one local worker at a time. Use the installed scheduler for allocation, priority, recovery, cancellation, and retained-session continuation; do not bypass it with a raw OpenCode process for ordinary authorized work.