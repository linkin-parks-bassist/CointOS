# Current status

Production model metadata is integrated through `4372020`; Astra independently
passed 613 tests and compared real snapshot/model-selection results with backend
facts. The commissioning metadata override is removed from dispatch. The next
local packet, `local-r8-launch-review`, was admitted using production snapshot
alone and completed with normal automatic release, finishing the scoped metadata
live checkpoint. [Operator launch cleanup](../agent_notes/0017-operator-launch.md)
is now integrated through `faae7ad`: registered-before-exec gate, truthful cleanup
and durable setup-failure evidence. Astra independently passed 622 tests
(589 discovered + 33 integration), plus a real-child gate-release failure probe.
This is bounded R8 launch acceptance, not complete operator inference admission.
Active: [isolated canonical contact work](../agent_notes/0018-canonical-contact.md)
through staging `edd341b`: shared decision validation, durable claim/completion,
one-job dispatch replay after injected final-write failure, and immutable reply
linkage. Astra passed 27 contact tests (earlier dispatch/A1 set: 33). These changes
are NOT in the runtime root: old-route candidate failures and C1 conversion/C2-C4
remain open. Next is read-only legacy shape evidence; no contact cutover or
services changed. See
[metadata checkpoint](../agent_notes/0016-model-metadata.md).

Conservative backend-close observation is live-accepted as David's temporary
MVP path. **R4-PRECISE remains a required open successor**, not optional
hardening: track [implementation and precise-release tasks](superpowers/plans/2026-09-06-backend-observation-repair.md)
and [decision 0012](decisions/0012-temporary-conservative-backend-release.md).
Future R4/bring-up agents must pick up that successor after conservative live
bring-up and before claiming complete concurrent-backend release support.
The adapter, pre-forward identity recording and close-time release wiring are
integrated at `b17c8fc`/`4776e15`/`5e4f333`/`f4fc438`. Astra independently passed
586 tests (553 discovered + 33 integration) and a synthetic real-R3 release probe.
David then approved the existing proxy restart and one admitted live smoke.
`local-r4-live-observer-smoke` returned one response and automatically reached
proxy revoked / R3 released / R1 quiescent using persisted `reconciled_absent`
evidence, with no manual reconciliation. Resources were healthy afterward;
subsequent metadata packets also use the working normal-close path. See
[observer checkpoint](../agent_notes/0015-backend-observation.md).

Bring-up checkpoint, 2026-09-06 (Astra): reviewed local Qwen repairs are
integrated: `99170fb` fixes active attempt/child quota boundaries; `d113c2a`
preserves cumulative task time/output across runner rounds, resets per-run time,
counts final output, and saves usage before backend-close reconciliation.
`0f3802c` makes the explicit new-attempt transition increment the attempts counter;
`1fa017d` stops runner resumes/fresh contexts charging another attempt. Astra
reviewed both diffs and independently passed 511 tests. Earlier verification also
covered a carried-output/wrap-up accounting probe. This does not close all R5/R6
requirements or implement a retry scheduler. David prioritizes MVP existence and plan fidelity
before broad hardening. The overnight task labels do not establish integrated/live acceptance. See
`agent_notes/0014-overnight-review.md` for the bounded review.

David authorized operator reconciliation of the prior-boot emergency and restored
local dispatch. The prior resource state is preserved in the ignored build
ledger; a validated scheduling snapshot is published and the transient
`cointos-mvp-proxy.service` runs the admitted endpoint. Earlier repair workers exited;
their process/backend absence was independently observed and their leases reconciled.
Current worker progress is recorded above and in the ignored dispatch ledger.
Conservative normal-close observation is live-accepted; production model metadata
is integrated as recorded above. This checkpoint does not assert working autonomous dispatch or
end-to-end Coin contact. The earlier implementation observations below are history.

Implementation update, 2026-09-05 (Astra): David approved the [complete MVP bring-up
suite](superpowers/plans/2026-09-05-cointos-mvp-index.md) for implementation and
activation. S0 is preserving the exact dirty planning/source snapshot before the
first worker writes code. No deployment or runtime behavior has changed yet. The
dated implementation observations below are historical, not live telemetry.

Updated: 2026-09-04 (Australia/Sydney)

## Active CointOS reliability build

The project is now named **CointOS**. The checkout remains temporarily at
`/home/david/agent-ecosystem` because the currently live services resolve that
path. Physical relocation is gated on installation of the root-owned permanent
gateway so the rename cannot take Cointelprofessional/CoinToss offline.

The approved reliability suite contains 25 tasks across five plans. Plan 1 is
complete. Plan 2 Task 1 is complete and independently reviewed: exact `RESTART` and
`RESET` recognition, typed records, strict JSON, replay identity, and crash-safe
publication are committed through `5c54511`; focused tests passed 18/18 and the full
suite passed 143/143. Plan 2 Task 2, the pure restart/reset lifecycle reducer, is at
commit `c34f4a4`; focused tests passed 10/10 and the full suite passed 153/153, with
independent review in progress.

Fast-track order: finish and review the Plan 2 reducer, gateway, guardian, and
root-owned packaging; install and smoke-test the model-independent permanent
contact path; then safely swap out the temporary 4B model and bring Halo online for
concrete implementation work. Hosted-model capacity is reserved primarily for
architecture, decomposition, security-sensitive review, and escalation. A bounded
follow-up will project approved plan tasks into dependency-aware, idempotent jobs so
local citizens can continuously discover, claim, test, review, and hand off loose
ends without gaining broader authority.

The existing emergency latch still admits only the failed sole-survivor identity.
Halo was not loaded yet because the resource admission calculation required 56.8
GiB of bounded GTT headroom while 56.6 GiB was available alongside the live 4B
contact model. A direct 4B attempt at the reducer made no durable progress and was
terminated cleanly after repeated context compaction; it left no files or commit.

## Implemented

- Durable filesystem jobs, role-context compilation, recorded model choice, local
  OpenCode execution, independent semantic verification, and dependent results.
- A three-stage Telegram path: durable receipt plus a fast Qwen3.5 4B first response,
  concurrent durable control, and separately supervised result presentation.
- Per-turn action caching and deterministic task idempotency, explicit unknown-
  delivery states, and a transport-owned five-minute disaster fallback.
- One pinned Qwen3.5 4B chatbot/router/emergency model and at most one dynamically
  selected, unpinned work model.
- Model-mediated `use_loaded`/`load`/`defer` dispatch with deterministic resource,
  residency, role-capability, and context validation.
- OpenCode session preemption, priority/time-quantum scheduling, abandoned-run
  recovery, and 75%-full context handoff into a fresh session.
- Kernel OOM detection, dispatch latching, full model unload, and an exclusive
  `sole_survivor` recovery role.
- Periodic deterministic health checks and model-judged Steward assignments.

## Operational state

Checked-in units cover model loading, Telegram intake, two deep-control workers,
background notifications, ecosystem intake/execution, and watchdog stewardship.
Runtime truth must be established from `systemctl --user`, Lemonade, control-turn/job
records, and an end-to-end probe after deployment or reboot; this document is not
live telemetry.

The 2026-09-04 foundation reconciliation repaired the existing user resource guard
after a live restart storm. A single non-OOM pressure sample had entered emergency,
the `sole_survivor` role was rejected, and a correctly loaded but busy model was
treated as absent. The partially committed emergency was then retried once per
second, restarting Telegram, control, and notification services until systemd
rate-limited Telegram. The unit suite still passed because the old resource tests
mocked across the failing composition boundary.

The repaired resource controller now confirms non-OOM pressure over configured
monotonic windows, treats loaded/backend-alive busy or in-use models as live, and
advances a durable fail-closed phase record only after each external effect's
postcondition is observed. Roles are nullable advisory context rather than an
admission boundary. A failed or malformed postcondition leaves the restrictive
phase visible for retry instead of publishing normal operation.

One foreground reconciliation converted the legacy latch into incident
`20260904T033110Z-0`, restored the pinned model, and prepared survivor
`task-e01f5d8c44f8421d`. Six samples over 25 seconds then showed stable resource
guard, Telegram, control-worker, and notifier process identities with zero restarts;
the dirty-checkout suite passed 113/113. That process-stability gate was not semantic
acceptance: the survivor then failed when a 25,523-token request exceeded the
backend's effective 16,384-token per-sequence context (`--ctx-size 32768` shared by
two sequences), and the guard initially repeated the unchanged error each second.

The contained retry corrected and verified backend allocation at total
`ctx_size=65536`, parallel two, preserved the old failed record hashes, and created
canonical replacement `task-a02f3a746e5a0914` as the sole admitted running owner.
Its first 75%-full rollover produced a 3,956-byte semantic handoff and a fresh
session. That session nevertheless reread the full incident and failed when its
33,891-token request exceeded the effective 32,768-token per-sequence capacity. A
foreground tick persisted one deduplicated `context_overflow` emergency-escalation
record for the replacement. The resource guard remains stopped; Telegram and the
notifier retained PIDs 272721 and 272720 with zero restarts.

The resource guard is also disabled at the user-service boot boundary, not merely
inactive for the current session. Telegram and the notifier remain active and
enabled.

Task 4 is therefore safely contained, not fully accepted. Automated completion of
this failure class is deferred to Plan 4's required context-overflow escalation to a
larger safe model/context. Lemonade's configured local API is port 13305.

The root-installed permanent gateway, hard guardian, survival spools, and full
failure-injection acceptance are still future work in the fifth plan of the survival
suite. The currently running user services are not that permanent survival plane.

## Known limits

- Telegram `sendMessage` has no client idempotency key. A crash during a request is
  recorded as `delivery_unknown` and is not replayed automatically.
- General live direct, role-local, and global inter-agent messaging remains specified
  but unimplemented.
- Lemonade exposes no serializable live backend KV cache; continuity therefore uses
  OpenCode sessions, exact prompts, logs, handoff artifacts, and filesystem state.
- Context KV cost is conservatively estimated rather than read from a backend lease
  API; the guard remains authoritative if observed pressure exceeds the estimate.
- Active user-unit status alone does not prove Telegram reachability, model health,
  a renewable subsystem lease, or recovery correctness. Those claims require the
  corresponding process, endpoint, durable-state, and end-to-end observations.
- Resource-guard process stability and one successful context handoff do not prove
  that the replacement session will avoid rereading an oversized incident or finish
  repair. The pending escalation record remains authoritative while the guard is off.
- Existing class-based tests remain incremental no-OOP migration debt.
