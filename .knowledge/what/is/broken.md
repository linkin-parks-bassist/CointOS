---
status: "unverified"
updated_at: "2026-09-17T12:25:23+10:00"
source: "2026-09-17 reconciliation of source, installed runtime, live services, and owning defect leaves"
---

Current #1 is qualification and simplification of abundance-first inference scheduling. The main acquisition path is implemented and live-proven for ordinary acquisition, unloaded-model loading, idle residency reclamation, park/reacquire, dead-owner recovery, context rerouting, cancellation, service-restart recovery, and cleanup. The remaining risks are unexplained fixed resource margins and transport ceilings, rather than a known generic refusal of available capacity.

## Open defects and unresolved risks

- **Fixed memory reserves.** The 32 GiB protected-host, 8 GiB control, 12 GiB model-load transient, and 64 GiB unknown-model values have duplicated legacy/current forms and incomplete measurement. Safety slack is legitimate; unexplained or stale arithmetic is not. Owner: `what/is/the/local/strix/halo/resource/policy.md`.
- **Proxy transport ceilings.** Header, request-body, stream-buffer, completed-JSON, and backend-observation limits protect bounded protocol handling, but their exact values have not been compared with legitimate maximum-context payloads. Owner: `why/does/cointos/limit/inference/proxy/transport/sizes.md`.
- **Work-residency policy.** `maximum_work_models: 1` has not been fully reconciled with two Lemonade LLM residency positions, the pinned fast model, idle reclamation, and future concurrent work-model use.
- **Cointelprofessional verification quality.** Transport loss, output starvation, cancellation interruption, arbitrary tool rounds, crash attempts, SIGALRM, and elapsed inference timeout are repaired. Demanding answers still need an evidence-based reviewer/verifier policy. Owner: `why/did/cointelprofessional/fail/to/prove/the/sylow/theorems/promptly/and/correctly.md`.
- **Quarantined model metadata.** Lemonade reports `gpt-oss-120b-mxfp-GGUF` as 1.48 GiB while the installed registry records 63.4 GiB. Do not admit it until provenance is reconciled. Owner: `why/does/the/gpt/oss/120b/mxfp/registry/size/report/1/48/gib.md`.
- **Verification-process supervision.** Duplicate abandoned test processes once survived for roughly 94 minutes. No active recurrence is established; preserve exact wait evidence before cleanup if it recurs. Owner: `why/did/operator/inference/tests/remain/running.md`.

## Repaired restriction families

At least nineteen spec-less or physically false barriers have been removed or replaced with retained continuation: exact OpenCode patch allowlisting; 4096-token worker output; 96-token front truncation; six deep tool rounds; 1400-token deep output; three deep crash attempts; ten-minute deep SIGALRM; 180-second deep inference cancellation; unconditional trusted-contact task refusal; mandatory workspace/task-contract paperwork; mandatory unloaded parameter count; synthetic context quantum; denial before idle reclamation; missing unloaded realization; duplicate legacy realization admission; terminal ordinary-agent budgets; prompt-level elapsed/attempt stops; 0.2-second cleanup; and exactly-four proxy handlers.

Other completed repairs include credential-preserving park/reacquire, dead-controller gated relaunch, semantic OpenCode error rerouting despite exit zero, queue head-of-line starvation removal, absent-deadline propagation, ready-state hot-loop prevention, caller-scoped progress/cancellation, proxy socket shutdown, dynamic parallel default one, measured retention of Qwen3.8 batch/ubatch 512/128, removal of the stale saved reasoning cap, and exact-session recovery after executor-service death.

Current governing rule: physically available capacity must propagate to an authorized active request within reasonable reconciliation time. Queue or suspend retained work for real contention; never deny it because of ghosts, stale observations, package versions, duplicated policy, or arbitrary scarcity-shaped constants.

## Installed recovery qualifications (2026-09-17)

Saturated priority qualification used real priority-550 managed Qwen3.8 work while priority-900 native control requests completed three times. It repaired CLI contract friction, observable-session parsing, queued-ghost preemption, and durable preemption intent; the exact session resumed and cancellation left resources clean.

Executor-service restart qualification killed only the active `agent-ecosystem.service` executor while a managed Qwen3.8 job held the backend. Recovery first retained resources until termination evidence was available, then revoked/released them, recovered exact session `ses_f52d75868ffevd43LBnP23G16y` from the durable observable event, and resumed generation 2 with that same session. Final cancellation left no owned process or lease. Owner: `how/does/cointos/recover/a/managed/worker/after/executor/service/restart.md`.
