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

- [x] OBS-1: Add bounded read-only backend identity/idle-observation functions
  under inference_proxy's ownership. Verify all-slot completeness, identity,
  busy/missing/unreadable data and sanitized evidence using synthetic responses.
  Integrated `b17c8fc` + `4776e15`; Astra independently passed 43 focused tests.
- [x] OBS-2A: Record identity before forwarding; retain a sticky unknown flag
  for absent/changed identity. Integrated `5e4f333`; Astra independently passed
  83 observer/enforcement/executor tests. No release changes in this packet.
- [x] OBS-2B: Close admission and observe fresh
  backend absence only after the bound runner/claims end. Persist evidence before
  returning it; preserve `reconciled_absent` through R3 release. Reuse the existing
  enforcement fixture; retain false-EOF/forged-proof regressions. Integrated
  `f4fc438`; reviewed by Astra, including evidence ordering and real-R3 probe.
- [x] OBS-3 code acceptance: independently review and integrate reviewed commits.
  Astra passed 553 discovered tests plus 33 separately invoked integration tests
  on the integrated tree (586 total). Synthetic fresh proof -> real R3 release
  -> proxy revocation also passed without mocking R3.
- [ ] OBS-3 live acceptance: controlled activation/smoke under the approval and
  admission boundaries. Await explicit approval to restart the existing transient
  proxy with reviewed bytes and perform one bounded admitted smoke. No new service,
  Telegram access, credentials, backend unload or broader activation implied.
  A committed patch is not live acceptance.

## R4-PRECISE — REQUIRED, OPEN

Trigger: after conservative live bring-up, before claiming complete concurrent
backend release support. Owner: next R4 integration agent, coordinated by Astra
or the current authorized coordinator. This is an explicit uncompleted deliverable,
not a suggestion to future agents to audit everything and not an added gate on
conservative MVP acceptance. Report the temporary limitation at that acceptance.

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
handoff identifies the missing evidence/authority. Conservative R4 acceptance
must state its limitation; do not close R4-PRECISE on the strength of that proof.
