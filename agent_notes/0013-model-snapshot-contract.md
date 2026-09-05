# Verified model snapshot contract

**Maintainer:** Codex agent Curie (`/root/r2_snapshot_completion`), 2026-09-05.

`models.snapshot()` is the fingertip which converts Lemonade registry/health data,
Linux memory, amdgpu sysfs counters, and accepted local policy into the model-routing
inventory. Parameter count, model bytes, capabilities, advertised context, context
quantum, backend total context, parallel sequences, and per-sequence context remain
separate facts. Missing registry or health fields remain `None`/unverified; model
names never supply metadata.

The host record carries exact byte counts and measured GTT freshness. The resource
envelope caps GTT at the lesser of the fresh measurement and the configured 100 GiB
boundary while retaining the 32 GiB protected-host, 8 GiB Coin, and 12 GiB load
transient reserves as separate fields. `resident_models` is shaped for R3. Lemonade's
structured `llamacpp_args` is decoded only at this fingertip to observe `--parallel`;
control/work classification uses the explicit configured control model identity.

Scheduling comes only from Q1's accepted `state/scheduling-policy.json`. The legacy
`config/model-policy.json` is not treated as a scheduling snapshot. It contributes
only the explicit control model identity used for residency classification.

Current production admission requires the registry to expose explicit
`parameter_count`, `size_bytes`, `capabilities`, `context_length`,
`supported_context_quantum`, and `parallel_sequences`. If Lemonade omits any of
these, that model is honestly deferred until a trusted metadata producer supplies
them; no catalogue facts were invented in this change.
