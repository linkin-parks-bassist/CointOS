---
status: "unverified"
created_at: "2026-09-14T23:26:35+10:00"
scope: "local"
source: "ecosystem/telegram.py main/accept_update/generate_first_response, control_worker.py process_turn, control_agent.py respond, inference.py request; safe default-path reproductions 2026-09-14"
updated_at: "2026-09-14T23:37:19+10:00"
---

Production fast and deep Telegram response paths are not wired to inference admission. telegram.main calls accept_update without inference_context; control_worker.process_turn calls respond without inference_context. Their default generation functions forward only messages/settings to inference.request, which immediately requires a lease dictionary and a 32-byte credential. Both default paths reproducibly raise ValueError: an admitted lease and 32-byte credential are required, before network access. Injected infer callbacks in existing tests bypass this boundary. Re-enabling stopped units alone cannot restore responses. Wire front/deep acquisition, bounded waiting/preemption, credential issuance and verified cleanup through the existing capacity/proxy owners; preserve mandatory admission rather than restoring direct backend calls. Qualification must cover the actual default production paths and cleanup/restart, not just injected inference.

Source repair: default fast/deep response functions now invoke managed_inference.request automatically when no explicit inference context is supplied. Three real subprocess/client/HTTP-proxy tests pass, including both default Telegram functions with fresh observation injection only. The historical missing-credential reproduction describes the pre-repair code; live backend/service adoption remains unqualified. See `how/does/automatic/native/inference/acquisition/work.md`.
