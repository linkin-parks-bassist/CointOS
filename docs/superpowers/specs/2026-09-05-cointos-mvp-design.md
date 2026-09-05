# CointOS minimum viable running system

Status: approved by David for implementation and activation on 2026-09-05;
implementation evidence is recorded by the execution index and durable task ledger.
Coordinator: Astra (Codex `/root`), 2026-09-05. Evidence workers: Flint and Cairn
(GPT-5.6 Sol, medium); Sieve (local Qwen3.8 27B extraction).
Provenance: personal orchestration infrastructure, restricted to CointOS for initial
autonomous work. Professional/customer material is outside the initial scope.

## Outcome and authority

Bring up a useful local agent system with responsive Cointelprofessional contact,
mechanical resource protection, dynamic model/context scheduling, continuing tasks,
spontaneous useful maintenance, independent verification, and approval through
Cointelprofessional before a verified improvement changes the running installation.
David explicitly selected that approval channel during this planning discussion.

This proposal replaces the old five-plan delivery order and survival-closure gate.
It preserves obligations, evidence and sound mechanisms, not existing decompositions.
An early live contact milestone precedes complete autonomous maintenance. Neither
milestone waits for the deferred hardening queue. No runtime action, credential
access, Telegram transmission, installation, publication, or merge is authorized
merely by this document being written. Execution follows David's approval of the
concrete plan; do not re-ask for actions that approval explicitly covers.

## What is essential

The three binding operating principles are: Coin stays available; no OOM; seamless
handover across dynamic, apparently arbitrary context allocations. Coin availability
depends on preventing OOM. Context continuity is independently mandatory and cannot
be postponed until the other two are satisfied.

1. Permanent model-independent receipt, lifecycle control and honest degraded contact.
2. Real reserved front inference capacity; ordinary work cannot consume its slot.
3. Host/GTT/context/load-transient admission, early pressure response, and exclusive
   recovery after OOM. Coin and the desktop retain their reserve in every mode.
4. Durable task identity, short bounded execution, interruption and fresh-context
   continuation. Context fullness never becomes a terminal task failure.
5. Autonomous discovery from notes and actual files/logs/state; useful work or a
   durable contribution, with source evidence and no manufactured task obligation.
6. Janitor, Gardener, Innovator, Speculator and existing specialist roles have clear
   remits. Capability and authority are task facts, not privileges inferred from names.
7. Failed health checks lead to bounded diagnosis/repair and escalation; repair
   reporting survives the ordinary scheduler/notifier being broken.
8. A tested, independently reviewed change can request approval through Coin,
   activate after that exact approval, and roll back after failed startup checks.
9. Basic tests and live evidence show the whole loop, including actual useful GPU work.
10. Live agent-to-agent communication survives context turnover, with direct/role/global/Coin addressing and truthful delivery/acknowledgement states.

## Distilled structure

| Level of meaning | Owning representation/functions | Adjacent contract |
| --- | --- | --- |
| External ingress/egress | Telegram records, local HTTP adapter, OpenCode events, systemd observations | Decode literal bytes once; preserve authenticated identity, timestamps and uncertainty. |
| Durable work | Existing jobs with validated task contract; control turns; append-only events | One identity and state authority; atomic claims/transitions; no success from exit code. |
| Admission/execution | Resource envelope, inference lease, worker lease, budget and continuation records | Reserve before dispatch; remeasure before load; release only after observed completion. |
| Autonomous selection | Configured scopes/role weights, due times, existing jobs and note references | At most one claim per source/generation; every child inherits a smaller authority/budget. |
| Observation/repair | Subsystem check results and incident reducer | Deterministic health independent of inference; bounded repair, evidence, independent recovery probe. |
| Release control | Immutable candidate manifest, verification, approval, activation attempt | Approval binds exact digest/base/target; durable intent, observed health, automatic rollback. |

These are software responsibilities, not a daemon per table row or per role. Ordinary
collaborators call functions over explicit shared data. Queues exist at real process,
inference, privilege, or Telegram boundaries. Status reads the same authoritative
records; it does not invent a second job or agent database. Cross-cutting admission,
drain, incident and release functions inspect the records they need directly.

Real cycles are explicit: observe/select/execute/verify; pressure/drain/recover;
context/handoff/resume; propose/approve/activate/probe/rollback. Each has one owner,
a deadline and a durable stopping state. No OOP, actor framework,
universal plugin registry, or new database is required for this MVP.

## Reuse, replacement and cutover

Keep the pure survival lifecycle reducer, exact RESTART/RESET protocol, crash-safe
record publication, dedicated gateway identity, protected installed code, central
timing validation, narrow backend adapters and usable process/session evidence.
Keep only tests of current obligations; passing tests do not sanctify a wrong model.

Replace the mixed ordinary Telegram/deep-control route with one canonical fast
turn -> optional task -> result route. Reuse turn identity, durable delivery and
conversation operations where they fit; do not first ship a permanent adapter to
the unconditional old deep controller. Remove obsolete consumers at cutover.

Rebuild model admission around explicit resource and per-sequence context facts;
delete resident-model bypasses and legacy substitution routes. Extract execution
budget/continuation policy from the monolithic executor. Replace diffuse Steward
task generation with scoped discovery and role selection. Notes remain ordinary
Markdown; a Speculator observation does not require a new domain entity or queue.

Do not rewrite all of cli.py or the runtime format as a prerequisite. Add the task
contract at its current owner; extract only the persistence/transition functions
needed by multiple consumers. Where live old records need conversion, perform one
bounded, previewed conversion preserving identities, source records and append-only
history. Do not retain a second parser indefinitely. A previous installed release
is an inactive rollback artifact, not a concurrent controller.

## Shared execution contract

Every new executable job receives `task_contract` containing `objective`, `scope`
(absolute workspace plus read/write path lists), `authority_profile`, `acceptance`
(structured local checks or expected artifact facts), `budget`, `source_key`,
`parent_job_id` (nullable), and `stop_condition`. Existing `id`, `role`, `task`,
`agent_name`, state, model decision and timestamps retain their meanings.

`budget` contains `run_seconds`, `task_seconds`, `maximum_attempts`,
`maximum_output_bytes`, `maximum_evidence_items`, and `maximum_children`.
Output and wall-time limits are enforced by the executor; evidence limits by the
evidence reader/tool adapter; child limits by enqueue admission. A prompt alone
does not satisfy these requirements. Context rollover is continuation, not a failed
attempt; cumulative budget still applies. Budget exhaustion yields a useful partial
handoff and a visible paused/partial outcome, never a fabricated completion.

Work states already present in jobs are reconciled through the owning transitions.
Add explicit continuation/approval states only where the contract requires them;
do not add another parallel task lifecycle. Accepted observations and proposals can
be completed outputs even when they do not request implementation.

## Model and resource policy

The operating model is a protected small front plus replaceable work inference.
Initially one local work invocation runs at once; the limit is validated policy,
not an architectural maximum. Multiple logical agents may be queued/resumable.

For local implementation workers, select the largest task-qualified model whose
verified model size, supported context, load transient and current allocation fit
the measured envelope. Then select its largest safe per-sequence context. Record
why larger alternatives were excluded. Parameter count, file bytes, available RAM,
GTT use, and KV demand are separate quantities; model names and registry size alone
are insufficient admission evidence. Unknown or stale facts produce explicit defer,
or an explicitly reported smaller verified choice; never an optimistic guess.

Capacity is not prompt length. A 131072-token allocation does not authorize reading
131072 tokens of irrelevant material. Leave room for output, tool results and
handoff. Read actual backend allocation per sequence, not just an advertised model
maximum or total context shared across sequences. Recheck loaded models too.
Choose any supported allocation quantum within the measured envelope; the existing
`context_candidates` list is not the new architecture. A task may move between
models and larger or smaller context allocations. Prepare a destination-sized
handoff and bounded evidence references before giving up its current allocation;
never seed a smaller context with an oversized transcript. Preserve task identity
and meaning across the transfer. If resources require immediate interruption,
durable task state supplies the recovery handoff and remains visibly pending until
a safe continuation can run; it is not a terminal context error.

All local inference consumers, including OpenCode HTTP requests, naming, routing,
verification and background presentation, enter the same admission owner. The
front lane has one exclusive physical sequence. Proxy/session credentials or
process configuration identify the admitted owner; client-supplied priority alone
cannot steal that lane. Root emergency mechanics do not depend on this arbiter.

David's required scheduling order is Sole Survivor, Coin, small health inspectors,
large health inspectors, then all other roles. Scheduling rank and protected
capacity are distinct: the highest-ranked survivor may preempt replaceable work
but cannot consume Coin's reserved slot or memory. Deterministic guardian/resource
actions are not model jobs and remain runnable without inference.

Proposed initial base priorities in `config/scheduling.json`:

| Role/profile | Priority |
| --- | --- |
| sole_survivor (installed incident authority only) | 1000 |
| coin (authenticated front/control profile only) | 900 |
| health_inspector / small | 800 |
| health_inspector / large | 700 |
| verifier | 600 |
| coder, worker | 550 |
| auditor | 500 |
| refactorer | 450 |
| gardener | 350 |
| janitor | 300 |
| documenter, default new/unknown role | 250 |
| chunker | 200 |
| innovator | 150 |
| speculator | 100 |

These values are policy, not role branches in code. Explicit role registration may
change lower-band priorities without implementation changes. The arbiter resolves
effective priority from installed role/profile policy plus trusted task authority;
an agent cannot gain emergency/contact/inspection priority by inventing a label.
Queue age boosts ordinary jobs up to 699, never above health inspection. Due-time
and per-profile resource budgets bound inspection frequency; unused inspection
capacity goes to ordinary work. Higher priority affects queued selection, bounded
preemption of running work and resource reclamation, not just displayed ordering.

The current 32 GiB protected reserve, 12 GiB model-load transient and 64 GiB GTT
boundary remain initial policy pending measured validation. Do not widen them to
fit a preferred worker. Actual pressure can invalidate an earlier admission.

Normal -> pressure drains work before OOM; pressure -> normal requires sustained
healthy samples. An OOM increment immediately closes ordinary work, preserves
durable state and runs one recovery owner. Escalation uses the strongest safe
recovery route after reclaiming replaceable work allocations. Reopening needs
observed health, not the survivor's assertion. Busy/in-use means alive, not missing.

## Worker drain and smoke-test ownership

Every Codex-managed local run is registered before it starts. Registration records
lease ID, PID plus process start identity or hosted-agent handle, scope, model,
deadline and stop method. One cross-process admission lock makes registration and
drain mutually exclusive. A smoke request first closes new worker admission, then
asks active local jobs to wrap up. Codex waits for completion/checkpoint and observes
that the process groups and inference requests have ended. A timeout names the
blocker and defers smoke; it never authorizes running alongside an unknown worker.

Local tasks target 2-5 minutes, hard run limit 300 seconds, wrap-up budget 30 seconds
and termination grace 15 seconds. Split work at independently checkable outcomes.
Sol workers use `gpt-5.6-sol`, `reasoning_effort: medium`, with isolated context and
15-25 minute task budgets. Hosted workers may continue read-only analysis during
smoke; they may not mutate smoke-covered files/services or spawn local work. The
coordinator also waits for any hosted writer whose files are part of the test.

Only the named smoke owner may admit test inference during the fence. Coin and
survival contact remain available. Once ordinary local workers are fully stopped,
the owner may unload their model, load the tested allocation and run the probe.
Failed smoke leaves ordinary admission closed if health is uncertain. Releasing
the smoke fence never clears a pressure, emergency, lifecycle or operator pause.

## Health and spontaneous work

Frequent health checks are deterministic, short and model-independent. A stalled
model cannot be required to declare its own supervisor healthy. Begin with contact,
inference, work execution, resource control, autonomous selection and release
control, each with actual process/endpoint/queue progress checks and boot-bound
freshness. Model monitors inspect deeper evidence through ordinary resource admission.

This deliberately replaces the old mandatory model verdict on every frequent
heartbeat. Initially the deterministic tick is 5 seconds; each check has a 2-second
deadline; leases expire after 30 seconds. The front canary is scheduled no faster
than every 60 seconds and its result has an explicit age. These are configurable
policy, not hard-coded architectural constants. Timed-out checks fail locally and
do not block later checks or gateway polling.

Health inspectors have one extensible role with small and large execution profiles.
Small inspections consume a bounded recent deterministic observation bundle; large
inspections investigate broader evidence and blind spots. Initially one small
inspection is due every 60 seconds with a 30-second run budget, rotating through
subsystems; one large inspection is due every 600 seconds with a 120-second budget.
These are system-wide cadences, not multiplied by every subsystem. They use the
trusted 800/700 priority bands and resource admission. Deterministic probes continue
even when inspections are deferred. Inspector output cannot renew its own health
lease or apply a code change without the ordinary verification/approval path.

Autonomous selection uses one deterministic scheduler tick, not one daemon per
role. A due scope/role or an incident can create a bounded discovery job. Initial
discovery interval is 300 seconds with stable staggering and one pending job per
scope/role. Subsequent eligible work may run immediately while capacity remains;
the interval does not force the GPU idle between existing useful tasks. Queue
aging prevents a busy role from excluding others. Pressure, pause, drain and repair
take precedence. There is no backlog explosion after missed ticks.

The first scope is this repository's non-secret source, docs, notes, test results,
and bounded operational event tails. Runtime conversation bodies and other projects
are excluded from ambient prompts unless David separately puts them in scope.

| Role | Initial remit/output |
| --- | --- |
| janitor | Notes, links, artifact/file organization and safe housekeeping; no code cleanup or deletion of runtime records. |
| documenter | Observe actual files, logs, interfaces and behavior; write grounded descriptions with sources, uncertainty and observation dates. No implementation. |
| gardener | Small code cleanup, dead code and local clarity; preserve intended behavior. |
| innovator | Grounded structural/capability proposals; no implementation. |
| speculator | Observations, possibilities and questions; no implementation or forced task conversion. |
| chunker | Extract one explicit unfinished item into a traceable handoff; no dispatch. |
| auditor | Investigate a bounded correctness/architecture question and record evidence. |
| health_inspector | Small/large profiles inspect bounded health evidence; both outrank ordinary work, small outranks large. Findings go to incident or verified improvement work. |
| coder / worker / refactorer | Perform one accepted task within its authority; refactorer owns larger evidenced structural changes. |
| verifier | Independently accept/reject the exact candidate outcome. |
| sole_survivor | Exclusive incident recovery with safe resource admission. |

Steward has no recurring MVP assignment; its useful task-card evidence moves to
scopes owned by the roles above. Lead adds no second approval ceremony: the executor
checks handoff completeness and an independent verifier checks substance. Preserve
historic identities without requiring these roles for new work.

Roles are extensible data. Add `roles/<lowercase_snake_case>.md` for a new context;
add a validated scope/schedule entry only if it should spawn autonomously. No code
switch, fixed role enumeration, new daemon or database migration is required.
Execution requirements and authority profiles are explicit task fields and shared
validated configuration. Unknown role labels remain advisory and use base context;
they cannot manufacture capabilities or bypass an authority profile. Documenter
records what is observed; Speculator may explore what might be; Janitor maintains
the existing material. None requires a separate software execution mechanism.

An agent may inspect, identify a task, perform authorized bounded work, leave partial
progress, or write a note/proposal. A result states sources, observation versus
inference, changed artifacts, checks and next action when one exists. No useful work
found is a legitimate result. Notes and task source keys deduplicate discoveries;
Markdown interpretation happens only in the discovery/tool fingertip.

Agents can request a child through validated enqueue, with inherited/narrower scope,
shared cumulative budget, explicit dependency and acceptance. Discovery has at most
one child request per run initially. Role-only prompts never grant wider authority.
Agent-to-agent messaging is explicitly part of the MVP, per David's subsequent
direction. Use the durable mailbox at the actual asynchronous runner boundary
described below; ordinary intra-process collaboration remains direct functions.

## Live agent communication

Carry forward the contract in `agent_notes/0003-control-plane-presence-and-live-messaging.md`:
direct exact-run messages, role-local announcements, global announcements and a
Coin address. Initial kinds are `information`, `request_status`, `wrap_up`, `cancel`,
`handoff`, `announcement`. Resolve recipients when publishing, preserve sender and
causal task/message IDs, and store one idempotent delivery state per recipient.

Project addressable runs from authoritative jobs and worker leases. A live logical
run ID survives context/model/process turnover and resource pauses; process identity
is a separate fact. The started generation's durable continuation state retains its
mailbox address between runner leases. Unexpected death is reported as unreconciled,
not healthy or successfully completed; bounded recovery resolves that state. Work
that has never started is not a live peer. A completed recipient is recorded as
unavailable, not silently replaced by a different agent with the same name/role.

Expose `send`, `receive` and `acknowledge` as ordinary functions plus narrow runner
tools. Pending messages enter at the earliest safe model/tool boundary. If the
adapter cannot interrupt an in-flight request, report queued status and deliver on
its next boundary. Never claim live communication by editing the original prompt.
Use an explicit observed acknowledgement; enqueue or HTTP submission alone is not
acknowledgement. Acknowledgement does not mean obedience or task success.

Any scoped live peer may send information/handoffs. Wrap-up and cancellation require
the recipient's owner/coordinator or installed recovery authority. Role/global
announcements do not spawn work or demand reply-all. Message urgency cannot elevate
an ordinary sender above the trusted role priority bands. Coin relays a message to
David only under the ordinary reporting/approval policy.

Initial configurable limits: 16384-byte payload, 32 recipient fan-out, 128 pending
messages per recipient and seven-day terminal-message retention. If a broadcast
exceeds its declared budget, defer/reject it explicitly; never silently omit some
recipients. Nonterminal messages persist until delivered, expired by explicit
policy or resolved as recipient unavailable. No runtime cleanup rewrites JSONL.

R1 drain sends authorized wrap-up through this channel once available, observes
checkpoint and process/request exit separately, and still works if the mailbox is
broken through its installed bounded process-control path. Messaging cannot become
a circular dependency for survival. Final acceptance includes bidirectional live
delivery, a role/global announcement, exact ACK semantics and a context rollover.

## Configuration and policy ownership

Use standard-library `configparser` for the existing `config/time.cfg` and `json`
through the strict JSON decoder for structured families. `survival/time_policy.py`
already uses ConfigParser; preserve its semantic validation and accepted-policy
recovery. Do not write another configuration language or add a parsing dependency.

| File/family | Adjustable values | Owner/application boundary |
| --- | --- | --- |
| `time.cfg` | Poll/probe periods, deadlines, wrap-up, leases, approval lifetime | Timing owner; complete validated reload, new operation deadlines only. |
| `resource-policy.json` | Host/GTT reserves, pressure/hysteresis, load/transient estimates | Resource owner; tighter policy closes admission and arranges handover before reallocating. |
| `model-policy.json` | Qualified model preferences, slot counts, context/output policy | Admission owner; new leases only, actual backend facts still required. |
| `scheduling.json` | Role/profile priorities, bounded age boosts, default role rank | Scheduler; recompute ready order and bounded preemption without stealing Coin reserve. |
| `autonomy.json` | Role scopes, enabled state, weights, cadence and discovery budgets | Selector; next tick, no missed-tick spawn storm. |
| `subsystems.json` | Implemented owners, checks, lease ages, repair policy | Health owner; no invented healthy defaults. |
| `messaging.json` | Payload, fan-out, mailbox count/retention and poll periods | Mailbox owner; never silently drop pending messages on a tighter limit. |
| `workspaces.json` | Explicit work/read/write scopes and authority profiles | Task owner; revalidate queued work, checkpoint work losing authority. |

Each family has one parser/validator owner and a versioned accepted snapshot with
digest and activation time. Missing, unknown, nonfinite, invalid or relationally
unsafe values reject the complete update and leave the previous accepted snapshot
active, with a visible error. Q1 supplies small parsing/reload functions; each
owning task adds its semantic validator. Do not scatter raw config reads through
consumers or hide several owners behind a universal interpreter.

David may edit operator configuration directly. Agent-proposed changes use the
same candidate/verification/Coin-approval path as code. In-flight operations retain
their recorded deadlines; resource reductions trigger controlled drain/continuation
instead of silently shrinking a live context. Fixed laws remain fixed: identity,
protocol/authentication rules, valid states and the three operating invariants.

## Verified improvements and Coin approval

All agent edits occur in an assigned isolated candidate workspace. They cannot
rewrite the files imported by the running services. Candidate tests run there;
independent verification binds base revision, diff/tree digest, test evidence and
declared targets. A zero exit or a verdict for another digest cannot approve it.

Coin sends one concise approval request with purpose, scope, evidence, risk and
candidate identity. Literal `APPROVE <request_id>` or `REJECT <request_id>` is parsed
from an authenticated update before inference. Approval binds the full candidate
digest, expected active base, target set and expiration, with the Telegram update
identity as replay key. Natural-language discussion alone cannot activate a release.
Expired approval or changed base/candidate requires a fresh request.

The installed release manager performs fixed operations only: validate the approved
manifest, close/drain work, stage immutable files, switch the active release,
restart the declared allowlisted targets, probe, and commit or restore the prior
release. No candidate build/test/install script executes as root. User-plane
activation and protected survival-plane activation are distinct target classes.
Protected updates preserve a root-owned recovery path and gateway availability;
an update which cannot do so remains approval-ready but operator-blocked.

Emergency containment/restart within installed recovery policy does not wait for
approval. New code/configuration changes do. A failed candidate is retained for
diagnosis and deduplicated repair; it is never endlessly reapplied. First MVP proof
uses a harmless user-plane improvement; protected self-update is demonstrated with
an unchanged approved release/rollback rehearsal before advertising that capability.

## Acceptance and deferred work

Early online: one authenticated ordinary message reaches the canonical turn and
replies, replay creates no second task, RESTART or RESET preserves contact and
ordinary response recovers, the old poller is inactive, and OOM count is unchanged.

Complete MVP: useful local work completes and is independently verified; front
response survives a busy worker; synthetic pressure prevents new work; interrupted
work resumes; context rollover finishes the same task; a deterministic incident
produces a bounded repair and independently observed recovery; a spontaneous
discovery produces useful work or a grounded contribution; Coin approval activates
one verified change; a failed candidate rolls back; new spawning resumes only after
the smoke fence and all other restrictive states permit it. Observe two autonomous
cycles and record real latency, resource and job evidence. No deliberate host OOM.

Defer exhaustive hostile-spool/permission/crash-matrix tests, every-subsystem model
monitors, voice/attachments, other projects, hardware
brokers, global code cleanup, full format/database redesign and benchmarking every
model. Keep ordinary-operation defects, OOM risk, lost contact, unrecoverable state
and unsafe rollback in the MVP gate. Deferred findings live in the one hardening
queue in the plan index; none can silently become a new bootstrap prerequisite.

## Architectural review of this proposal

- Vertical replacement: backend/Telegram encodings end at adapters; admission and
  discovery consume meaningful resource/task records. Backend replacement changes
  its adapter and qualification evidence, not role prompts or incident semantics.
- Horizontal access: drain, status and release operations inspect shared identities
  and state directly; no mirrored roster or actor choreography.
- Contracts: every effect names authority, owner, budget, expected postcondition and
  recovery boundary; unknown delivery and partial work remain distinguishable.
- Machine reality: per-sequence context, load spikes, process groups, privilege,
  GPU pressure and Coin latency remain explicit. Hardware modules are not being
  designed here; the software no-OOP rule is not applied to physical GPU instances.
- Distillation: rejected controllers/role schedulers disappear at cutover; keep
  rollback releases and evidence without keeping parallel live semantics.
- Verification limit: this is a design and task contract, not a claim that the
  current implementation or hardware already satisfies it.
