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

Next packet local-r8-gated-map is read-only: exact executor gated_child_launch /
release / cleanup contracts and reusable regression fixtures. Prefer adapting the
existing gate so requested code cannot execute before lease registration, preserving
owner-attested failure evidence, rather than another raw Popen cleanup mechanism.
Do not silently change detached-session interruption semantics, preemption policy,
dead-session reconciliation authority or add an autonomous repair loop.

Packets/logs remain in ignored .superpowers/sdd/2026-09-05-cointos-mvp-index/.
Read-only work uses the clean metadata worktree; create a new isolated writer
worktree for any operator-session implementation after the bounded design is fixed.
