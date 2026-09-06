# Backend observation repair and required precise successor

Owner: Astra (hosted coordinator), local Sieve/Qwen implementation.
Authority: David approved conservative MVP release with a visible precise successor.
Decision: [0012](../../decisions/0012-temporary-conservative-backend-release.md).

One deliverable per local packet; isolated worktree, local inference, no pushes.
Read only the named functions/fixtures; red regressions before source changes,
focused verification per packet, combined suite and independent review before
integration. No artificial short wall-clock worker kill; use explicit evidence,
file and edit-cycle boundaries. Runtime evidence stays append-only and ignored.

## Conservative MVP implementation

- [ ] OBS-1: Add bounded read-only backend identity/idle-observation functions
  under inference_proxy's ownership. Verify all-slot completeness, identity,
  busy/missing/unreadable data and sanitized evidence using synthetic responses.
- [ ] OBS-2: Record identity before forwarding; close admission and observe fresh
  backend absence only after the bound runner/claims end. Persist evidence before
  returning it; preserve `reconciled_absent` through R3 release. Reuse the existing
  enforcement fixture; retain false-EOF/forged-proof regressions.
- [ ] OBS-3: Independently review/run combined tests, integrate reviewed commits,
  then perform controlled live activation/smoke under the existing approval and
  admission boundaries. A committed patch is not live acceptance.

## R4-PRECISE — REQUIRED, OPEN

Trigger: after conservative live bring-up, before claiming complete concurrent
backend release support. Owner: next R4 integration agent, coordinated by Astra
or the current authorized coordinator. This is an explicit uncompleted deliverable,
not a suggestion to future agents to audit everything.

- [ ] P1: Inspect the installed backend's native request/physical-slot lifecycle
  contract. Record a demonstrated claim -> request -> slot/incarnation mapping;
  escalate if the backend lacks an adequate trustworthy observation interface.
- [ ] P2: Implement exact normal-end/cancel observation behind the same proxy
  release boundary, preserving claim/run/lease generation binding.
- [ ] P3: Verify independent release under two concurrent requests; reject stale,
  wrong and reused identities and cancellation/subsequent-request races.
- [ ] P4: Run one bounded live concurrent-release case, integrate, remove the
  conservative all-slots-idle restriction for supported production backends,
  and update decision 0012 plus status with evidence/commits.

Stopping condition: the specified packet is verified, or an honest partial
handoff identifies the missing evidence/authority. Do not mark R4 complete while
R4-PRECISE remains open.
