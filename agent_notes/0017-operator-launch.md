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
R8-G2A review history: local-r8-register-gate e7e83de, only run_command registration-before-exec,
verified setup cleanup and attached failure attestation; two tiny real-child tests.
Independent 23 tests pass, but injected cleanup exception raises UnboundLocalError:
Python deletes the except target cleanup_error, losing original registration error.
Do not accept e7e83de alone. local-r8-cleanup-error adds the missing regression and
minimal binding fix before integration; runtime success was not semantic acceptance.
Correction c4eeca3 accepted with e7e83de as 6555a10/7314204: Astra independently
passed 24 tests; exact original exception and cleanup cause survive in the added
regression. R8-G2A is now accepted. R8-G2B: local-r8-launch-journal,
durable sanitized setup-failure reporting, separate packet after G2A.
Lease state stays conservatively unchanged on failure; no fabricated release,
quiescence or dead-session self-healing. Post-release wait/interruption semantics
unchanged. Only operator_session.py and new tests/test_operator_launch.py.
Do not silently change detached-session interruption semantics, preemption policy,
dead-session reconciliation authority or add an autonomous repair loop.

Packets/logs remain in ignored /home/david/.CointOS/development/sdd/2026-09-05-cointos-mvp-index/.
Read-only work used the clean metadata worktree. Writer worktree now exists at
/home/david/.worktrees/cointos-mvp-operator-launch, branch fix/mvp-operator-launch,
base 05723b0. Current worker base includes accepted R8-G1 commits above.

## Accepted launch checkpoint — Astra, 2026-09-07

R8-G2B local 016a051/3f2c030 -> f6994d3/faae7ad. Initial 26 tests passed,
but the requested field projection was missing; local-r8-journal-fields supplied
it and a polluted-attestation table regression. Events retain only allowed facts,
unknown spawn/cleanup remains unknown, cleanup precedes persistence, original
errors survive, and failed persistence is chained. No automatic lease closure.
Astra independently passed all 622 tests (589 discovery + 33 separately discovered
integration), 26 focused tests, and diff check. Additional tiny real-child probe:
gate-release failure after registration never ran the marker command, reaped the
group, persisted proof, and retained active (not falsely released) lease state.
All local packet processes closed normally through conservative backend evidence.
Removed only two temporary coordinator-owned AGENTS steering files; committed
source, tests and isolated writer branch remain preserved.

R8 launch repair is accepted; full R8 ordinary tool inference admission, detached
session semantics and explicit failed-launch reconciliation remain separate
requirements, not claimed complete. Existing post-release wait/release and no-dead-
self-healing boundary unchanged. R4-PRECISE remains open as tracked in status.
Next priority is approved C1 canonical contact, initially read-only local mapping
in /home/david/.worktrees/cointos-mvp-contact. Keep canonical replacement isolated
until its offline callers/cutover are ready; do not break live legacy consumers
by cherry-picking a half-converted schema into the runtime checkout.
