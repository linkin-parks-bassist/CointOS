# Cointelprofessional survival control and subsystem health

Status: approved in conversation on 2026-09-04; written specification awaiting
David's review.

Provenance: personal orchestration infrastructure. It may coordinate professional
work, but this design does not authorize copying professional or customer material
into its records, prompts, tests, or external services.

Design coordinator: Codex agent `/root`. Evidence contributors: Codex agents
`ingress_audit`, `watchdog_audit`, and `lifecycle_audit`.

## Objective

Cointelprofessional is the permanent remote control surface for the local agent
ecosystem. Failure of that control surface is a survival incident on the same level
as an out-of-memory event. Ordinary agent work, model throughput, notification
polish, and graceful shutdown all rank below restoring contact.

The implementation must provide:

- exact `RESTART` and `RESET` commands which remain available while the agent and
  inference planes are broken;
- a highest-priority small-model path which replies promptly and decides whether an
  ordinary message needs a separately dispatched job;
- permanent, non-agentic supervision of per-subsystem health leases;
- bounded initial repair by a smaller model, with direct reporting and manual or
  automatic escalation to the strongest safely runnable model;
- occasional deeper monitor agents which discover blind spots in heartbeat
  contracts;
- a central, quickly readable subsystem catalogue and live-status projection;
- centrally configurable operational periods in `config/time.cfg`; and
- live, end-to-end verification under process, model, and context failures.

No claim of literal universal availability is possible on one home machine using an
external Telegram service. A power, kernel, hardware, network, ISP, or Telegram
outage can still break reachability. Within the machine boundary, however, no
agentic component, inference server, ordinary OOM event, lifecycle command, or
malformed job may be able to keep the gateway down.

## Binding invariants

1. The Telegram gateway and hard guardian form a survival plane. Neither
   `RESTART`, `RESET`, resource recovery, nor ordinary agents may stop them.
2. The survival plane has no model dependency. It can authenticate commands,
   durably accept messages, issue honest degraded responses, report incidents, and
   recover the destructible plane while Lemonade is absent.
3. Literal commands are recognized before inference. Only the exact,
   case-sensitive message bodies `RESTART` and `RESET` are commands. Surrounding
   whitespace, prefixes, suffixes, and different case make a message ordinary text.
4. Command execution is authenticated, typed, durable, idempotent by Telegram update
   identifier, and incapable of accepting shell text, service names, or arbitrary
   arguments.
5. An ordinary message is handled first by the small control model. One
   schema-valid result supplies both the immediate reply and a `respond` or
   `dispatch` decision. Only `dispatch` can create work.
6. Small-model contact work has mechanically reserved inference capacity and
   maximum scheduler priority. A declaration in a prompt or configuration file is
   not enforcement.
7. Every implemented subsystem owns a health contract and heartbeat lease. A lease
   is renewed only after every currently required check passes.
8. A stale heartbeat first starts a bounded smaller-model repair. Successful repair
   plus a fresh independent probe closes the incident without large-model
   escalation.
9. Repair agents can report progress and manually escalate. Silence, process death,
   invalid completion, context exhaustion, or loss of progress automatically
   escalates and preserves the available findings.
10. Cointelprofessional reports incident opening, bounded repair, meaningful
    progress, escalation, recovery, and operator-required blockers. These reports
    bypass the ordinary model presentation and notifier paths.
11. Roles are optional advisory context. Missing and unknown roles never reject an
    otherwise valid job. Emergency execution does not depend on role-file lookup.
12. Runtime records remain append-only or atomically replaced according to their
    existing ownership. Health projections never become a competing source of job
    truth.

## Why the current system became unreliable

The main failure was not lack of stated priority. The priority was repeatedly
written into prose and configuration without being converted into enforced
boundaries and composition tests.

- Current ingress has no literal-command parser. Every nonblank message, including
  `RESTART`, enters a synchronous model call.
- The gateway processes updates serially. One update can spend up to twenty seconds
  in inference and forty seconds in Telegram delivery before a later urgent update
  is examined.
- Fast, deep-control, routing, naming, and presentation requests share two model
  sequences. `reserved_slots = 1` is present in configuration but unused by any
  enforcing component.
- Telegram agent jobs receive high executor priority only after a deep model turn
  decides to enqueue them. That does not prioritize receipt, initial response, or
  the dispatch decision.
- The watchdog is a three-minute advisory job generator. It checks only a fraction
  of the control plane and queues the resulting Steward at the scheduler's lowest
  priority. One pending Steward suppresses later watchdog work, including unrelated
  failures.
- On 2026-09-04 a single memory-PSI sample crossed an aggressive threshold and
  entered resource emergency despite zero OOM kills and ample memory/GTT headroom.
  The transition committed the emergency latch before preparing its recovery job.
- Recovery then passed `sole_survivor` into a validator which rejects underscores,
  although `roles/sole_survivor.md` is checked in. The transition failed after
  ordinary dispatch had been closed, leaving no permitted survivor job.
- The guard considered the pinned model live only when its status was exactly
  `ready`. While the model was correctly `in_use`, the guard interpreted it as
  absent, repeatedly reloaded it, and restarted Telegram, control, and notification
  services every second. Systemd eventually applied its start-rate limit.
- Exceptions were logged while the guard continued looping through the same
  partially committed state. No incident message reached David.
- All 57 unit tests passed during this live failure. The resource tests mocked the
  emergency transition and therefore never composed role loading, model busy state,
  partial persistence, service restart, and scheduler admission.

The repository accumulated many individually reasonable changes faster than their
cross-component invariants were tested. Documentation described intended state as
implemented before live Telegram and failure-injection gates had passed. This
design replaces those aspirational labels with a small survival boundary, explicit
state machines, and process-level acceptance tests.

## Architecture

The system is divided into a permanent survival plane and a destructible agent
plane.

```text
Telegram API
    |
    v
permanent gateway  <---- durable critical outbox ---- permanent guardian
    |       |                                      /       |       \
 commands  | ordinary message                    /        |        \
    |       v                                    /         |         \
    |   durable ingress spool                   /          |          \
    |       |                                  /           |           \
    +----> typed lifecycle socket             /     health leases    incidents
            |                                 /            |
            v                                v             v
       permanent guardian ---- controls ---- destructible agent plane
                                        (Lemonade, models, controller,
                                         scheduler, executor, notifier,
                                         monitors, ordinary agents)
```

### Permanent gateway

The gateway is a minimal root-installed system service running as a dedicated,
unprivileged `cointelprofessional` system user. Its installed code is root-owned and
does not execute directly from the mutable repository. Telegram credentials are
provided through a protected systemd credential file and never copied into Git,
logs, prompts, or command records.

The gateway owns only:

- Telegram long polling and allowed-user authentication;
- exact literal-command recognition;
- atomic writes to the durable ingress spool;
- delivery of the survival plane's typed critical messages;
- an honest deterministic degraded response when small-model service is currently
  unavailable; and
- a process heartbeat consumed by the guardian.

It does not load models, interpret natural-language intent, run agents, edit the
repository, or accept arbitrary privileged instructions.

The service uses `Restart=always`, a subsecond restart delay, no systemd start-rate
limit, strict filesystem and syscall restrictions, high resource protection, and
systemd's process watchdog. The guardian also checks its application heartbeat and
requests a restart if the process is alive but not polling. An unconsumed inbound
update remains in the external spool across any gateway restart.

### Permanent guardian

The guardian is a root-owned, non-agentic system service in the same protected
survival slice. It owns:

- the two-command lifecycle state machine;
- the fixed allowlist of destructible units and cgroups;
- start, stop, kill, load, and verification operations needed to recover those
  units;
- per-subsystem lease deadlines;
- incident state reduction and deduplication;
- dispatch and supervision of bounded repair runners;
- critical Telegram updates through the gateway spool; and
- recovery of incomplete lifecycle commands or incidents after its own restart.

A root-owned Unix socket is the only lifecycle request boundary. The guardian checks
the peer credentials and accepts only the dedicated gateway user. Its protocol is a
versioned record containing a command enum, Telegram update identity, authenticated
user identity, and timestamps. There is no field for shell, unit, path, model, or
argument text.

The ordinary executor runs as David and cannot authenticate as the gateway user.
This avoids a sudo wrapper which every same-UID agent could invoke.

The guardian never executes model-generated code or a model process as root. Repair
runners execute as David in a restricted transient unit. They can inspect their
bounded evidence and submit typed requests to the guardian, which independently
validates and performs only installed, allowlisted lifecycle operations.

### Durable survival spools

Survival records live under `/var/lib/cointelprofessional/`, outside the mutable
repository and ordinary restart set. Separate directories hold inbound updates,
critical outbound messages, lifecycle requests, accepted timing policy, and minimal
incident recovery records. Ownership and group permissions allow only the required
one-way writes. Writes are temporary-file, `fsync`, rename operations.

Detailed agent records remain under the repository's ignored `state/` and
`logs/runs/`. Survival records contain the least information needed to restore
contact and do not duplicate conversation history or professional task content.

## Commands and lifecycle

### `RESTART`

`RESTART` preserves every sound durable boundary while terminating anything which
cannot complete a bounded checkpoint.

1. Persist the command and close new agent-work admission. The gateway continues
   accepting messages and commands.
2. Deliver and record an immediate command acknowledgement.
3. Stop activation sources so they cannot recreate work during the drain.
4. Ask active agents to write a compact handoff and durable checkpoint. The initial
   grace period is thirty seconds from `config/time.cfg`.
5. Mark responsive work recoverable. Interrupt unresponsive work by process group,
   escalating through the configured termination deadlines. No record may remain
   falsely `running`.
6. Stop every destructible ecosystem unit and kill remaining processes in their
   cgroups.
7. Stop Lemonade and its child model servers through root systemd, verify their
   cgroups are empty, and clear failed/start-limit state.
8. Start Lemonade, the resource guard, the pinned small model, inference scheduling,
   control services, notification, and ordinary execution in dependency order.
9. Reconcile interrupted jobs, control turns, outbox records, and incomplete
   verification before reopening activation sources.
10. Require fresh health observations, including a fast-model canary. Restore the
    prior explicit pause state and resume preserved work only after this gate.
11. Report completion or the exact remaining blocker through the permanent gateway.

### `RESET`

`RESET` optimizes for rapid removal of broken live state without making durable
recovery impossible.

1. Persist the command, close admission, acknowledge it, snapshot active record
   identities, mark in-flight work interrupted/recovery-required, and issue the
   durability fence.
2. Do not request model handoffs or wait for cooperative agents.
3. Immediately stop and kill every destructible service cgroup, Lemonade, and child
   model server.
4. Follow the same clean startup, reconciliation, health gate, pause restoration,
   and reporting sequence as `RESTART`.

Neither command deletes queued work, conversations, audit events, completed output,
or recoverable sessions. `RESET` discards volatile execution and inference state;
`RESTART` additionally attempts semantic handoff. Destructive record deletion can
be a future separately named command and is not implied by reset.

The destructible set is an installed, root-owned list derived from the subsystem
catalogue at deployment. Runtime requests cannot add targets. The gateway and
guardian are explicitly absent from the set.

### Lifecycle recovery and reporting

Lifecycle phases are versioned data:

```text
accepted -> acknowledged -> admission_closed -> checkpointing
         -> stopping -> backend_stopped -> starting -> reconciling
         -> verifying -> resumed -> completed
```

`RESET` moves directly from `admission_closed` to `stopping` after its durability
fence. Any phase may enter `blocked` or `failed`; the guardian restarts from the
last verified idempotent phase. Telegram updates are emitted on phase changes and
at the configured progress interval while a phase remains active.

## Highest-priority ordinary-message path

The gateway durably spools an ordinary update and immediately returns to polling.
A fast-control worker consumes the spool independently of longer work. It reads a
bounded conversation tail and compact subsystem-status projection, then submits one
request to the small pinned model through the inference arbiter.

The response schema is plain data:

```text
reply: nonempty user-facing text
decision: respond | dispatch
task: required only for dispatch
role: optional advisory label
constraints: optional bounded task constraints
```

Schema failure, timeout, or backend loss never becomes silence. The gateway emits a
truthful degraded response, retains the turn for recovery, and opens a contact or
inference incident. It does not claim that work started.

The arbiter is the single admission path for local inference. It enforces a maximum
priority lane for fast contact and leaves one physical small-model request sequence
unavailable to deep/background users. Background work cannot consume that reserve.
When necessary, a queued front request preempts cancellable lower-priority inference
or waits only on the dedicated sequence's current front request.

A validated `respond` result completes the turn without creating a deep-control
job. A validated `dispatch` result atomically creates exactly one task using the
turn identifier as its idempotency key. Model and context selection for that task
remain separate, resource-validated scheduling decisions.

## Optional roles

Job meaning and authority must not depend on a decorative role name.

- `role` is nullable.
- A known role file may add context and a default capability request.
- An absent or unknown label is retained as advisory metadata and receives the base
  agent context.
- Role-file paths are never constructed from unchecked text. Safe identifier/path
  handling remains mandatory, but failure to find a definition is not an execution
  failure.
- Capabilities, provenance, authority, budget, and acceptance criteria are explicit
  job fields or assigned execution policy. They are not inferred solely from role.
- Survival recovery uses an installed authority profile and typed tools, not a role
  lookup.

Existing model-generated `unknown role` errors therefore disappear without opening
a path-traversal or privilege-escalation hole.

## Subsystem catalogue and status projection

Tracked subsystem definitions live together under `config/subsystems/`. The initial
catalogue contains:

- `cointelprofessional`;
- `lifecycle`;
- `health_supervision`;
- `inference`;
- `dispatch`;
- `scheduler`;
- `executor`;
- `notification`;
- `resource_control`;
- `orchestrator`, initially `unimplemented`; and
- `messaging`, initially `unimplemented`.

Each definition includes its identifier, purpose, implementation state,
dependencies, services/process groups, heartbeat contract, monitor policy, repair
authority, and escalation class. Unimplemented subsystems appear in queries but do
not have active lease deadlines or monitor schedules.

Generated state lives under `state/subsystems/<subsystem_id>/` and contains atomic
current projections plus append-only events where history matters. The projection
includes:

- implementation and current health state;
- heartbeat path, age, required check identifiers, and latest evidence;
- dependencies and service state;
- open incident and health-gap summaries;
- active-agent count; and
- for each active agent: name, age, optional role, task summary, model, lifecycle
  state, progress age, context allocation/consumption, and owning subsystem.

Jobs, control turns, inference inventory, and systemd remain authoritative. A
projection builder derives the subsystem view from them and records source
timestamps. It never mutates authoritative state while answering a query.

The fast-control prompt receives a bounded summary of this projection. It can answer
ordinary questions such as scheduler status or current agents without launching a
larger job. A narrow read-only tool provides detail when the bounded summary is
insufficient.

## Heartbeat probes

Every implemented subsystem has one frequent small probe agent. Probe schedules are
staggered and driven by `config/time.cfg`. A probe receives only its subsystem
definition, recent projection, open health gaps, and bounded relevant evidence.

The lease writer independently checks that:

- every deterministic check in the subsystem contract passed;
- every confirmed open health gap's temporary or permanent check passed;
- the probe agent returned a schema-valid healthy verdict;
- the evidence generation is current and belongs to this boot; and
- the write deadline has not already expired.

Only then does it atomically replace `heartbeat.json` with a versioned record
containing subsystem, boot identifier, generation, monotonic observation time, UTC
record time, check results, evidence codes, and probe duration. File modification
time alone is not health evidence.

The guardian examines leases every five seconds by initial policy. A missing,
invalid, future-dated, wrong-boot, or older-than-sixty-second lease is stale. One
fingerprinted incident is opened; repeated checks update it instead of producing a
repair or alert storm.

## Bounded repair and escalation

An incident begins with a direct Cointelprofessional report naming the subsystem,
failed evidence, and bounded repair deadline. The guardian launches a smaller
repair model through a recovery runner which does not depend on the failed ordinary
scheduler. The runner receives one incident, explicit authority, a time/context
budget, narrow tools, and a required terminal result.

The repair agent has two survival-owned operations:

```text
report_progress(findings, action, next_check)
escalate_incident(findings, reason, preserved_context)
```

Both append to the incident and immediately enqueue a direct gateway message. The
agent is expected to report material findings and can manually escalate as soon as
it knows that a larger capability or context is required.

After a repair, the guardian launches a fresh probe. A new valid lease is necessary
for recovery; a model's assertion is not enough. If the lease renews, the incident
closes, preserved ordinary work resumes as policy permits, and Cointelprofessional
reports success. No large model is launched.

Automatic escalation occurs when the repair runner:

- exits without a schema-valid terminal result;
- explicitly reports failure;
- exceeds its time budget;
- stops producing progress beyond its lease;
- loses the inference backend;
- reaches a configured context rollover boundary but fails to write a valid handoff;
- is killed by context overflow; or
- completes a repair which the independent probe rejects.

The guardian preserves the initial request, all progress reports, exact evidence,
tool outcomes, transcript/session references, and any valid semantic handoff. It
announces the reason and findings before starting emergency repair.

Emergency mode pauses or preempts ordinary work but never the gateway. The model
router selects the strongest locally available model which passes deterministic
resource admission and gives it the largest safely supportable context. For a
resource/OOM incident, "plausible" excludes a model/context combination likely to
repeat the failure. If the nominal maximum is unsafe, Cointelprofessional says so
and names the bounded alternative; safety is not silently waived.

Emergency progress uses the same direct reporting operations. A missing terminal
result remains an open, reported incident rather than being mislabeled successful.

## Periodic subsystem monitors and evolving health contracts

Each implemented subsystem has one deeper monitor agent. The initial activation
period is five minutes, with stable offsets distributed across that period so the
monitors do not start together. The monitor schedule, evidence budget, and deadline
come from configuration.

Monitors look beyond current heartbeat checks: recent incidents and errors, latency
trends, queue/backlog behavior, dependency consistency, stale or contradictory
records, context failures, delivery uncertainty, and architectural drift. They
cannot renew a heartbeat themselves.

A supported blind-spot finding creates a durable `health_gap` with evidence and
immediately marks the subsystem `suspect`. It dispatches one high-priority,
idempotent health-contract job to:

1. verify the finding against primary local evidence;
2. express it as a focused deterministic or bounded semantic check;
3. add the check to the subsystem's heartbeat contract;
4. add a regression test which fails without the check;
5. repair the underlying issue when authorized; and
6. obtain independent verification.

While a confirmed gap lacks a passing check, the heartbeat writer refuses renewal.
If the finding is disproved, the verifier closes it with its evidence. This prevents
both permanent false-green status and unreviewed model conjecture from silently
rewriting health policy.

## Central timing policy

All tunable operational periods introduced or touched by this work live in the
human-editable `config/time.cfg`. Keys use lowercase snake_case and include their
units. The initial groups cover:

- Telegram polling, sending, command acknowledgement, and degraded-response
  deadlines;
- fast-control inference and decision deadlines;
- inference queue/front-reserve timeouts;
- heartbeat probe periods, maximum age, guardian polling, and probe runtime;
- five-minute monitor activation, staggering, and monitor runtime;
- initial and emergency repair deadlines, progress leases, and user-update periods;
- `RESTART` checkpoint grace and stop/terminate/kill phases;
- Lemonade stop, start, model-load, and health-verification deadlines;
- lifecycle reconciliation and progress reports; and
- control-turn, executor, verification, outbox, and recovery periods encountered in
  the modified control path.

The initial policy is concrete rather than left to implementation-time invention:

```ini
[telegram]
poll_seconds = 1
long_poll_seconds = 25
request_timeout_seconds = 40
command_acknowledgement_deadline_seconds = 2
degraded_response_deadline_seconds = 3

[fast_control]
response_deadline_seconds = 10
maximum_queue_age_seconds = 5

[inference]
model_stop_deadline_seconds = 15
model_start_deadline_seconds = 180
health_verification_deadline_seconds = 60

[heartbeat]
probe_period_seconds = 20
probe_deadline_seconds = 15
maximum_age_seconds = 60
guardian_poll_seconds = 5

[monitor]
activation_period_seconds = 300
stagger_spacing_seconds = 25
run_deadline_seconds = 120

[repair]
initial_model_deadline_seconds = 180
progress_lease_seconds = 60
progress_update_period_seconds = 60
emergency_model_deadline_seconds = 900

[resource]
pressure_confirmation_seconds = 5
emergency_confirmation_seconds = 10
healthy_release_seconds = 60

[lifecycle]
restart_checkpoint_grace_seconds = 30
service_stop_deadline_seconds = 10
terminate_grace_seconds = 5
kill_grace_seconds = 2
reconciliation_deadline_seconds = 60
progress_update_period_seconds = 30

[control_turn]
run_deadline_seconds = 600

[executor]
run_deadline_seconds = 1800
time_slice_seconds = 300

[verification]
run_deadline_seconds = 900

[outbox]
poll_seconds = 2
retry_initial_seconds = 5
retry_maximum_seconds = 60
```

The values are initial operating policy, not embedded defaults. Validation requires
all keys, rejects unknown keys and unsafe/nonpositive ranges, and checks relational
constraints such as `probe_deadline_seconds < maximum_age_seconds`. A command whose
acknowledgement cannot be delivered inside its deadline still proceeds from its
durable record; the gateway reports delivery uncertainty and later lifecycle phases
without replaying the command.

One functional timing-policy module parses, validates, and serves named durations.
Components do not parse or reinterpret the file independently. Durations use
monotonic time for decisions and UTC timestamps only for records.

Long-lived services detect a changed file, validate the whole policy, and atomically
adopt it. The guardian stores an accepted last-known-good projection under
`/var/lib/cointelprofessional/`. An invalid edit does not disable supervision or
partially apply. The previous accepted policy stays active, the live configuration
state becomes visibly degraded, and Cointelprofessional reports every rejected key
and reason. There is no silent default.

Systemd retains only fixed bootstrap backstops needed when application
configuration cannot be read: survival-service restart behavior, process watchdog,
and immutable resource protection. Future model, resource, priority, and behavior
configuration families are outside this implementation; the timing module provides
the pattern without creating speculative files.

## Incident representation

Plain versioned data represents health state. There are no classes or hidden mutable
objects.

```text
health_incident:
  schema_version
  incident_id
  subsystem_id
  fingerprint
  generation
  state
  first_seen_at
  last_seen_at
  failed_evidence
  repair_attempts
  escalation_attempts
  active_run
  next_deadline_at
  latest_verified_observation

incident states:
  suspect -> repair_starting -> repairing -> verifying -> recovered -> closed
                                    |             |
                                    +--> escalating <---+
                                              |
                                  operator_required
```

Every action and user update has an idempotency key derived from incident,
generation, phase, and attempt. Flapping faults create a new generation after the
configured recovery hysteresis. Persistent faults do not generate unbounded agents,
messages, or restarts.

## Error boundaries

- State transitions validate prerequisites before committing a restrictive latch.
  Multi-step effects record the intended next phase so restart recovery can resume.
- Model `busy` and `in_use` states count as alive. Liveness and admission availability
  are distinct facts.
- One malformed job, turn, outbox item, subsystem record, or heartbeat is isolated
  and reported; it cannot terminate a whole scan loop.
- External delivery state distinguishes `rendering`, `ready`, `sending`,
  `delivered`, and `delivery_unknown`. Only interruption after the Telegram request
  begins is delivery-unknown.
- Service-control calls retain exit status, stdout/stderr summaries, and verified
  postconditions. A zero subprocess status alone is not recovery.
- A configured deadline is not merely prompted. The owning supervisor enforces it
  and preserves a partial handoff.
- Resource pressure cannot restart the gateway or enter a retry loop against a busy
  model. Emergency transition tests cover every commit/crash boundary.

## Verification and acceptance

Implementation follows test-driven development. Unit tests cover pure parsers,
reducers, schemas, configuration loading, priority selection, role resolution, and
fake-clock deadlines. Integration tests use fake Telegram and Lemonade endpoints,
temporary durable stores, real subprocesses, and systemd unit verification.

Required fault-injection tests include:

- exact command recognition and ordinary handling of every near match;
- rejection of unauthorized Telegram users and local socket peers;
- idempotent update replay and guardian restart during every lifecycle phase;
- `RESTART` preserving queued work and valid checkpoints while terminating a stuck
  agent;
- `RESET` skipping model cooperation and removing every destructible cgroup;
- proof that Lemonade and child model-server process identities change after both
  commands;
- gateway receipt and truthful response while Lemonade and all agent services are
  stopped;
- front-reserve enforcement while all background model capacity is busy;
- a small repair succeeding, independently renewing the lease, reporting recovery,
  and never launching the large fixer;
- manual escalation carrying findings and context into emergency repair;
- automatic escalation on timeout, process death, missing terminal result, backend
  failure, and context-overflow/handoff failure;
- maximum safe model/context selection under both healthy and resource-pressure
  conditions;
- one five-minute monitor per implemented subsystem running at distinct offsets;
- a monitor finding creating one health-gap job and preventing false heartbeat
  renewal until verified;
- unknown, missing, underscored, and null roles continuing with base context;
- invalid and valid live timing-policy reloads;
- malformed records being isolated instead of blocking later work; and
- deduplicated direct Telegram progress for open, repair, escalation, recovery, and
  operator-required states.

Live deployment acceptance requires more than active systemd units. With David's
approved bot endpoint, the test must establish:

1. a baseline Telegram round trip and measured response time;
2. continued gateway command response while Lemonade is deliberately stopped;
3. successful `RESTART`, observed Lemonade/model PID turnover, preserved work, fresh
   leases, and post-restart ordinary response;
4. successful `RESET`, observed hard teardown, reconciliation, and post-reset
   ordinary response;
5. a synthetic stale lease repaired by the smaller model with no escalation;
6. a controlled repair failure which reports findings and escalates with preserved
   context; and
7. unchanged kernel OOM count and a healthy desktop/control reserve throughout.

Tests must inspect durable records, process identities, cgroups, journals, and
actual Telegram delivery. Documentation or a model saying "done" is not evidence.

## Implementation decomposition

The work is one reliability architecture but will be implemented as independently
verifiable slices:

1. Reproduce and fix the current emergency-transition, busy-model, and optional-role
   failures with regression tests.
2. Add the typed timing policy and migrate touched control-path durations.
3. Build and test the root-installed permanent gateway, guardian, survival spools,
   socket protocol, and installation boundary.
4. Implement durable `RESTART` and `RESET` lifecycle reducers and process-level
   failure injection.
5. Replace serial model-bound ingress with durable fast control and mechanically
   reserved inference priority.
6. Add subsystem definitions, projections, health contracts, leases, and quick
   Cointelprofessional inspection.
7. Add bounded repair reporting, manual/automatic escalation, context-failure
   detection, and largest-safe-context routing.
8. Add staggered five-minute monitor agents and verified health-gap evolution.
9. Reconcile documentation and agent notes, install the approved units, and execute
   the live acceptance sequence.

Each slice has one owner, bounded inputs and authority, tests, a compact handoff, and
review before integration. Adjacent features such as general inter-agent messaging,
a full orchestrator, additional commands, or a broader configuration suite remain
separate tasks.
