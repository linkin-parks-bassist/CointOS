---
status: green
revised_at: "2026-09-26T06:41:58+10:00"
---

`ecosystem.watchdog.tick` serializes under `state/watchdog.lock` and calls `managed_inference.reconcile_dead_callers(cli.ROOT)` before qualitative review. It stores the `last_native_recovery` result on both review and idle paths. Reconciliation is responsible for preserving live or unknown callers and requires verified backend termination before releasing dead-caller capacity. The watchdog review prompt refers to installed-runtime `cli.ROOT/state/conversations`, not retired checkout state paths.

The current source and installed `ecosystem/watchdog.py` copies match. Bounded isolated tick and existing portability/runtime-root checks passed during the wiring change; live caller-death/restart qualification remains pending. The periodic verifier-link repair is a separate concern, owned by `how/does/cointos/durably/enqueue/a/verifier/without/duplicates.md` for new jobs.
