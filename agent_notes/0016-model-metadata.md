# Production model metadata — Astra, 2026-09-06

R2 follow-up after conservative OBS-3: production models.snapshot now qualifies
measured backend metadata. The dispatch helper's operator metadata override has
been removed; it calls production_inventory(), a checked models.snapshot only.
Never infer facts from model names or mark unobserved allocations qualified.

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
- R2-M2A code accepted: local dec6fb2 -> 4ee10de; Astra independently passed 38
  model-admission tests. _get_backend allows only numeric-loopback HTTP metadata
  GET /v1/models and /props, timeout 1 second, maximum response 1 MiB; no redirects,
  completions, lifecycle control or new inference path. No live caller yet.
- R2-M2B code accepted: local 56b661e/31a7cab -> dbb4d58/4372020. Snapshot uses
  bounded metadata reads, post-read identity/config recheck and normalized resident
  capacity. Unknown resident facts invalidate inventory. Astra caught a present
  null/empty/non-string endpoint falling back to registry-only verification;
  the correction demonstrated that failure red, then 46 focused tests passed.
- R2-M3: Astra independently passed 580 discovered + 33 integration tests (613)
  on integrated root; read-only production snapshot qualified both loaded models
  and selected Qwen3.8 without the commissioning override. Dispatch helper now
  uses that production path for initial and refreshed admission. First actual
  packet `local-r8-launch-review` is admitted/running; final normal-close evidence
  will complete this checkpoint. No model/service change was needed.

This does not close arbitrary model/context qualification, R4-PRECISE, operator
leases, autonomous MVP or protected deployment acceptance.
