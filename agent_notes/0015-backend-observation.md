# Backend observation bring-up — Astra, 2026-09-06

David approved temporary whole-backend-idle reconciliation, conditional on a
visible path to precise per-request/physical-slot observation. Decision0012 and
the 2026-09-06 backend-observation plan are authoritative; status links both.
R4-PRECISE is required follow-up, NOT an added conservative MVP acceptance gate.

OBS-1 is integrated: local `ca9fcda`/`0733f9a` -> `b17c8fc`/`4776e15`.
The proxy owner now has bounded loopback metadata GET, PID/start/boot identity,
backend snapshot, and before/after exhaustive idle observation functions.
Only sanitized identity/slot-id/processing facts are returned, never prompts.
The adapter is read-only; later packets below wire it into automatic runner release.
Astra independently passed 43 focused tests and reviewed both diffs. The initial
worker needed a correction for dead process state X and function-based assertions;
the correction demonstrated the X regression red before going green.

OBS-2A is integrated: local `c712ca8` -> `5e4f333`. Actual backend identity is
recorded before forwarding, with sticky credential uncertainty. Astra independently
passed 83 observer/enforcement/executor tests. Qwen repaired the EOF test's
unhashable fake upstream, which previously crashed before POST; it now verifies
recording before the real forwarding path while still forbidding EOF-only proof.

OBS-2B is integrated: local `08bd1a4` -> `f4fc438`. Close admission, observe outside
the proxy lock, recheck the exact credential, fsync sanitized append-only evidence,
then publish fresh reconciled_absent proof and preserve its kind through R3.
Astra reviewed those boundaries and independently passed 586 tests on integrated
root: `python3 -m unittest discover -s tests -q` runs 553, and
`python3 -m unittest tests.integration.test_survival_processes -q` runs 33 more.
Discovery alone silently omits the integration directory; Astra initially
misattributed the count difference to duplicates and corrected that claim.
The ignored `verify_close_r3.py` probe also passed with actual R3 validation and
release, not a mocked release_sequence. Synthetic observations are not live proof.

OBS-3 live-accepted after David explicitly approved restart and one admitted smoke.
Astra fenced R1 admissions, checked zero active leases/claims and actual backend
idle, then restarted only `cointos-mvp-proxy.service` (62160 -> 266838).
The immediate listener probe raced startup and got connection refused; admissions
stayed fenced until a subsequent probe confirmed listening and unauthenticated
401. No inference was attempted during that gap; the service was not restarted twice.
The existing bootstrap executor then ran `local-r4-live-observer-smoke`: exactly
one request returned `OBSERVER_SMOKE_OK`, and normal close reached `run_finished`,
proxy revoked, R3 released, R1 quiescent without any manual reconciliation.
Astra independently checked exact evidence/binding equality, process/group absence
and healthy resources. Proof: `state/backend-observations.jsonl` record
`83135806225749e8a5762cc6291199a4`; restart evidence `observer-activation.jsonl`
and smoke transcript remain in the ignored SDD ledger. No worker remains active.
This accepts conservative release, not autonomous MVP, production model metadata,
precise concurrent release or broader protected service activation.
The exact local packets are retained under ignored /home/david/.CointOS/development/sdd/
2026-09-05-cointos-mvp-index/. The implementation worktree is
/home/david/.worktrees/cointos-mvp-backend-observation; temporary coordinator-owned
nested AGENTS were excluded from worker commits and removed after acceptance.

Never infer physical slot0 from R3 logical sequence1. The required successor must
demonstrate native request/slot/incarnation correlation and independent release
while another slot remains busy. Do not close that follow-up on conservative tests.
