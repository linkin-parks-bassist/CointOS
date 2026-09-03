# Current status

Updated: 2026-09-04 (Australia/Sydney)

## Implemented

- Durable filesystem jobs, role-context compilation, recorded model choice, local
  OpenCode execution, independent semantic verification, and dependent results.
- A three-stage Telegram path: durable receipt plus GLM first response, concurrent
  Qwen deep control, and separately supervised result presentation.
- Per-turn action caching and deterministic task idempotency, explicit unknown-
  delivery states, and a transport-owned five-minute disaster fallback.
- GLM-4.7-Flash, Qwen3.8-27B, and Qwen3-Coder-30B as the intended resident model set.
- Periodic deterministic health checks and model-judged Steward assignments.

## Operational state

Checked-in units cover model loading, Telegram intake, two deep-control workers,
background notifications, ecosystem intake/execution, and watchdog stewardship.
Runtime truth must be established from `systemctl --user`, Lemonade, control-turn/job
records, and an end-to-end probe after deployment or reboot; this document is not
live telemetry.

## Known limits

- Telegram `sendMessage` has no client idempotency key. A crash during a request is
  recorded as `delivery_unknown` and is not replayed automatically.
- General live direct, role-local, and global inter-agent messaging remains specified
  but unimplemented.
- Worker checkpoint/preemption and model lease admission remain future work.
- Existing class-based tests remain incremental no-OOP migration debt.
