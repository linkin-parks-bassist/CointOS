---
status: "unverified"
created_at: "2026-09-16T16:17:51+10:00"
updated_at: "2026-09-16T17:02:29+10:00"
scope: "project local"
source: "installed queue no-starvation qualification 2026-09-16"
checked_at: "2026-09-16T16:23:00+10:00"
---

During installed cancellation qualification, `task-5a6a1b3735254ea5`, an older periodic watchdog task, lacked routable model metadata/capability facts. `prepare_next()` selected it, wrote its deferral reason, returned, and left it queued. Repeated preparation selected the same task again while the newer authenticated-contact cancellation probe remained queued and acquired no worker or inference lease. When `run_until_idle()` was started, this became a hot loop repeatedly re-preparing the ready probe and re-deferring the old task without executing either; the service was stopped and its path/timer triggers paused with all capacity clean.

The source repair changes the deferral branch's terminal `return` to `continue`. Every deferred record and its reason remain durable, scheduler order remains unchanged, and later candidates can be considered in the same pass. If all candidates defer, preparation finishes and `execute_next()` can return idle instead of spinning. `py_compile`, `git diff --check`, and 48 existing intake/executor checks pass. Installed adoption and reproduction closure remain next.

Installed qualification passes: one preparation pass retained and reported both older unroutable watchdog tasks, continued to the authenticated-contact probe, and made that later task ready on Qwen3.8. The probe then reached running execution. The head-of-line starvation is closed.
