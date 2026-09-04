# Current status

Updated: 2026-09-04 (Australia/Sydney)

## Implemented

- Durable filesystem jobs, role-context compilation, recorded model choice, local
  OpenCode execution, independent semantic verification, and dependent results.
- A three-stage Telegram path: durable receipt plus a fast Qwen3.5 4B first response,
  concurrent durable control, and separately supervised result presentation.
- Per-turn action caching and deterministic task idempotency, explicit unknown-
  delivery states, and a transport-owned five-minute disaster fallback.
- One pinned Qwen3.5 4B chatbot/router/emergency model and at most one dynamically
  selected, unpinned work model.
- Model-mediated `use_loaded`/`load`/`defer` dispatch with deterministic resource,
  residency, role-capability, and context validation.
- OpenCode session preemption, priority/time-quantum scheduling, abandoned-run
  recovery, and 75%-full context handoff into a fresh session.
- Kernel OOM detection, dispatch latching, full model unload, and an exclusive
  `sole_survivor` recovery role.
- Periodic deterministic health checks and model-judged Steward assignments.

## Operational state

Checked-in units cover model loading, Telegram intake, two deep-control workers,
background notifications, ecosystem intake/execution, and watchdog stewardship.
Runtime truth must be established from `systemctl --user`, Lemonade, control-turn/job
records, and an end-to-end probe after deployment or reboot; this document is not
live telemetry.

The 2026-09-04 foundation reconciliation repaired the existing user resource guard
after a live restart storm. A single non-OOM pressure sample had entered emergency,
the `sole_survivor` role was rejected, and a correctly loaded but busy model was
treated as absent. The partially committed emergency was then retried once per
second, restarting Telegram, control, and notification services until systemd
rate-limited Telegram. The unit suite still passed because the old resource tests
mocked across the failing composition boundary.

The repaired resource controller now confirms non-OOM pressure over configured
monotonic windows, treats loaded/backend-alive busy or in-use models as live, and
advances a durable fail-closed phase record only after each external effect's
postcondition is observed. Roles are nullable advisory context rather than an
admission boundary. A failed or malformed postcondition leaves the restrictive
phase visible for retry instead of publishing normal operation.

One foreground reconciliation converted the legacy latch into incident
`20260904T033110Z-0`, restored the pinned model, and prepared survivor
`task-e01f5d8c44f8421d`. Six samples over 25 seconds then showed stable resource
guard, Telegram, control-worker, and notifier process identities with zero restarts;
the dirty-checkout suite passed 113/113. That process-stability gate was not semantic
acceptance: the survivor then failed when a 25,523-token request exceeded the
backend's effective 16,384-token per-sequence context (`--ctx-size 32768` shared by
two sequences), and the guard initially repeated the unchanged error each second.

The contained retry corrected and verified backend allocation at total
`ctx_size=65536`, parallel two, preserved the old failed record hashes, and created
canonical replacement `task-a02f3a746e5a0914` as the sole admitted running owner.
Its first 75%-full rollover produced a 3,956-byte semantic handoff and a fresh
session. That session nevertheless reread the full incident and failed when its
33,891-token request exceeded the effective 32,768-token per-sequence capacity. A
foreground tick persisted one deduplicated `context_overflow` emergency-escalation
record for the replacement. The resource guard remains stopped; Telegram and the
notifier retained PIDs 272721 and 272720 with zero restarts.

The resource guard is also disabled at the user-service boot boundary, not merely
inactive for the current session. Telegram and the notifier remain active and
enabled.

Task 4 is therefore safely contained, not fully accepted. Automated completion of
this failure class is deferred to Plan 4's required context-overflow escalation to a
larger safe model/context. Lemonade's configured local API is port 13305.

The root-installed permanent gateway, hard guardian, survival spools, and full
failure-injection acceptance are still future work in the fifth plan of the survival
suite. The currently running user services are not that permanent survival plane.

## Known limits

- Telegram `sendMessage` has no client idempotency key. A crash during a request is
  recorded as `delivery_unknown` and is not replayed automatically.
- General live direct, role-local, and global inter-agent messaging remains specified
  but unimplemented.
- Lemonade exposes no serializable live backend KV cache; continuity therefore uses
  OpenCode sessions, exact prompts, logs, handoff artifacts, and filesystem state.
- Context KV cost is conservatively estimated rather than read from a backend lease
  API; the guard remains authoritative if observed pressure exceeds the estimate.
- Active user-unit status alone does not prove Telegram reachability, model health,
  a renewable subsystem lease, or recovery correctness. Those claims require the
  corresponding process, endpoint, durable-state, and end-to-end observations.
- Resource-guard process stability and one successful context handoff do not prove
  that the replacement session will avoid rereading an oversized incident or finish
  repair. The pending escalation record remains authoritative while the guard is off.
- Existing class-based tests remain incremental no-OOP migration debt.
