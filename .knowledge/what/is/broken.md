---
status: "unverified"
updated_at: "2026-09-17T12:53:53+10:00"
source: "2026-09-17 reconciliation of source, installed runtime, live services, and owning defect leaves"
---

Current #1 is qualification and simplification of abundance-first inference scheduling. The main acquisition path is implemented and live-proven for ordinary acquisition, unloaded-model loading, idle residency reclamation, park/reacquire, dead-owner recovery, context rerouting, cancellation, service-restart recovery, and cleanup. The false 64 GiB capacity cap and dead legacy 108 GiB load gate are removed. Remaining risks are the rationale and possible duplication of the 32 GiB protected-host, 8 GiB control, and 12 GiB load-transient margins, plus transport ceilings.

## Open defects and unresolved risks

- **Remaining fixed memory reserves.** The active byte-form policy retains 32 GiB protected host memory, 8 GiB control reserve, and 12 GiB model-load transient reserve in both `physical_capacity` and `inference_capacity`. Their current rationale, duplication, and combined effect still need measurement. Owner: `what/is/the/local/strix/halo/resource/policy.md`.
- **Proxy transport ceilings.** Header, request-body, stream-buffer, completed-JSON, and backend-observation limits protect bounded protocol handling, but their exact values have not been compared with legitimate maximum-context payloads. Owner: `why/does/cointos/limit/inference/proxy/transport/sizes.md`.
- **Work-residency policy.** `maximum_work_models: 1` has not been fully reconciled with two Lemonade LLM residency positions, the pinned fast model, idle reclamation, and future concurrent work-model use.
- **Cointelprofessional verification quality.** Transport loss, output starvation, cancellation interruption, arbitrary tool rounds, crash attempts, SIGALRM, and elapsed inference timeout are repaired. Demanding answers still need an evidence-based reviewer/verifier policy. Owner: `why/did/cointelprofessional/fail/to/prove/the/sylow/theorems/promptly/and/correctly.md`.
- **Quarantined model metadata.** Lemonade reports `gpt-oss-120b-mxfp-GGUF` as 1.48 GiB while the installed registry records 63.4 GiB. Do not admit it until provenance is reconciled. Owner: `why/does/the/gpt/oss/120b/mxfp/registry/size/report/1/48/gib.md`.
- **Verification-process supervision.** Duplicate abandoned test processes once survived for roughly 94 minutes. No active recurrence is established; preserve exact wait evidence before cleanup if it recurs. Owner: `why/did/operator/inference/tests/remain/running.md`.

## Repaired restriction families

Removed or replaced barriers include exact OpenCode patch allowlisting; 4096-token worker output; 96-token front truncation; six deep tool rounds; 1400-token deep output; three deep crash attempts; ten-minute deep SIGALRM; 180-second deep inference cancellation; unconditional trusted-contact task refusal; mandatory workspace/task-contract paperwork; mandatory unloaded parameter count; synthetic context quantum; denial before idle reclamation; missing unloaded realization; duplicate legacy realization admission; the dead 64 GiB unknown-model fallback; the false `min(64 GiB sysfs domain, 100 GiB hardware capability)` cap; terminal ordinary-agent budgets; prompt-level elapsed/attempt stops; 0.2-second cleanup; and exactly-four proxy handlers.

Other completed repairs include credential-preserving park/reacquire, dead-controller gated relaunch, semantic OpenCode error rerouting despite exit zero, queue head-of-line starvation removal, absent-deadline propagation, ready-state hot-loop prevention, caller-scoped progress/cancellation, proxy socket shutdown, dynamic parallel default one, measured Qwen3.8 batch/ubatch 512/128, stale reasoning-cap removal, and exact-session recovery after executor-service death. The ancient unroutable Kaelen Steward record and its Admin deletion job were terminalized on 2026-09-17 so they no longer pollute current lifecycle summaries.

Current governing rule: physically available capacity must propagate to an authorized active request within reasonable reconciliation time. Queue or suspend retained work for real contention; never deny it because of ghosts, stale observations, package versions, duplicated policy, or arbitrary scarcity-shaped constants.
