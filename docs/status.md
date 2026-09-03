# Current status

Updated: 2026-09-03 (Australia/Sydney)

## Observed

- Lemonade 11.9.0 is running on loopback port 13305 and reports
  `GLM-4.7-Flash-GGUF` ready.
- The pre-existing `lemonade-ecosystem-install.service` is still active.
- No agent ecosystem units were installed or enabled during this milestone.

## Implemented

- A durable, atomic JSON-file job queue with content-derived idempotency keys.
- Markdown inbox intake that creates project proposals and clarification lists.
- Append-only JSONL run events, three Markdown role definitions, pause
  switch, systemd unit templates, migration notes, and automated tests.
- Role-context compilation, task enqueue/preparation, and an allowlisted Telegram
  long-polling gateway with structured commands.
- A serialized OpenCode executor using local Lemonade models, dedicated permissions,
  per-job output capture, timeouts, and durable completion/failure states.
- Resource-aware per-job model selection with explicit overrides, recorded rationale,
  and an immutable-at-enqueue inventory snapshot.

## Deliberately deferred

- Automatic retries, privileged approval state transitions,
  worker dispatch, hardware/Vivado access, and service activation.
- The autonomy boundary and AMD data-handling constraints still require David's
  decisions before unattended execution expands beyond proposal generation.
