# Independent MVP design review

Flint (Codex) reviewed the 2026-09-05 MVP design plus the health, autonomy,
and approval/release plans on 2026-09-05. Scope excluded Flint's contact plan,
runtime tests, services, network/model use, and source changes. The pending swarm
index and health-inspector integration were treated as intentional coordinator work.

## Credible strengths

- The spec states all three binding invariants independently: Coin availability,
  no OOM, and seamless continuation across dynamic—including smaller—context
  allocations. Health H3 inherits R6; autonomy A5 explicitly exercises a smaller
  continuation context; approval keeps the invariants active during release work.
- The exact requested rank appears in the spec: Sole Survivor > Coin > small health
  inspector > large health inspector > other roles. It explicitly distinguishes
  rank from Coin's exclusive physical inference capacity and rejects label spoofing.
- Early contact is not gated on H1-H4, A1-A5, P1-P4, or deferred adversarial review.
  The plans are substantial but form the complete MVP after the early-online slice,
  rather than resurrecting the old exhaustive survival-closure prerequisite.
- Autonomy A1/A3 makes roles configuration/Markdown data after the loader change,
  requires a temporary role to work without source edits, and includes Documenter
  with a remit distinct from Janitor and Speculator.
- Approval P2 parses exact authenticated literal commands before inference; P3
  requires approval/base/digest validation before fixed activation; P4 waits for
  David's real approval. Silence, prose, expiry, replay, or delivery do not approve.

## Actionable findings

1. **Independent verification does not bind declared release targets.**
   `2026-09-05-cointos-mvp-approval-release.md`, P1 `candidate_verified` example,
   compares candidate ID, tree digest, and source revision only. Yet its manifest
   also carries `base_release_digest`, `target_class`, `target_units`, and checks,
   and the spec says the verifier binds declared targets. Those policy fields could
   change after the displayed verdict without invalidating `candidate_verified`.
   Smallest correction: include base-release digest, target class, canonical target
   list, changed-path list, and check-evidence digest in the verifier's independently
   computed `verification_digest`, and compare that exact digest in P1 tests.

2. **Approval acceptance cannot revalidate every fact it claims to bind.**
   Same plan, P2 interface
   `accept_approval(request, accepted_update, current_digest, now)` supplies only
   one ambiguous digest, while the text/tests require current candidate tree,
   expected active base, and targets. P3 receives `active_digest` only later.
   Smallest correction: replace `current_digest` with an observed record containing
   `candidate_digest`, `active_base_digest`, `target_class`, and canonical
   `target_units`; reject any mismatch inside `accept_approval` and repeat the same
   comparison in `new_activation` before durable activation acceptance.

3. **Incident repair completion has no shared event contract.**
   `2026-09-05-cointos-mvp-health.md`, H2 moves `repair_claimed` directly to
   `verifying`, but H3's runner produces `progress|partial|candidate_ready|contained|
   failed|deadline|backend_lost`; no function maps those observations to H2 events.
   Claiming a run is not evidence it completed, so the shown reducer can request an
   independent probe before the repair outcome exists. Smallest correction: keep
   `repair_claimed` in `repairing`; define one exact
   `ingest_repair_observation(incident, run, observation)` mapping, with only
   `contained|candidate_ready` (as policy permits) producing `repair_finished` and
   then `request_probe`; map terminal failures to bounded escalation.

4. **The “ordinary scheduler dead” repair path lacks a production handshake.**
   Health H3 promises a guardian-owned launch intent, a David-owned template unit,
   direct reporting, and survival when the ordinary scheduler is killed, but its
   public surface ends at user-side `run_repair(...)`. It does not name the root
   launch function, exact instance identity/path, result record, or reconciliation
   after guardian/runner death. The acceptance test cannot prove independence from
   the ordinary scheduler without these facts. Smallest correction: specify
   `start_repair_unit(run_id, systemctl) -> dict`, an exact root-written request and
   David-written result schema/path keyed by `incident_id/run_id`, and
   `reconcile_repair_run(...)` using unit/process postconditions; add the killed-
   scheduler test through these injected production fingertips.

5. **Contribution artifact validation lacks the data and authority it requires.**
   `2026-09-05-cointos-mvp-autonomy.md`, A4 exposes
   `validate_contribution(result, task_contract)` while requiring actual artifact
   existence/digest checks. `result.artifact_paths` contains strings only and the
   validator receives no candidate root or observed digests. Smallest correction:
   keep `validate_outcome(raw)` schema-only, then define
   `observe_contribution(candidate_root, result, task_contract) -> dict` returning
   canonical `{path, digest}` artifacts after containment/existence checks; the
   verifier and `apply_contribution` consume that observed record.

6. **Child enqueue in A4 is not type-consistent with A1.**
   A1 extends `cli.enqueue_task(..., task_contract=...)`, but A4 pseudocode calls
   `enqueue(child, idempotency_key=...)` without naming whether `child` is a full
   enqueue request or only a task contract. This makes atomic budget reservation and
   replay hard to implement consistently. Smallest correction: define
   `enqueue_child(parent_job, child_contract, idempotency_key) -> str` at A1's sole
   enqueue owner; A4 calls only that function after `narrow_contract`, and its test
   asserts one budget debit and one job across crash/replay.

## Review conclusion

Astra resolution, 2026-09-05: all six interface findings were incorporated into
the proposal. P1 now verifies a full manifest binding including targets/checks;
P2 consumes an independently observed binding/base/target/boot record; H3 maps
actual repair outcomes to H2 events and names installed request/result/launch/
reconciliation functions; A4 observes real contained artifacts; A1 owns atomic
`enqueue_child`. Candidate-ready remains awaiting approval, never repaired. This
records design correction, not executed tests or deployed behavior. The index and
H5 inspector integration are now present; C5 depends on A1's shared contract but
not on spontaneous scheduling or the complete A5 cycle.

No contradiction was found in the governing invariants, priority/capacity split,
data-driven role extension, Documenter remit, early-online sequencing, or the need
for exact Coin approval. The six gaps above are locally repairable interface
omissions; none requires another subsystem, database, daemon, or exhaustive gate.
