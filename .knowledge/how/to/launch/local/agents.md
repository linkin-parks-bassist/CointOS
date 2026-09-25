---
status: green
revised_at: "2026-09-26T01:50:17+10:00"
---

Launch managed local agents through the installed CointOS runtime at `/home/david/.CointOS`, because `ecosystem.cli.ROOT` is derived from the imported package location. Running source checkout `./scripts/ecosystem enqueue` creates an inert job under checkout state; it does not enter the installed scheduler. When importing the installed package from Python, work in `/home/david/.CointOS` so the installed package precedes the checkout on `sys.path`.

For a source-checkout task, call installed `ecosystem.cli.enqueue_task` with a validated contract whose canonical workspace and read/write paths point at `/home/david/Projects/CointOS`, then start `agent-ecosystem.service`. Required fields are `acceptance`, `authority_profile`, `budget`, `objective`, `parent_job_id`, `requirements`, `scope`, `source_key`, and `stop_condition`. Keep worker tasks cohesive, closed-ended, and valuable enough to justify their cost. Default ordinary work does not request an independent verifier.

Every managed launch wraps OpenCode with installed `scripts/opencode_observable.py`. Its durable viewer record is under `~/.CointOS/state/worker-views/TASK-TIMESTAMP.json`, with loopback URL, retained session ID, server PID and attach command. Executor log is `~/.CointOS/logs/runs/TASK.opencode.log`. From the checkout, `scripts/worker-log-summary --active` lists nonterminal managed tasks and `scripts/worker-log-summary TASK --tail 25` shows recent durable events. Both are read-only; closing a viewer must not stop the worker.

The installed scheduler is the ordinary launch path; do not bypass it with raw OpenCode or a transient executor lane. Generic dynamic lanes derive process demand from admitted jobs and fresh route capacity rather than a Qwen-specific count. Two CointOS-only workers ran simultaneously on separate backend sequences, exited cleanly, and a queued third started automatically and completed. Sibling cancellation, pressure shutdown and parked-worker handoff across a physical profile change remain unqualified.

Fresh installed executor launches pass the validated task workspace as OpenCode `--dir`, so the startup hook runs in the intended project root; retained pre-change sessions keep their original home-directory identity on resume. Worker prompt is exactly assigned task text plus newline; the hook owns KT bootstrap. Task-only prompt text and complete hook delivery were previously live-qualified. If hook delivery fails, diagnose startup. Future worker launches should use a bounded cohesive slice and leave task-related KT write scope available. `validate_scope` rejects contract read/write paths outside its workspace; do not silently broaden a worker's scope to include runtime logs.
