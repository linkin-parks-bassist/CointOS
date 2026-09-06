# Production model metadata — Astra, 2026-09-06

Next approved R2 gap after conservative OBS-3 live acceptance: models.snapshot
lacks backend metadata; dispatch uses the ignored operator commissioning helper.
That helper is not production qualification. Never infer facts from model names.

Sieve's read-only `local-r2-metadata-map` found the snapshot/normalizer seam but
hallucinated ecosystem/backend_observation.py and attributed registry normalization,
launch-path matching and slot/context checks to backend_snapshot. Astra rejected
that claim: the real helper is in inference_proxy.py with a different contract.
The map changed no code; its worker lease closed automatically.

Worktree /home/david/.worktrees/cointos-mvp-model-metadata, branch
fix/mvp-model-metadata, base 1ab3e7b. Baseline: 19 model-admission tests pass.
Packets/transcripts: ignored .superpowers/sdd/2026-09-05-cointos-mvp-index/.

- R2-M1 running: pure _observed_model_record in models.py, synthetic tests only.
  Verify measured parameters/bytes/context, exact backend/launch path agreement,
  slot divisibility and explicit tool support. Qualify observed resident allocation
  only; reject missing/contradictory facts. No transport/caller changes yet.
- R2-M2 next: bounded local read-only backend metadata transport and snapshot
  composition, preserving owner boundaries and truthful unqualified reasons.
  Reuse normalized facts for resident capacity; no inferred metadata fallback.
- R2-M3 next: independent combined tests and read-only comparison of production
  snapshot with observed backend facts. Retire commissioning override only after
  real production admission is demonstrated under approved boundaries.

This does not close arbitrary model/context qualification, R4-PRECISE, operator
leases, autonomous MVP or protected deployment acceptance.
