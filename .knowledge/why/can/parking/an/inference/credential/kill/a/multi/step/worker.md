---
status: green
revised_at: "2026-09-17T14:59:34+10:00"
checked_at: '2026-09-17T15:06:00+10:00'
---

After a completed tool-call response, `serve_one_connection()` calls `park_proxy_credential()` to release the physical sequence while retaining the logical OpenCode run. The former implementation changed the credential from `open` to `parking` before `release_sequence()`. If release raised, the caller swallowed the exception so a completed response was not turned into a client failure, but the credential stayed `parking`; authorization mapped that state to terminal HTTP 409. `ReserveArithmeticTracer` exhibited this exact failure after its first tool call.

The repair makes `parking`, `parked`, and `reacquiring` retryable 425 authorization states. `serve_one_connection()` waits while a park is actively in progress and only invokes reacquisition from parked/reacquiring states, avoiding contention between release and reacquire. If physical release raises or returns non-released, `park_proxy_credential()` restores a still-parking credential to `open` and removes the park request marker; it does not undo a concurrent cancellation transition to closing.

Live qualification passed in the same retained `ReserveArithmeticTracer` session: after installation and recovery it crossed numerous model/tool boundaries, survived equal-priority rotations, produced its complete reserve-consumer report, and emitted explicit `step_finish: stop`. The 108 existing focused inference and executor checks pass.