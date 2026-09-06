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
need no executor credential. R8-G1 accepted: local 316fb41/9b92f18 -> 538fb54/afe41b3.
config_fd=None support (record sentinel -1) preserves existing FD behavior and all
gate/cleanup contracts. Astra passed 40 initial focused/executor tests, then four
corrected gate tests. Review rejected two new TestCase instances and a marker-
absence assertion made after temp-directory deletion; local correction uses plain
functions and asserts absence while the directory still exists. No dummy credential
or parallel gate implementation. Tiny test children only, no live operator changes.

R8-G2 combined packet local-r8-gated-launch REJECTED: exited zero/run_finished
but final reason length at 32000 output tokens, no patch or tests. Runtime close
worked; semantic deliverable did not. Do not mark it completed. Keep output cap
32000 (OpenCode's actual limit); split tasks rather than inflate it.
R8-G2A running: local-r8-register-gate, only run_command registration-before-exec,
verified setup cleanup and attached failure attestation; two tiny real-child tests.
R8-G2B next: durable sanitized setup-failure reporting, separate packet after G2A.
Lease state stays conservatively unchanged on failure; no fabricated release,
quiescence or dead-session self-healing. Post-release wait/interruption semantics
unchanged. Only operator_session.py and new tests/test_operator_launch.py.
Do not silently change detached-session interruption semantics, preemption policy,
dead-session reconciliation authority or add an autonomous repair loop.

Packets/logs remain in ignored .superpowers/sdd/2026-09-05-cointos-mvp-index/.
Read-only work used the clean metadata worktree. Writer worktree now exists at
/home/david/.worktrees/cointos-mvp-operator-launch, branch fix/mvp-operator-launch,
base 05723b0. Current worker base includes accepted R8-G1 commits above.
