# Operator launch review — Astra, 2026-09-06

Next R8 bring-up concern after production metadata live acceptance. Authority:
existing R8 implementation plan and decisions 0008/0009; separate operator owner,
no self-healing dead_unreconciled sessions, no new deployment/preemption authority.

Read-only local-r8-launch-review identifies a real run_command seam: Popen executes
the command before kernel identity and operator registration. Identity/registration
exceptions do not clean up the child. Popen failure leaves starting; ordinary
completion requests release and later observed absence owns quiescence.
Astra checked source: executor.process_identity returns dict or raises, NEVER None.
Reject the worker's hypothetical None/TypeError branch as an established blocker;
an unreaped rapid-exit child normally remains observable as a zombie as well.
Existing two CLI tests run actual small children but do not cover registration failure.

The read-only local-r8-gated-map confirmed executor gated_child_launch/release /
cleanup contracts. Parent owns a blocked gate; requested exec starts only on release.
Cleanup reports reaped only after leader reap and observed process-group absence.
Existing credential-bearing gate requires an FD, while arbitrary operator tools
need no executor credential. R8-G1 running: local-r8-gate-optional-fd adds explicit
config_fd=None support (record sentinel -1), preserving existing FD behavior and
all gate/cleanup contracts. New plain-function tests use tiny marker-writing
children, no model inference. No dummy credential or parallel gate implementation.
After acceptance, R8-G2 adapts run_command to register before opening that gate;
its precise exception/state contract must be fixed before dispatch.
Do not silently change detached-session interruption semantics, preemption policy,
dead-session reconciliation authority or add an autonomous repair loop.

Packets/logs remain in ignored .superpowers/sdd/2026-09-05-cointos-mvp-index/.
Read-only work used the clean metadata worktree. Writer worktree now exists at
/home/david/.worktrees/cointos-mvp-operator-launch, branch fix/mvp-operator-launch,
base 05723b0. Only executor.py and new tests/test_operator_gate.py in R8-G1.
