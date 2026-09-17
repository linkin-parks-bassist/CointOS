---
status: "unverified"
updated_at: "2026-09-18T00:15:18+10:00"
source: "installed user-directed scheduling qualification and supervised compaction incident 2026-09-17"
---

Current #1 is qualification and simplification of abundance-first inference scheduling. The main acquisition path is implemented and live-proven for ordinary acquisition, unloaded-model loading, idle residency reclamation, park/reacquire, dead-owner recovery, context rerouting, cancellation, whole-system restart recovery, backend-restart reconciliation, cleanup, and multi-step retained-session continuation. The false 64 GiB capacity cap and dead legacy 108 GiB load gate are removed. Physical reserve values have one configuration owner under `physical_capacity`, and their production arithmetic is mapped.

## Open defects and unresolved risks

- **Compaction handoff can falsely complete unfinished work.** Builder `task-33f3571db23d4c29` emitted a structured handoff explicitly saying no edits or acceptance checks were complete, then ended with nominal `stop`; CointOS terminalized the job and closed its observable endpoint. The retained session survives, but no checked managed one-call resume procedure exists. Owner: `why/can/a/worker/be/falsely/completed/after/a/tool/call.md`.
- **Quiescent worker leases accumulate without a retention policy.** The first aggregate observation found 2,084 quiescent records. They do not consume execution, but the whole state document grows indefinitely. Safe pruning shape is known; the justified replay window/count is not. Owner: `why/are/quiescent/worker/leases/retained.md`.
- **Notification incident reporting still names a dead event.** Delivery acquisition and cleanup are repaired and the stranded notification delivered, but the watchdog findings filter still looks for `outbox.delivery_failed`, which the notifier does not emit. It should consume the new state-based delivery summary. Owner: `why/did/cointos/notifications/fail/to/deliver.md`.
- **Remaining fixed memory reserves.** The active byte-form policy retains 32 GiB protected host memory, 8 GiB coin/control reserve, and 12 GiB model-load transient reserve. Their values still need live measurement. Owner: `what/is/the/local/strix/halo/resource/policy.md`.
- **Proxy transport ceilings.** Bounded protocol limits have not been compared with legitimate maximum-context payloads. Owner: `why/does/cointos/limit/inference/proxy/transport/sizes.md`.
- **Work-residency policy.** `maximum_work_models: 1` has not been fully reconciled with two Lemonade LLM residency positions, the pinned fast model, idle reclamation, and future concurrent work-model use.
- **Cointelprofessional progress prose and conversational endings are poor.** Repaired unsolicited delivery exposed operational messages that were unclear or partly nonsensical, and routine replies repeatedly ended with canned chatbot engagement questions. Progress must state the concrete change, result, and consequence; generic follow-up solicitations should be omitted unless an answer is required. Owner: `what/is/intended/control_plane.md`.
- **Cointelprofessional verification quality.** Demanding answers still need an evidence-based reviewer/verifier policy.
- **Quarantined model metadata.** Lemonade reports `gpt-oss-120b-mxfp-GGUF` as 1.48 GiB while the installed registry records 63.4 GiB. Do not admit it until provenance is reconciled.

## Repaired restriction and failure families

Installed generation agreement now has an atomic post-swap stamp and read-only systemd observer. After the whole-system restart, all six service members live-qualified as installed-path, post-stamp `ok`; unavailable observation cannot collapse into a healthy action.

Recognized user-directed task creation is now durable scheduler provenance. Exact local CLI origin and syntactically valid authenticated Telegram contact origin enter the existing user-driven band; every other origin omits the field. The installed local path live-scored 850 instead of the former 250, while direct checks preserved Sole Survivor 1000 and Coin 900 above it and aged background work below it.

Notification delivery now treats cancelled dependencies as terminal, acquires the fast control model through managed inference when no context is injected, and releases capacity from a terminal successful response when no backend slot identity exists and no request remains in flight. Installed live qualification delivered the formerly waiting record in one attempt. The watchdog persists notification state counts and oldest pending time.

Server-side OpenCode continuation is live-qualified: after a tool call the wrapper mirrors the server-produced report and explicit stop without injecting another user continuation or replaying the tool.

The control worker no longer limits eligible deep turns to two controller children. Verified model realization refreshes inventory before runner admission. Fairness rotation applies only between equal-priority jobs. The watchdog preserves healthy managed workers before abandoned-owner cleanup.

Removed or replaced barriers include exact OpenCode patch allowlisting; 4096-token worker output; 96-token front truncation; six deep tool rounds; 1400-token deep output; three deep crash attempts; ten-minute deep SIGALRM; 180-second deep inference cancellation; unconditional trusted-contact task refusal; mandatory workspace/task-contract paperwork; mandatory unloaded parameter count; synthetic context quantum; denial before idle reclamation; missing unloaded realization; duplicate legacy realization admission; the dead 64 GiB unknown-model fallback; the false `min(64 GiB sysfs domain, 100 GiB hardware capability)` cap; terminal ordinary-agent budgets; prompt-level elapsed/attempt stops; 0.2-second cleanup; exactly-four proxy handlers; duplicated physical reserve configuration; unconditional ordinary-task verifier spawning; fairness time charged during retained-session prefill; and the fixed two-controller gate.

Other completed repairs include watchdog finding cadence, exact-session promotion, requested-model routing, ghost-lease reconciliation, parked-session cancellation and reacquisition, dead-controller relaunch, backend-restart reconciliation, semantic OpenCode error rerouting, queue starvation removal, absent-deadline propagation, ready-state hot-loop prevention, caller-scoped progress/cancellation, proxy shutdown, dynamic parallel default one, measured Qwen3.8 batch/ubatch 512/128, stale reasoning-cap removal, exact-session executor recovery, whole-system generation control, and control-turn retry backoff.

Current governing rule: physically available capacity must propagate to an authorized active request within reasonable reconciliation time. Queue or suspend retained work for real contention; never deny it because of ghosts, stale observations, package versions, duplicated policy, or arbitrary scarcity-shaped constants.
