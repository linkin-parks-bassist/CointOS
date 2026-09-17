---
status: "unverified"
updated_at: "2026-09-17T15:00:33+10:00"
source: "source and installed qualification through task-4894b791ecbcbafc 2026-09-17"
---

Current #1 is qualification and simplification of abundance-first inference scheduling. The main acquisition path is implemented and live-proven for ordinary acquisition, unloaded-model loading, idle residency reclamation, park/reacquire, dead-owner recovery, context rerouting, cancellation, service-restart recovery, backend-restart reconciliation, cleanup, and multi-step retained-session continuation. The false 64 GiB capacity cap and dead legacy 108 GiB load gate are removed. Physical reserve values have one configuration owner under `physical_capacity`, and their production arithmetic is mapped.

## Open defects and unresolved risks

- **Remaining fixed memory reserves.** The active byte-form policy retains 32 GiB protected host memory, 8 GiB coin/control reserve, and 12 GiB model-load transient reserve. All three stack in host admission; transient also enters GTT admission. Their values still need live measurement. Owner: `what/is/the/local/strix/halo/resource/policy.md`.
- **Semantic-stop wrapper qualification.** Tool-call and no-finish transport exits now continue the retained session, and the reserve-audit worker reached a real final stop. The installed wrapper now terminates the attached client immediately at explicit stop so post-response housekeeping cannot trigger another scheduler rotation; live-qualify that prompt exit on the next managed task. Owner: `why/can/a/worker/be/falsely/completed/after/a/tool/call.md`.
- **Proxy transport ceilings.** Header, request-body, stream-buffer, completed-JSON, and backend-observation limits protect bounded protocol handling, but their exact values have not been compared with legitimate maximum-context payloads. Owner: `why/does/cointos/limit/inference/proxy/transport/sizes.md`.
- **Work-residency policy.** `maximum_work_models: 1` has not been fully reconciled with two Lemonade LLM residency positions, the pinned fast model, idle reclamation, and future concurrent work-model use.
- **Cointelprofessional verification quality.** Transport loss, output starvation, cancellation interruption, arbitrary tool rounds, crash attempts, SIGALRM, and elapsed inference timeout are repaired. Demanding answers still need an evidence-based reviewer/verifier policy.
- **Quarantined model metadata.** Lemonade reports `gpt-oss-120b-mxfp-GGUF` as 1.48 GiB while the installed registry records 63.4 GiB. Do not admit it until provenance is reconciled.

## Repaired restriction families

Removed or replaced barriers include exact OpenCode patch allowlisting; 4096-token worker output; 96-token front truncation; six deep tool rounds; 1400-token deep output; three deep crash attempts; ten-minute deep SIGALRM; 180-second deep inference cancellation; unconditional trusted-contact task refusal; mandatory workspace/task-contract paperwork; mandatory unloaded parameter count; synthetic context quantum; denial before idle reclamation; missing unloaded realization; duplicate legacy realization admission; the dead 64 GiB unknown-model fallback; the false `min(64 GiB sysfs domain, 100 GiB hardware capability)` cap; terminal ordinary-agent budgets; prompt-level elapsed/attempt stops; 0.2-second cleanup; exactly-four proxy handlers; duplicated physical reserve configuration; unconditional ordinary-task verifier spawning; and fairness time charged during retained-session prefill.

Other completed repairs include credential-preserving park/reacquire, active-parking wait without reacquire contention, failed-park rollback, dead-controller gated relaunch, backend-instance restart reconciliation, semantic OpenCode error rerouting despite exit zero, tool-call/no-finish retained-session recovery, queue head-of-line starvation removal, absent-deadline propagation, ready-state hot-loop prevention, caller-scoped progress/cancellation, proxy socket shutdown, dynamic parallel default one, measured Qwen3.8 batch/ubatch 512/128, stale reasoning-cap removal, and exact-session recovery after executor-service death.

Current governing rule: physically available capacity must propagate to an authorized active request within reasonable reconciliation time. Queue or suspend retained work for real contention; never deny it because of ghosts, stale observations, package versions, duplicated policy, or arbitrary scarcity-shaped constants.