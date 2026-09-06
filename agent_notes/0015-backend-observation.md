# Backend observation bring-up — Astra, 2026-09-06

David approved temporary whole-backend-idle reconciliation, conditional on a
visible path to precise per-request/physical-slot observation. Decision0012 and
the 2026-09-06 backend-observation plan are authoritative; status links both.
R4-PRECISE is required follow-up, NOT an added conservative MVP acceptance gate.

OBS-1 is integrated: local `ca9fcda`/`0733f9a` -> `b17c8fc`/`4776e15`.
The proxy owner now has bounded loopback metadata GET, PID/start/boot identity,
backend snapshot, and before/after exhaustive idle observation functions.
Only sanitized identity/slot-id/processing facts are returned, never prompts.
This is a read-only adapter; it is not yet wired to automatic runner release.
Astra independently passed 43 focused tests and reviewed both diffs. The initial
worker needed a correction for dead process state X and function-based assertions;
the correction demonstrated the X regression red before going green.

Remaining: OBS-2A records the actual backend identity before forwarding and
retains uncertainty for the entire credential; OBS-2B performs fresh close-time
observation/persistence and preserves reconciled_absent through R3. OBS-3 is
combined verification and controlled live activation, not implied by commits.
The two exact local packets are retained under ignored .superpowers/sdd/
2026-09-05-cointos-mvp-index/. The implementation worktree is
/home/david/.worktrees/cointos-mvp-backend-observation; nested AGENTS are temporary
coordinator-owned steering, excluded from worker commits.

Never infer physical slot0 from R3 logical sequence1. The required successor must
demonstrate native request/slot/incarnation correlation and independent release
while another slot remains busy. Do not close that follow-up on conservative tests.
