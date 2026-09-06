# 0012: Temporary conservative backend release

Status: accepted by David, 2026-09-06; Astra coordinates implementation.

## Decision and scope

For MVP, ordinary runner close may automatically reconcile its inference lease
only after the exact worker has ended, its proxy claims are drained and closed
against further admission, and every physical slot on its recorded backend
instance is freshly observed idle. Backend identity includes model, endpoint,
PID/start identity, boot and observed model/slot configuration. Missing, changed,
busy or unreadable facts leave reconciliation required; no HTTP EOF, timeout,
worker exit or caller-supplied flag alone proves backend absence.

The proxy remains the single owner of backend HTTP and release evidence. Use
plain functions/data and its existing R3/R4 attestation boundary, not a new
scheduler or policy framework. Evidence is append-only JSONL without prompts,
credentials or unrelated user data. Label this proof `reconciled_absent`, not a
fabricated request/physical-slot termination. Work correctness remains a separate
semantic verification decision. This check does not kill or unload anything.

This is deliberately temporary. Unrelated activity on the SAME backend may
delay release; other model backends need not be idle. No automatic retry loop or
broader service activation is authorized by this record alone.

## Required successor: precise per-request physical-slot observation

**Open follow-up R4-PRECISE; not optional cleanup or a completed R4 milestone.**
The next R4 integration owner must consult the tracked task in
`docs/superpowers/plans/2026-09-06-backend-observation-repair.md` and report its
state at bring-up/acceptance checkpoints. Keep it linked from `docs/status.md`
until verified and integrated. Trigger implementation after conservative live
bring-up, before claiming complete concurrent-backend release support.

1. Establish a backend-native request identifier and authoritative mapping from
   proxy claim to actual physical slot AND backend incarnation. Do not infer this
   mapping from R3's logical lease sequence number.
2. Observe normal completion/cancellation for that exact request; bind immutable
   evidence to claim, run generation, lease allocation generation and backend
   identity. A stream terminal marker is sufficient only if the backend contract
   demonstrably attests the required termination, not merely socket closure.
3. Replace the all-slots-idle requirement with that precise observation behind
   the proxy's same release interface; preserve no-proof/no-release behavior.
4. Prove two concurrent requests can release independently while the unrelated
   slot remains busy; also prove wrong/stale/reused slot and backend identities,
   duplicate ends, cancellation races and subsequent requests cannot release the
   wrong allocation. Add one bounded live acceptance case.
5. Retire the temporary path once the supported production backend passes these
   tests, or explicitly document any remaining backend-specific limitation.

Do not let a green conservative test suite close R4-PRECISE. Record successor
implementation/verification commits here and in status when that work is done.
