---
scope: project local
source: 'installed CointOS enqueue and observable worker qualification through task-4894b791ecbcbafc, 2026-09-17'
review_when: Recheck when the observable launcher, installed scheduler, viewer pool, or task-intake contract changes.
status: "unverified"
updated_at: "2026-09-17T13:48:13+10:00"
---

Launch managed local agents through the installed CointOS runtime at `/home/david/.CointOS`, because `ecosystem.cli.ROOT` is derived from the imported package location. Running the source checkout's `./scripts/ecosystem enqueue` creates an inert job under the checkout's ignored `state/`; it does not enter the installed scheduler.

For a source-checkout task, call the installed `ecosystem.cli.enqueue_task` with a validated task contract whose canonical workspace and read/write paths point at `/home/david/Projects/CointOS`, then start `agent-ecosystem.service`. Keep local worker tasks simple and closed-ended. Default ordinary work does not request an independent verifier.

Every managed launch wraps OpenCode with the installed `scripts/opencode_observable.py`. Its durable viewer record is under `~/.CointOS/state/worker-views/TASK-TIMESTAMP.json` and contains the loopback URL, retained session id, server PID, and exact `opencode attach ... --session ...` command. The executor log is under `~/.CointOS/logs/runs/TASK.opencode.log`. Closing a viewer must not stop the worker.

The current manually supervised capacity practice is one local worker at a time. Use the installed scheduler for allocation, priority, recovery, cancellation, and retained-session continuation; do not bypass it with a raw OpenCode process for ordinary authorized work.
