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

- R2-M1 code accepted: local 881e7e1/3a1c3a4 -> 34456c8/dcd1add. Pure
  _observed_model_record verifies measured parameters/bytes/context, exact
  backend/launch paths, slot divisibility and explicit tool support. Qualifies
  observed resident allocation only. Astra independently passed 29 focused tests
  and normalized actual metadata from both loaded models with read-only GETs.
  No snapshot caller yet; this is not production dispatch acceptance.
- Coordinator correction: original packet wrongly equated Lemonade registry
  context_length with backend n_ctx_train. Real 4B facts: registry/total 65536,
  slots 2, per-sequence 32768, training maximum 262144; 27B registry/total 131072,
  slot 1, training maximum 262144. Corrected tests preserve those separate meanings
  and registry_context_length diagnostic. Backend URLs end /v1; provenance now
  correctly names root /v1/models and /props, not /v1/v1/models.
- R2-M2A running: bounded metadata-only loopback HTTP reader in models.py. No
  completions, lifecycle control or new inference path. Pure transport tests.
- R2-M2B next: snapshot composition with truthful unqualified reasons and fresh
  backend identity/config recheck. Reuse normalized resident facts for capacity;
  no guessed metadata fallback or duplicated route selection.
- R2-M3 next: independent combined tests and read-only comparison of production
  snapshot with observed backend facts. Retire commissioning override only after
  real production admission is demonstrated under approved boundaries.

This does not close arbitrary model/context qualification, R4-PRECISE, operator
leases, autonomous MVP or protected deployment acceptance.
