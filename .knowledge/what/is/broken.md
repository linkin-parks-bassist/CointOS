---
status: green
revised_at: "2026-09-26T08:11:27+10:00"
checked_at: "2026-09-20T13:15:27+10:00"
---

The prior operational fault was sticky emergency incident `20260925T162248Z-0`: both Sole Survivor attempts failed required-artifact acceptance and ordinary intake remained draining. The incident is now recovered and the guard has an installed automatic, rate-limited survivor escalation path. Live escalation has not yet been qualified; source checks and an active guard restart do not prove it can resolve every incident. See `what/is/the/state.md` and `why/is/resource/incident/20260925t162248z-0/still/in/emergency/after/survivor/retry.md`.

The main scheduler is implemented and has live evidence for two simultaneous CointOS workers, queued dispatch, automatic profile growth/shrink, idle residency reclamation and exact cleanup. The repaired dispatch wake, sibling cancellation, pressure priority, live multi-model selection, failed-profile rollback, throughput/MTP and some restart behavior still need bounded live qualification after recovery. A named Qwen model or fixed slot count is not the design limit.

Open product and operational risks:

- A nominal OpenCode stop can still falsely complete a job with no explicit acceptance evidence, although declared nonempty artifact checks now fail missing/empty files and conservative structured incomplete handoffs continue the same session. Owner: `why/can/a/worker/be/falsely/completed/after/a/tool/call.md`.
- Quiescent worker leases accumulate: 2,253 entries in 2.86 MB. The read-only parse is about 0.02 seconds, not evidence of a current write bottleneck. Replays require exact historical IDs, so pruning by old monotonic time or a newest-tail count is unsafe. Owner: `why/are/quiescent/worker/leases/retained.md`.
- Historical notification failures need human disposition; do not auto-replay delivery-unknown messages. Owner: `why/did/cointos/notifications/fail/to/deliver.md`.
- The fixed 32 GiB host, 8 GiB coin/control and 12 GiB load-transient reserves need live measurement; proxy transport ceilings need comparison with legitimate maximum-context payloads. Owners: `what/is/the/local/strix/halo/resource/policy.md` and `why/does/cointos/limit/inference/proxy/transport/sizes.md`.
- `maximum_work_models: 1` limits distinct work models, not parallel lanes. Concurrent different work models are not qualified within the current two-position backend with a pinned control model. Owner: `what/is/the/work/model/residency/limit.md`.
- Cointelprofessional operational prose and conversational endings need improvement, and demanding answers need an evidence-based verification policy. Owner: `what/is/intended/control_plane.md`.
- The reported size of `gpt-oss-120b-mxfp-GGUF` conflicts with registry size; keep it quarantined pending provenance reconciliation.

Governing rule: physically available capacity must reach an authorized active request within reasonable reconciliation time. Real contention should queue or suspend retained work; ghosts, stale observations and arbitrary scarcity constants must not become terminal denials.
