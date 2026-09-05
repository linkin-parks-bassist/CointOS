# 0008: Owner-attested spawn failures

Status: accepted, 2026-09-05.

## Context

When a gated child launch failed before the process was registered with workload
control, the executor released the R1 lease and parked the job in
`reconciliation_required`, but the lease stayed in an unresolved state: any later
observation without a registered process forced the lease back to `starting`, so a
released lease could never quiesce, blocked new acquisitions and smoke, and the only
exit was manual record surgery. The cleanup result of a post-spawn crash (identity
check failure after Popen) was discarded, so the executor could not distinguish
"conclusively never spawned" from "spawned and reaped" from "spawned and unverified".

## Decision

`gated_child_launch` attaches a `launch_failure` attestation to every raised error:
`{"spawned": False}` when no process exists, or `{"spawned": True, "pid",
"start_ticks", "pgid", "cleanup"}` after consuming the bounded `gated_child_cleanup`
outcome when a process did exist.

`launch_runner_round` journals `runner_spawn_failure` (phase, error, spawned,
cleanup_state) on every pre-R3 failure. A spawn whose cleanup is not verified reaped
leaves the job and its lease in reconciliation. A verified terminal outcome releases
the lease and records one attested observation: `never_spawned: true` when no process
was created, or `reaped_spawn` with the reaped process identity and returncode when
the process was created but never registered. Registered-process failures keep the
existing identity-matched observation path.

Workload control strictly validates attested observations and applies them as
terminal evidence for local leases: an attestation on a processless lease moves it to
`observed_stopped`, or to `quiescent` once the release outcome is recorded; an
attestation contradicting a registered process marks the lease `dead_unreconciled`.
An unattested observation of a processless lease changes nothing. Attested leases do
not owe checkpoint evidence, because nothing was running to checkpoint.

## Consequences

A failed spawn returns the job to `ready` with a truthful deferred reason instead of
a poisoned lease, and drain/smoke can proceed without manual intervention. The two
crash classes the executor cannot distinguish are no longer conflated: unverified
cleanup is quarantined for reconciliation, verified outcomes are attested with the
exact reaped identity. A lease marked `dead_unreconciled` has no self-healing path;
that is deliberate, and clearing it is a separate operator concern.
