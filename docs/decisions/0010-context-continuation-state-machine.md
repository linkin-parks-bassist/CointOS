# 0010: Context continuation is an explicit state machine

Status: accepted, 2026-09-06. Chosen architecture: a separate pure module
(`ecosystem/continuation.py`) owning the context-run state and identity laws,
with the executor reduced to the durable backend adapter that observes,
attests, and persists.

## Context

Before R6 the executor carried context rollover as two inline flags —
`handoff_pending` and `fresh_context_after_handoff` — mutated in several
places inside `execute_next`. Identity had no explicit survival law: nothing
stated that `job_id` and `agent_generation` must survive a context or model
change, a process restart, or a resource pause, and nothing said what
increments what. Rollover detection was OpenCode-specific and ran only in the
preemption poll: a run that finished cleanly past the 75 percent threshold
would have been relaunched with `--session` into a near-full context, letting
the backend truncate history. There was no state for a context that exists but
has no lease, and a missing semantic handoff was handled by one degraded
artifact path with no place in any state machine.

## Decision

`ecosystem/continuation.py` is a pure module over plain data — no I/O, no
classes. The context-run state lives on the job record as `context_state`
and `context_generation`. The states are `running`, `handoff_requested`,
`handoff_durable`, `continuation_ready`, and `paused_for_resources`; the
machine advances only through these functions:

- `observe_context_usage(adapter_event, lease)` normalizes one backend usage
  event against the lease's `context_tokens`. Overflow (fraction above 1.0)
  is a fact, not an error.
- `context_transition(job, usage, rollover_fraction)` moves `running` to
  `handoff_requested` at the rollover fraction. The fraction is validated to
  be strictly between 0 and 1: rollover must precede the backend limit. A
  requested context stays requested at any overflow — context overflow is
  never terminal.
- `attest_handoff(job, handoff)` moves to `handoff_durable` when a durable
  semantic handoff (non-empty summary, integer token count) exists. Double
  attestation fails explicitly.
- `handoff_budget(destination_lease)` validates that the destination's
  prompt/handoff/tool/output reserves all fit inside its context; a
  destination whose partition exceeds its context is infeasible and is
  rejected, never trimmed.
- `prepare_continuation(job, handoff, artifacts, destination_lease)` builds
  the next-context record against an admitted destination: `context_generation`
  advances by one, `context_state` becomes `continuation_ready`, the
  destination budget is reserved into the record, and evidence is carried by
  reference. A null handoff remains visibly continuable
  (`handoff_missing: true`), never a failure; an over-budget handoff fails
  explicitly so the writer resizes it. A double continuation fails.
- `new_attempt(job)` is the only thing that increments `agent_generation`;
  it resets `context_generation` to 1 and the state to `running`.

The identity law is enforced by construction: only `prepare_continuation`
touches `context_generation`, only `new_attempt` touches
`agent_generation`, and transition fragments never carry either field.

The executor keeps the durable OpenCode session/event parsing
(`opencode_context_usage`) as its adapter role and otherwise only persists
what the module returns:

- Rollover is detected in the preemption poll via the module and additionally
  at clean run end: a run finishing past the threshold rolls over instead of
  resuming a full session.
- On a `handoff_requested` run finishing, the executor reads the handoff
  artifact, attests it (or writes the explicit degraded artifact when the
  agent emitted none), archives the old context log by reference, pops the
  session, and returns the job to the scheduler.
- The continuation launches at routing time, when the destination is known:
  the freshly admitted lease becomes the `destination_lease`, so a model
  change between handoff and relaunch is honoured. The rollover prompt is
  written there (with a degraded note when the handoff was missing) rather
  than pre-prepared.
- A deferred job with a live session and a plain running context enters
  `paused_for_resources`; a continuation-in-flight state is never clobbered
  by deferral. Launch consumes `continuation_ready` and
  `paused_for_resources` back to `running`, and initializes
  `context_generation` to 1 on first launch.

This is a clean break: `handoff_pending`, `fresh_context_after_handoff`, and
`context_rollover_usage` are deleted.

## Consequences

The job record gains `context_state` (plus the continuation record fields on
rollover); a record without them is a record that has never rolled over, so
`running`/generation 1 are the true facts for it, not a fallback. A handoff
that exceeds the configured `handoff_tokens` reserve is rejected until
resized; the executor estimates its token count conservatively (roughly one
token per three characters) at the adapter boundary. Clean finishes past the
threshold now roll over — a behavior gap that previously existed only on the
preemption path. `new_attempt` is module-level: wiring a control-plane
re-attempt of a checkpointed job (R5) through it is a separate follow-up.
The `_run_preemptibly` outcome contract (`context_rollover`,
`context_usage`, the `total/limit` reason) is unchanged.
