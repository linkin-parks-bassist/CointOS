---
status: "unverified"
created_at: "2026-09-14T22:40:40+10:00"
scope: "local"
source: "Independently inspected current source and design decisions in this turn; isolated real OpenCode read-back and named tests; 2026-09-14"
updated_at: "2026-09-14T22:42:45+10:00"
---

The launch producer reads Lemonade /v1/models and /api/v1/health, selects a downloaded registry model and resident backend, then reads that backend's /v1/models and /props. observe_opencode_backend_capacity reuses _observed_model_record to require model-name/path agreement, a live PID/launch command, tool-capability consistency, parameter/size metadata agreement and a supported allocation layout. meta.n_ctx, launch --ctx-size/--parallel and total_slots determine per-request capacity; meta.n_ctx_train is a model ceiling, not the current allocation.

Fixed layout requires pool divisible by slots and per-sequence == pool/slots. Explicit unified layout uses its verified per-sequence cap without dividing again. Unproven/contradictory layouts return None; unknown capacity never receives the training maximum as fallback. The record carries backend URL/PID/command/fingerprint and observation time. The observer reports no measured backend output ceiling; that absence must not be presented as a measured numeric maximum. Code owners: ecosystem/models.py _observed_model_record, observe_opencode_backend_capacity; ecosystem/context_layout.py observed_context_layout; ecosystem/executor.py _observe_worker_capacity. Startup reobservation is owned by how/does/cointos/verify/opencode/resolved/limits/before/inference.md.

The launch producer now requires exactly one downloaded registry match and resident match. It reads the kernel process identity before/after backend document collection and rereads Lemonade health, requiring model name, URL, PID, loaded/alive flags, recipe options and launch command unchanged. Busy/streaming transitions are not identity changes. This avoids combining props from one allocation with residency from another; ambiguity or a changed/reused PID yields no capacity. Tests inject duplicate registry/resident records and an incarnation change before normalization.
