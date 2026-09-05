# 0009: Operator session leases

Status: accepted, 2026-09-05. Chosen architecture: separate owner module (David's
decision between a separate owner, an R1 lease-kind extension, or a design-first
record).

## Context

R8 requires that David's independently launched user-driven agents (for example
`lemonade opencode launch`, not only bare inference clients) hold explicit leases
that ordinary management cannot evict. The plan's rank order is Sole Survivor,
Coin, active user-driven agent session, small health inspectors, large health
inspectors, other roles; an admitted session prevents ordinary eviction, unload
and context resizing, and only Coin may preempt it, and only when Coin's reserved
capacity cannot otherwise be realized. Before this change nothing in the resource
fence knew an operator session existed: the pressure path's dynamic unload could
drop the model a live operator session was using, and no rank existed between
Coin and the health inspectors.

## Decision

A new owner `ecosystem/operator_session.py` owns `state/operator-sessions.json`
(flock, atomic write, the same idiom as R1). A session lease is plain data:
`session_id`, `state`, `request` (session_id, owner_identity, tool, model_id,
request_id), `process` (pid, process_start_ticks) once registered, `acquired_
monotonic`, optional `release_outcome`/`released_monotonic`, optional
`reconciliation`.

Lifecycle, mirroring R1's semantics: `acquire_operator_session` creates a
`starting` session and is idempotent for an identical request; it refuses
admission when the published scheduling snapshot lacks the `user_driven` band.
`register_operator_process` binds the process identity (pid plus start ticks)
and moves the session to `active`; it is idempotent for the same identity on an
active session and refused on any other state. `release_operator_session`
records the outcome (idempotent for the same outcome, an error on a different
one) and moves the session to `release_requested`; a `dead_unreconciled`
session refuses release and can only be reconciled. `observe_operator_sessions`
moves a release-requested session to `quiescent` once its process is observed
stopped, moves an active session observed dead without a release outcome to
`dead_unreconciled`, and changes nothing else. `reconcile_operator_session` is
the only exit from `dead_unreconciled` and requires explicit evidence,
matching 0008: a dead session has no self-healing path.

Protection is model ownership: an active session's `request.model_id` (nullable,
null pins nothing) is owned. `operator_session_owns_model(root, model_name)` is
the query ordinary management must consult.

Ordinary management honours leases in the one place it currently frees capacity:
`resource_control.unload_dynamic_models` skips models owned by active sessions
and records the skip. `enter_pressure` may preempt only when no unprotected
dynamic model remained to unload — that is the concrete form of "Coin's reserved
capacity cannot otherwise be realized". It then calls
`operator_session.preempt_operator_sessions` with coin-reserve evidence
(`kind: "coin_reserve"`, positive `required_bytes`, `incident_id`), the only API
that releases a session without the operator's own release; preempted sessions
record `{"state": "preempted", "returncode": None}`. The emergency (Sole
Survivor) path is unchanged: the survival tier stands above every lease.

Scheduling gains the `user_driven` band strictly between `coin` and
`small_health`; `effective_priority` resolves operator sessions into that band
with ceiling `coin - 1`, and `small_health`'s ceiling drops to
`user_driven - 1`. Scheduling rank still never steals Coin's physical reserve.

`scripts/cointos-opencode` wraps `python3 -m ecosystem.operator_session run`:
acquire, spawn the named tool in its own process group, register the process,
wait, release with the child's outcome, and propagate the exit code. Only a
fresh `starting` session may spawn: a re-run against an active, released, or
dead session is refused before anything is launched, so the operator must
release or reconcile the stale session first.

## Consequences

A live operator session's model survives ordinary pressure; pressure reports the
skip instead of silently breaking the session. Preemption is explicit,
evidence-borne, audited, and reachable only from the coin-reserve path. Operator
sessions rank below Coin and above the inspectors, exactly as the plan orders
them. The wrapper's crash leaves `dead_unreconciled` — visible, bounded, and
cleared only by an operator with evidence, consistent with the rest of the
fence. The scheduling policy schema gains one band; every published snapshot
without it is invalid, so admission fails closed until the policy is republished.
