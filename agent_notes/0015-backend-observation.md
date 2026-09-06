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

Remaining: OBS-3 controlled live acceptance. The existing transient proxy still
runs its earlier imported code. Ask David to approve restarting that proxy with
reviewed bytes and one bounded admitted smoke; preserve a fresh idle/admission
fence and rollback path. Do not enable new services or activate broader changes.
Both local workers exited and were independently reconciled; no worker is active.
The exact local packets are retained under ignored .superpowers/sdd/
2026-09-05-cointos-mvp-index/. The implementation worktree is
/home/david/.worktrees/cointos-mvp-backend-observation; temporary coordinator-owned
nested AGENTS were excluded from worker commits and removed after acceptance.

Never infer physical slot0 from R3 logical sequence1. The required successor must
demonstrate native request/slot/incarnation correlation and independent release
while another slot remains busy. Do not close that follow-up on conservative tests.
