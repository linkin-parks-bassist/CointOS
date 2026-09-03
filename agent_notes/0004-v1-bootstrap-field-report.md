# V1 bootstrap field report

Status: historical account and handoff for future ecosystem custodians.

Compiled by Palinode (Codex agent) on 2026-09-04 from Git history, the original
vision, durable job and event records, private conversation chronology, live service
state, and direct verification. The implementing root-agent context was compacted
several times during the work; this report therefore prefers durable evidence over
recollection. It contains no credentials or professional/customer material.

## Executive summary

In one extended session, the machine went from a concept document and an existing
local model server to a working first vertical slice of a local agent ecosystem.
David can talk naturally to an allowlisted Telegram bot, retain conversational
context, inspect live machine and queue state, dispatch named role-backed local
agents, receive dependent results, and pause the system. Timer and path units drive
inbox work and periodic stewardship. Jobs, model decisions, prompts, outputs,
verification handshakes, and messages have durable local representations. Local
models are loaded automatically at boot.

This is reasonably called v1 in the experiential sense: the main loop exists and
has been exercised. Architecturally it remains a functional prototype requiring
consolidation before broad parallelism or stronger authority. That distinction is
important. A lively interface and many successful handshakes do not prove crash
consistency, safe interruption, correct publication boundaries, or semantic
completion.

The most important achievement was not any one feature. It was the emergence of a
design rule: whenever the bot behaved mechanically, lied by implication, lost
context, or mistook activity for success, the repair moved authority toward explicit
state, evidence, and narrow interfaces while leaving language understanding and
judgment to capable models.

## Starting point

`/home/david/AGENT_ECOSYSTEM_VISION.md` described a local-first environment that
could accept rough ideas, create structured work, use role-specific agents, ask only
meaningful questions, run periodically or in response to events, remain inspectable,
and eventually operate hardware through controlled Vivado/JTAG boundaries. Lemonade
and OpenCode already existed. No custom persistent agent services or working remote
control plane existed.

The initial machine view was misleading: firmware reserved 64 GiB as fixed UMA,
leaving Linux approximately 62 GiB. This later became a major scheduling constraint
and a useful lesson in distinguishing physical unified memory, firmware carveout,
Linux-visible total, reclaimable memory, VRAM, and dynamic GTT.

Telegram was unfamiliar to David and was not installed locally. Browser links tried
to invoke an absent system handler, which made initial bot setup needlessly opaque.
Installing the desktop client and walking through the bot exchange made the remote
surface testable; the product then had to earn its usefulness through repeated live
conversation rather than configuration alone.

## What was built

### Durable coordination core

- A Git repository at `/home/david/agent-ecosystem` became the inspectable source of
  truth.
- Markdown inbox files are discovered idempotently using content hashes.
- Jobs are atomic JSON records with explicit lifecycle state; audit events are
  append-only JSONL.
- The initial intake path turns a rough idea into a project proposal and clarification
  checklist without silently treating a proposal as implementation authority.
- A global `PAUSED` state is checked before new work begins.
- Role and task text are compiled into the exact prompt packet given to the runner.
- OpenCode executes local agent work as user `david`, captures complete output, and
  has a bounded timeout.

### Roles and custodianship

Spawnable Markdown roles currently include Intake, Worker, Steward, Auditor,
Refactorer, Verifier, and Coder. The Telegram control-plane role is infrastructure,
not a spawnable worker. Roles state mission, inputs/outputs, permissions, approval
boundaries, model guidance, handoff, and success/failure conditions; their full text
is injected when an agent is prepared.

Periodic Stewards draw from a fixed, overdue-weighted task deck instead of creating
one role per maintenance concern. Cards cover system-map maintenance, filesystem
health, logs, Cointelprofessional quality, architecture, improvement gardening,
fact consistency, component handshakes, unfinished plans, and model catalogue
reconciliation. This gives varied observation without unbounded social-role growth.

Auditors are meant to establish evidence and violated invariants. Refactorers turn
accepted findings into bounded structural repairs. Verifiers independently decide
whether a finished run actually achieved its request. All roles may leave a durable
message for Cointelprofessional when David genuinely needs to know or decide
something.

### Telegram control plane

The Telegram adapter long-polls from a user service and admits only configured user
IDs. The token remains outside Git in a mode-restricted environment file. Ordinary
text is model input, never shell input. The control model receives its complete role,
recent private conversation, live queue/resource facts, role inventory, model
policy, and narrow validated tools.

The first implementation used a brittle intent-classifier JSON envelope. Real
conversation showed that this repeatedly misunderstood corrections and questions.
It was replaced by a conversational model that decides whether to answer, inspect
typed state, amend pending work, pause, or dispatch. Exact high-confidence lifecycle
questions use authoritative typed projections; the model interprets ambiguity and
presents facts but does not own those facts.

Private per-user JSONL conversation memory made follow-ups such as “I meant
argument” possible in principle without a human manually re-injecting transcripts.
Dependent outbox records allow a message to wait for a job's verified terminal
state. Agent-originated notices are rewritten into concise informal language before
delivery, while raw IDs and evidence remain local.

Agents receive durable generated names rather than a fixed pool. The naming policy
tries to be task-aware and internationally broad, permits occasional `Journathan`-
style linguistic accidents or clever puns, and rejects cultural caricature and
fantasy-name sludge. The current probabilities are now known to be too conservative;
significantly stranger generation is recorded as pending work.

### Truthful completion and observation

Early jobs exited with code zero after producing plans, partial work, or nothing
substantive, and the outbox announced success. This exposed a category error: process
termination is not semantic completion. Ordinary clean runs now enter
`awaiting_verification`. A separately selected Verifier inspects the request, full
run, artifacts, tests, and live state, then emits a schema-checked verdict. Only an
accepted verdict produces completion; malformed or negative verdicts reject.

The watchdog runs cheap deterministic checks every three minutes and periodically
enqueues one deduplicated qualitative Steward review. It checks stale work, missing
verification links, service health, model/catalogue mismatches, output progress,
and transport error storms. This realizes the “community of onlookers” idea in a
bounded initial form: models supply judgment, while deterministic checks supply
ground facts and escalation triggers.

### Model choice and scheduling

Model choice is recorded job state, not an executor constant. Each decision includes
model identity, rationale, and a resource snapshot. The intended factors include
role/task fit, capabilities, context, downloaded and resident state, load, live
memory, queue age, and switching cost. Explicit user choices are retained.

The current runner still serializes durable worker jobs, but the scheduling policy
prefers capable resident models, batches compatible work, assigns a higher switching
penalty and longer residency to larger weights, and prevents indefinite starvation.
The control model is Qwen3.8-27B-GGUF with four llama.cpp sequences and one reserved
for responsiveness. Qwen3-Coder-30B-A3B-Instruct-GGUF is loaded alongside it with
two sequences. Coefficients are loaded once per backend; parallel sequences have
separate inference/KV state.

This is request-level parallelism and coarse job-boundary scheduling, not yet the
rich time-sharing David wants. There is no safe token-level preemption, checkpointed
agent continuation, model lease abstraction, or general live inter-agent bus yet.

### Authority, provenance, and workspace integration

David's personal-project instructions were recovered from the attached USB and
adapted into `/home/david/AGENTS.md` for a mixed personal, Avnet/AMD, partner, and
customer workstation. The resulting policy makes provenance an operational boundary:
professional material must not leak to personal repositories, Telegram, unrelated
notes, or external model contexts. Permission to edit is not permission to publish.

The policy preserves David's revealed engineering taste: abstraction grounded in
machine reality, infrastructure before features, explicit meaning, lean modules,
lossless simplification, lowercase snake_case, manual/visible ownership, and a total
prohibition on OOP. Existing `unittest.TestCase` code is recorded migration debt,
not precedent.

The workspace catalogue registers:

- `/home/david/reference_projects/kestrel-interface-ab1b88db9612` as an immutable,
  detached reference at commit `ab1b88db9612cf177d991a9855bbdbe56f0b1244` for
  David's human-written C/Verilog style and architecture;
- `/home/david/personal_projects/pigen` as an active personal repository where
  approved work may use topic branches, local commits, push, and pull requests, but
  never merge without explicit approval.

A narrow root-owned APT broker allows Workers and Refactorers to install precisely
named packages from already configured repositories without granting general sudo.
It rejects options, paths, repository changes, removals, and upgrades and journals
requests. It has been exercised for `iverilog` and `pipx`. This preserves the desire
for agents to install ordinary tooling while keeping privilege a typed capability.

### Boot and memory configuration

Systemd user path/timer units, the Steward watchdog, Telegram gateway, and resident
model loader are enabled. User lingering allows the user manager to start at boot.
The system Lemonade service starts first; `agent-models.service` loads the resident
27B control and coding models; Telegram starts after the model loader.

The Strix Halo memory setup was changed from a 64 GiB fixed UMA carveout to the
minimum 512 MiB carveout through `/sys/class/drm/card1/device/uma/carveout`. The
official `amd-debug-tools` utility was installed with `pipx`; `amd-ttm --set 100`
wrote `options ttm pages_limit=26214400` to `/etc/modprobe.d/ttm.conf` and rebuilt
the current initramfs.

One reboot initially appeared unsuccessful because the configuration was actually
written after that boot. The distinction was caught by comparing the live module
parameter, file birth time, initramfs time, and boot time instead of trusting the
tool's success text. After the next controlled reboot, direct observation showed:

- UMA index `0`: 512 MiB fixed VRAM;
- Linux `MemTotal`: approximately 124.9 GiB;
- live TTM `pages_limit`: `26214400` pages;
- live GTT total: exactly 107374182400 bytes (100 GiB);
- both resident 27B models loaded simultaneously;
- successful generated-response probes through Lemonade for both models;
- no new GPU reset, fault, hang, or OOM during the probes.

## How the design evolved through failure

The live Telegram transcript is the best product test that occurred. Important
failures and the design lessons they produced were:

1. **No situational awareness.** The bot answered “I cannot see your local
   environment” while running on the machine. Its role now includes machine identity,
   system purpose, runtime topology, and tools for live state.

2. **No conversational continuity.** A correction from “agreement” to “argument”
   was handled as a fresh generic query. Private conversation memory and pending-job
   amendment were added.

3. **Fire-and-forget work.** A task was queued, but its later result was not returned
   naturally. Dependent outbox messages and agent-originated relays were introduced.

4. **Mechanical presentation.** Raw JSON, task IDs, “job completed,” generic chatbot
   opt-in questions, and repeated canned acknowledgments felt wrong. Presentation
   was separated from durable internal records, notifications became informal, and
   generic invitation tails were suppressed.

5. **Brittle routing.** The intent classifier emitted invalid roles, mishandled
   ordinary questions, and encouraged schema-shaped conversation. It was deleted in
   favor of a model-driven conversational controller with typed tools.

6. **Silence and spam at once.** Immediate canned acknowledgments appeared on every
   message, while actual generated replies could stall. Canned replies were removed;
   a literal disaster fallback remains only after five minutes. Later, that fallback
   phrase contaminated conversation history and the model reproduced it; synthetic
   fallback text is now excluded from model context. Fast generated first response
   still needs further improvement.

7. **Stale or invented operational facts.** The bot confused Lemonade (server) with
   Qwen (model), called available RAM total RAM, and sometimes answered lifecycle
   questions from memory. Live fact snapshots and typed lifecycle projections were
   added. Any future cached machine profile must be treated as policy, not telemetry.

8. **Exit zero called success.** This directly caused the independent semantic
   verification architecture.

9. **Context overflow.** A worker absorbed broad directory listings and exceeded a
   32k limit. Context limits were raised for capable models, but the deeper lesson is
   to scope evidence and preserve resumable task slices rather than dumping a home
   directory into one turn.

10. **Model residency collisions.** Numerous Steward/Coder runs received HTTP 400
    when routed to a non-resident model while the control model occupied available
    capacity. The immediate repair was residency-aware routing and later explicit
    dual-model preload. The 4B model performed poorly and was removed from the
    intended resident pair. True time-sharing remains open.

11. **Active process mistaken for health.** Service status, exit codes, and load
    commands repeatedly looked fine while useful behavior was absent. Audits now
    combine process state, logs, durable transitions, artifact inspection, and small
    end-to-end probes.

12. **Shutdown exposed a missing control channel.** Before reboot, a live Wren
    (Steward agent) could not be asked to wrap up; its stdin was already a closed
    prompt file and the runner had no inbox. It was allowed to finish rather than
    being stranded. This produced the safe-powerdown and live-message-bus notes.

## Process observations

The development rhythm was unusually direct: David tested the bot conversationally,
called out bad taste or false behavior immediately, and the root coding agent traced
each symptom into state, logs, prompts, and service boundaries. Small coherent Git
commits preserved the sequence. This was much more productive than designing the
whole social system in advance.

The best changes converted revealed taste into central policy: names, informal
presentation, no generic follow-up prompts, capable model use, OOP prohibition,
semantic verification, and provenance. The weakest changes were local conditions
added under time pressure. `docs/architecture-assessment.md` correctly identifies
that `telegram.py` and `cli.py` still combine too many responsibilities and that
job schemas/transitions are insufficiently formal.

Compaction of the implementing agent's context reinforced the need for three
different memories: append-only evidence, explicit current state, and curated
Markdown. Git history reconstructed the work more faithfully than a final chat
summary would have.

There was also an important restraint: David requested strong remote control and
the ability for agents to install things, but the implementation did not turn
Telegram into arbitrary remote shell or grant general sudo. Instead it built narrow
typed actions and a scoped package broker. Remote convenience must never silently
expand disclosure or root authority.

## Current verified condition

At report time:

- all five boot-facing agent units/timers checked were enabled and active;
- dispatch was live;
- Qwen3.8-27B and Qwen3-Coder-30B were resident together;
- the 100 GiB GTT configuration was live and persisted through initramfs;
- the standard-library test runner passed 32 tests in 0.317 seconds;
- `pytest` itself was not installed, so do not claim a pytest run;
- durable historical state contained 20 failed, 18 delivered, 9 completed, 3
  rejected, 2 queued, and 1 awaiting-verification record.

The failed count is historical durable evidence, not proof of twenty current service
faults. It does show how rough the early live exercise was and should eventually be
made easier to distinguish from actionable failures in presentation.

Some checked-in documentation is already stale. In particular, `docs/status.md`
still describes an earlier milestone with services disabled and GLM as the observed
model. `docs/system-map.md` still calls the controller a small model. These should be
reconciled from live facts, not blindly updated from this report.

## Known debt and dangerous artifacts

- Job, message, approval, model-lease, trigger, and event records need versioned
  schemas and one explicit transition authority.
- Persistence queries scan files ad hoc; crash-safe compare-and-set/index boundaries
  are absent.
- Executor termination lacks checkpoint/requeue semantics. A killed process can
  leave a dead `running` record.
- Pausing while path/timer activation occurs can mark oneshot services failed because
  exit 75 is operationally meaningful but not represented cleanly to systemd.
- Live direct, role-local, and global inter-agent messaging is specified in
  `agent_notes/0003-control-plane-presence-and-live-messaging.md` but not implemented.
- Safe drain/reboot is specified in `agent_notes/0002-safe-powerdown.md` but remains
  manual.
- Model routing records decisions, but real admission control, leases, parallel
  durable workers, checkpointing, context swapping, and hot-swapping do not exist.
- “Innovator” and “Speculator” were requested conceptually but are not current role
  files. Preserve the distinction: Innovator proposes structural improvements but
  does not implement; Speculator records unconstrained observations/musings without
  turning them into implementation claims.
- Natural agent introductions should include age and role on first mention per
  message, for example `Wren (6m, Steward)`. This remains unimplemented.
- Fast first responses and significantly stranger generated names remain pending.
- The naming config still selects Qwen3.5-4B even though that model was removed from
  the intended resident set; this is policy drift.
- Existing class-based unit tests violate the eventual no-OOP end state.
- Hardware-in-the-loop, approval workflows, voice/attachment intake, containers,
  recovery manifests, and migration completeness remain future milestones.

The untracked `infrastructure/multi-model-server.json` must not be treated as a
working design. It claims time-sharing/hot-swapping that was not implemented, names
nonexistent paths/models, retains the unwanted 4B default, and binds to `0.0.0.0`,
contradicting the local-only boundary. Inspect provenance, then replace it with an
evidence-based design or remove it with appropriate authority. Do not normalize it
into documentation merely because a model wrote it.

`agent_notes/0001-inference-concurrency-upgrade.md` is also stale: it describes the
pre-carveout memory split and single-resident failure period. Consolidate its still-
valid motivation into current architecture rather than accumulating another layer.

The working tree already contained untracked/modified agent notes and infrastructure
material while this report was created. Future commits must select only owned files
and preserve unrelated work.

## Guidance for the next administrative builder

1. Begin every substantial turn by reading `/home/david/AGENTS.md`, the relevant
   repository notes, and current live state. Determine provenance before opening a
   model context or external channel.
2. Do not infer health from one layer. Trace a representative handshake end to end:
   trigger, durable command, role packet, model lease, execution, evidence,
   verification, outbox, Telegram delivery, and retained conversational context.
3. Prefer one foundational repair over five behavior-specific conditionals. The
   immediate architectural milestone is a versioned functional domain core with
   explicit transitions and ports for inference, execution, messaging, clock,
   scheduling, persistence, and host facts.
4. Build the inter-agent message bus and lifecycle/drain semantics together. A
   `wrap_up` request, receipt, checkpoint, timeout, escalation, and reboot recovery
   are one protocol, not separate shell scripts.
5. Add durable worker concurrency only behind measured model/memory admission.
   Preserve a responsive control lane, keep capable models resident long enough to
   amortize loads, and measure latency/throughput rather than inventing capacity.
6. Continue using models for semantic review, taste, and ambiguity. Keep state
   transitions, permissions, exact facts, deduplication, and destructive boundaries
   symbolic and validated. Neither half replaces the other.
7. Give observers authority to make only bounded, already-authorized repairs.
   Deduplicate findings and repair chains. A swarm repeatedly reporting the same
   defect is a malfunction, not vigilance.
8. Keep Telegram natural. Generated prose should arrive quickly, use ongoing
   context, name agents with age/role on first mention, and mention only useful
   outcomes. Raw IDs and JSON are evidence, not conversation.
9. Keep services local and narrow. Do not expose Lemonade, an executor, Vivado/JTAG,
   or a general shell to the public network. Do not move professional context through
   Telegram or personal project notes.
10. After every reboot or consequential configuration change, verify the live value
    and useful behavior. A file, tool success message, enabled unit, loaded process,
    or exit code is only one piece of evidence.
11. Maintain notes by consolidation. Correct stale reports, retain causal lessons,
    and remove obsolete implementation detail rather than appending endless lore.
12. Preserve the fun. Names, informality, and a sense of community are product
    requirements—but they must ride on truthful state and good engineering rather
    than concealing it.

## Condensed chronology

- **18:57:** filesystem-first repository, roles, intake, logs, pause, tests, and
  systemd templates.
- **19:31–19:41:** OpenCode executor, natural-language Telegram routing, private
  context, corrections, and dependency-aware results.
- **19:48–19:56:** control/worker separation, resource-aware recorded model choice,
  residency scheduling, operational status, and injected system identity.
- **19:59–20:09:** watchdog, randomized Steward task deck, agent-to-David relay,
  informal delivery, durable names, and model-generated naming.
- **20:12–20:30:** acknowledgment/presentation fixes, typed lifecycle projections,
  architecture assessment, Auditors/Refactorers, and binding engineering principles.
- **21:04–21:21:** truthful result language, independent verification, workspace
  provenance, and durable agent notes.
- **21:32–21:56:** registered pigen/style-reference workspaces, explicit model
  selection, scoped package installation, model-catalogue stewardship, and deletion
  of the brittle intent router in favor of the conversational control agent.
- **22:00–23:50:** four control sequences, visible replies after tool calls, Coder
  role, branch/PR workflow, responsive front-desk delegation, dual-model boot preload,
  and removal of disaster-fallback text from model history.
- **23:55–00:18:** safe-powerdown requirement, corrected unified-memory reporting,
  512 MiB UMA carveout, persistent 100 GiB TTM/GTT, controlled reboots, dual-model
  inference verification, and live-message/control-plane backlog.

## Primary evidence map

- Original intent: `/home/david/AGENT_ECOSYSTEM_VISION.md`
- Binding workspace policy: `/home/david/AGENTS.md`
- Repository history: `git log --reverse --stat`
- Current architecture debt: `docs/architecture-assessment.md`
- Operational contracts: `docs/operations.md`
- Data flow and safety map: `docs/system-map.md`
- Accepted decisions: `docs/decisions/`
- Roles and recurring judgment: `roles/`, `steward-tasks/`
- Runtime evidence: ignored `state/` and `logs/runs/`
- Next control/shutdown work: `agent_notes/0002-safe-powerdown.md` and
  `agent_notes/0003-control-plane-presence-and-live-messaging.md`

This ecosystem became useful by being corrected in public, against its own live
behavior. Future builders should keep that loop: observe, doubt, trace, repair the
boundary, verify independently, and leave the system easier to understand than it
was before.
