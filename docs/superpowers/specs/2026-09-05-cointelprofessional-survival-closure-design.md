# Cointelprofessional survival-plane closure

Status: approved in conversation on 2026-09-05; written specification awaiting
David's review.

Provenance: personal orchestration infrastructure. This work does not authorize
professional or customer material to cross into Telegram, prompts, tests, or
personal project records.

Design coordinator: Codex agent `/root`. Review evidence: Codex agents Anscombe
(`/root/plan2_final_review`) and Boyle (`/root/plan2_final_fix`), plus the local
Qwen3.6 35B adversarial audit.

## Objective

Close the six load-bearing defects left by the single permitted Plan 2 final-fix
wave without weakening, bypassing, or rewriting its accepted survival contracts.
The result must be eligible for a new independent review and then for the separate
Plan 5 installed acceptance gate. It is not live-ready merely because repository
tests pass.

The closure comprises:

1. indefinitely idempotent lifecycle failure and retry;
2. crash-safe per-job interruption and a real checkpoint consumer;
3. restoration of prior activity independently of the pause marker;
4. whole-operation systemd deadlines and an exact backend-liveness canary;
5. pre-command incident reporting and timed lifecycle progress;
6. crash-truthful critical-message delivery ambiguity; and
7. an explicit installed cross-UID acceptance gate.

## Binding constraints

- The permanent gateway and guardian remain outside every destructible unit set.
- Root never executes model-generated code. The checkpoint consumer runs as David.
- Existing exact command, peer-credential, schema, unit, action, and path allowlists
  remain strict. No shell text or arbitrary unit/path enters a privileged record.
- Durable intent precedes each external mutation. Recovery may repeat an operation
  only when its postcondition makes repetition safe.
- A retry may remain blocked indefinitely, but it may not crash the guardian,
  silently disappear, admit later lifecycle commands, or create unbounded reports.
- Delivery uncertainty is never converted into permission to replay an external
  Telegram effect.
- Pause state and prior unit activity are independent facts. Neither substitutes
  for the other.
- Timing values come only from the accepted central timing projection.
- Software remains functions over explicit plain data; no classes, inheritance,
  hidden mutable object state, or class-oriented patterns.
- This closure is implemented and reviewed without installing or enabling units.
  Cross-UID and live-system evidence belongs to the explicit installed gate.

## Architecture

The existing pure reducer, production adapter table, immutable effect-attempt
records, semantic unit catalogue, gateway delivery store, and central timing owner
remain the canonical route. The closure adds no parallel controller.

Four narrow contracts complete the route:

```text
lifecycle retry owner
    durable pending effect -> attempt/postcondition -> blocked fact -> bounded report

checkpoint request
    guardian intent -> David-owned consumer -> per-job handoff fact -> guardian snapshot

incident destination
    installed authorized chat identity -> root critical intent -> gateway delivery fact

critical delivery
    immutable source -> private delivery state -> Telegram -> terminal/unknown fact
```

The guardian remains the sole lifecycle reducer and privileged executor. A small
unprivileged checkpoint consumer is activation-independent infrastructure: it reads
only fixed-schema checkpoint requests, asks the existing control/job layer to reach
a durable boundary, and writes one result per requested job. It cannot issue
systemd operations or authenticate to the guardian command socket.

## Lifecycle failure and recovery

### Stable blocked state

An effect failure produces one durable blocked fact keyed by request ID and effect
ID. The blocked report is a separate optional effect with its own deterministic key.
Recovery never assumes that a pending blocked-report effect exists. It derives the
next action from explicit state:

- if the original effect postcondition is now satisfied, record success and reduce;
- otherwise perform or retry the idempotent effect under its accepted policy;
- if it fails, update the existing blocked fact's observation time and bounded
  attempt count, and ensure at most one report per configured progress interval;
- return a valid blocked result rather than raising, even after any number of
  identical failures.

The oldest incomplete lifecycle remains the sole active lifecycle. Later commands
are durably accepted and serialized, not interleaved or lost.

### Crash-safe job interruption

The aggregate `interrupted_jobs` snapshot is replaced as the authority by one
atomic transition record per job and request. Before changing a job from `running`,
the guardian publishes an interruption intent naming the immutable job identity and
request. After the job record reaches `interrupted`, the guardian publishes the
completed transition. Recovery reconstructs the aggregate view exclusively from
these per-job facts and verified job records. Death before intent changes nothing;
death after intent resumes inspection; death after mutation but before completion
recognizes the job postcondition and completes without losing membership.

The runtime snapshot may cache the derived set, but it is not its authority.

## Checkpoint ownership

`RESTART` publishes a fixed-schema checkpoint request containing the lifecycle
request ID, deadline, and exact job identities observed active. The unprivileged
checkpoint consumer watches the request directory independently of ordinary job
admission. For each job it invokes the existing control-worker checkpoint/handoff
interface, never arbitrary job text, and emits exactly one atomic result:

- `checkpointed`, with the durable handoff/session identity;
- `already_terminal`;
- `unsupported`, explicitly recoverable only by interruption; or
- `deadline_expired`.

The guardian waits until all requested job results are terminal or the single
overall checkpoint deadline expires. It verifies every claimed handoff exists
before marking that job preservable. All others enter the crash-safe interruption
route. Elapsed sleep alone can never constitute checkpoint success.

The consumer is installed as protected control infrastructure but runs as David.
`RESET` does not wait for checkpointing and remains the fastest safe hard cycle.

## Pause and activity restoration

Admission closure snapshots these independent values:

- the explicit global pause marker;
- active activation sources;
- active ordinary services;
- active control services; and
- active inference prerequisites.

After reconciliation and verification, prior active services are restored in
dependency order regardless of the pause marker. The prior pause marker then
determines whether new ordinary work admission and preserved-job resumption reopen.
A previously paused system therefore returns to its previously running supporting
services while remaining paused. A previously inactive unit is never started merely
because it appears in the catalogue.

## Whole-operation deadlines and health truth

Each semantic systemd action owns one absolute monotonic deadline. Every subprocess
call and postcondition probe receives only its remaining duration. Unit actions use
`systemctl --no-block`, then observe manager state and cgroup state until the shared
deadline. Timeout does not imply cancellation: the guardian issues the fixed
allowlisted cancellation/stop/kill action appropriate to the stage and verifies a
safe terminal postcondition before recording failure. If safe state cannot be
proved, the lifecycle remains blocked and admission stays closed.

The model canary requires all of:

- the expected model identity;
- `loaded == true`;
- the accepted ready/in-use service status;
- `backend_alive == true`; and
- a successful bounded inference canary.

Missing, false, malformed, or non-finite observations fail closed without taking
down the gateway.

## Incident destination and progress reporting

The authorized Telegram destination is installed survival configuration, separate
from lifecycle history. It contains the exact numeric chat/user identity already
accepted for gateway authorization, is root-owned, schema-validated, and readable
only where needed. The gateway does not accept a destination supplied by an
ordinary spool record or model.

Gateway data-health incidents and invalid timing-policy incidents can therefore
create a root critical intent before the first lifecycle command. Deduplication keys
derive from incident kind and stable incident identity, not the latest command.

While a lifecycle remains incomplete, the guardian uses
`lifecycle.progress_update_period_seconds` from the accepted timing projection.
It publishes a progress report only when the phase, blocker, or configured interval
requires one. Reports contain fixed operational facts, never arbitrary job content.
Report failure cannot block recovery; delivery state remains independently visible.

## Critical-message delivery truth

Guardian critical-message source records remain immutable. Gateway-owned delivery
records use this state machine:

```text
absent -> ready -> sending -> delivered
                    |          
                    +-> delivery_unknown
```

`absent` may create `ready` only when no delivery attempt has ever existed. Once an
attempt identity exists, missing, malformed, quarantined, or interrupted delivery
state reconstructs as `delivery_unknown`, never `ready`. A small immutable attempt
tombstone or source-side `attempt_observed` fact supplies that history without
granting the gateway mutation authority over guardian content.

`delivery_unknown` is terminal for automatic sending. It produces a deduplicated
local health incident for later operator adjudication but never an automatic replay.

## Verification

Repository closure tests must prove:

- at least three consecutive failures of the same lifecycle effect return a stable
  blocked result without guardian death, duplicate report, or later-command entry;
- death at every per-job intent/mutation/completion cut reconstructs every affected
  job and preserves verified handoff membership;
- the real checkpoint consumer handles checkpointed, terminal, unsupported, and
  expired jobs and the guardian never treats sleeping as success;
- paused-but-active and unpaused combinations restore exact prior unit activity and
  exact prior admission state;
- one absolute deadline bounds action plus all probes, and an unfinished systemd
  manager job cannot be recorded as safely failed;
- `backend_alive` false/missing/malformed prevents admission reopening;
- gateway-data and invalid-policy incidents report before any lifecycle command;
- long-running/blocked lifecycle progress obeys the live configurable period;
- corrupt, missing-after-attempt, and quarantined delivery facts become
  `delivery_unknown` and never send again; and
- the complete production constructor drives both commands with only literal
  machine fingertips substituted.

The installed Plan 5 gate must create/use the actual service identities and prove:

- each intended cross-UID read/write succeeds;
- forbidden rename, injection, source mutation, delivery-state mutation, socket
  authentication, and private-state reads fail;
- process identity/cgroup turnover, pause restoration, checkpoint handoff, Telegram
  acknowledgement/progress/completion, and gateway continuity hold under real
  services; and
- any failed assertion refuses enablement or rolls back to the known-live gateway.

## Failure policy and stopping condition

No repository-green claim closes the installed evidence gate. No installed test may
trade away the currently live Cointelprofessional path. If live acceptance cannot
preserve or atomically restore that path, installation stops and reports the exact
blocker through the existing gateway.

This closure is complete only when its independent whole-plan review has no open
Critical or Important implementation finding. Deployment is complete only after
the separate installed gate passes under the real identities and services.
