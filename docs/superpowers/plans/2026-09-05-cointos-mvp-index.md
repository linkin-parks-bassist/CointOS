# CointOS MVP Bring-up Implementation Plan

## Thesis and acceptance reconciliation — 2026-09-07

The MVP is concurrent/time-shared agents plus spontaneous generation, extensible
roles and two-way remote contact. This restores the original thesis, not new scope.
The canonical spec's model/resource and remote-contact sections are authoritative.
Retain the existing owners and task IDs; do not create a second scheduler or plan
suite. Parent acceptance is not inferred from a completed narrow worker packet.

| Requirement | Owning tasks | Required evidence |
| --- | --- | --- |
| Global `.cfg` slot/context policy and backend qualification | Q1, R2, R3 | One policy owner; native 262K target distinguished from actual allocation; fixed/shared KV accounting explicit |
| Concurrent inference and independent slot release | R3, R4 including R4-PRECISE | Two busy Qwen requests; one releases without awaiting the other |
| More agents than slots, fair time-sharing | R1, R3, R5, R6 | All contending agents progress with stable sessions and bounded resource ownership |
| Memory-contended model residency | R2, R3, R4, R5, R6; R7 pressure constraints | Eligible model drain/evict/load/resume while contingency survives; no fabricated pressure incident |
| Spontaneous work and extensible roles | A1–A3, A5 | Grounded work without a new human task; new role requires data/config, not scheduler branches |
| Unsolicited remote contact and reply continuation | C1–C3, B1–B4, A5 | Agent-originated Telegram message and a reply routed to original work after runner exit |

R2–R6 completion must include these resource obligations; R4's temporary
all-slots-idle release is not final concurrency acceptance. Before further resource
dispatch, Astra supplies bounded implementation-only packets matching these owning
contracts and real existing interfaces. This reconciliation is not a claim that
legacy code samples below already implement the revised interfaces. Contact's
superseded detailed C1–C3 examples remain quarantined until their packet revision.

## Cross-cutting extensibility requirement — David, 2026-09-07

Design the general mechanisms so new applications are principally role definitions,
data and access/schedule configuration, not new scheduler, executor, gateway or Coin
controllers. [Telegram tasks and reminders](../../product-ideas/telegram-tasks-and-reminders.md)
is the concrete design probe, not a bespoke subsystem or an additional MVP gate.
Its role content can follow bring-up; the enabling channels must be in the MVP
contracts from the start:

- A1–A3: real configurable role/tool authority, shared authorized read/write data,
  and bounded periodic/event-driven admission without application-specific branches.
- C1–C3: escalated Coin's commissioned tools/delegation, unsolicited messages from
  any role via the shared gateway-owned outbox, and Telegram replies correlated to
  their originating agent/work context. No fake inbound record for outbound events.
- B1–B4: durable agent communication and admitted continuation after a run ends;
  do not require an originating inference process to remain resident for a reply.
- G2/new-role acceptance: exercise this composition, not just role-name discovery.

Preserve existing approval, data-provenance and resource boundaries. Role prose is
not authority, and this requirement does not grant uncommissioned system access.
No new plugin framework, separate Reminder service or generic intra-process
message system is requested. Owners must carry this constraint into their concrete
packets; a running packet is not silently expanded.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans for the assigned task only. Read the design and swarm contract before the owning task.

**Status:** approved by David for implementation and activation on 2026-09-05;
deployment evidence is still pending. Merge and publication remain separately controlled.
**Coordinator:** Astra (Codex `/root`), 2026-09-05. Planning contributors: Flint and Cairn (GPT-5.6 Sol, medium), Sieve (local Qwen3.8 27B).

**Goal:** Bring up a useful, resource-managed, self-maintaining CointOS with protected Coin contact, seamless continuing work, live agent communication and approval-controlled self-improvement.

**Architecture:** One canonical contact route, one inference admission owner, durable task/run identities, and independent model-free survival controls. Functions over plain data compose these responsibilities; asynchronous transport appears only at real process/model/Telegram boundaries. Candidate changes cannot alter live imports before independent verification and David's exact Coin approval.

**Tech Stack:** existing Python standard library, Markdown role contexts, append-only JSONL records, Git worktrees, local model backends, OpenCode, systemd and Telegram.

**Spec:** [Complete MVP design](../specs/2026-09-05-cointos-mvp-design.md).

## Global constraints

- Coin stays available; no OOM; seamless handovers across dynamically chosen model/context allocations, including smaller destinations.
- Sole Survivor > Coin > active user-driven agent session > small health inspectors > large health inspectors > other roles. Scheduling rank never steals Coin's physical reserve. An admitted user-driven session prevents ordinary eviction, unload and context resizing; Coin may preempt it only when Coin's reserved capacity cannot otherwise be realized. This covers independently launched tools such as `lemonade opencode launch`, not only bare inference clients.
- Functions and plain data only; lowercase snake_case; no new class-based framework, database or configuration language.
- Personal CointOS scope only. Preserve dirty work, credentials, professional/customer boundaries and append-only runtime records.
- Qwen is the preferred qualified normal model; 4B is contingency capacity. Allocate context under global policy and concurrent demand. Managed task slicing/eviction follows R3–R6; the commissioning rule against interrupting a healthy implementation worker is not a universal prohibition on GPU time-sharing. Smoke still requires completion/checkpoint and observed process/request exit; resource guardians retain emergency authority.
- Worker kind follows the dispatcher: a hosted coordinator may run GPT-5.6 Sol medium workers; a local agent dispatches local workers only and never spawns or enqueues hosted-model workers. Owner/budget lines naming Sol name the hosted-coordinator scenario; under local dispatch the same task goes to the largest safely feasible qualified local model/context.
- Agent changes activate only after tests, independent verification and authenticated approval through Cointelprofessional. Installed emergency containment does not wait for a new approval.
- No installation, service change, credential access, Telegram transmission, publication or merge is authorized by writing this plan. S0 starts after David approves the execution scope.
- Read the [worker contract](2026-09-05-cointos-mvp-swarm.md) for budgets, test collection, handoffs and exclusive smoke ownership.

## What changed from the existing plans

The old suite had useful survival obligations but made broad closure and monitor work precede the first complete live proof. This suite replaces that execution order; it does not add an eighth competing route.

| Previous plan | Retained obligation / new owner | Removed from the bring-up gate |
| --- | --- | --- |
| Foundation stabilization, old 01 | R1-R7: actual resources, loaded-model truth, independent restrictive states and one recovery owner | Blanket cleanup of every old architectural defect |
| Survival lifecycle, old 02 | C3-C5: permanent gateway, protected installation, one poller, exact lifecycle semantics | Rebuilding already sound reducers just to follow the old checklist |
| Survival closure, old 02b | C4, H2-H3, P3-P4: progress, bounded effects, retained contact, observed rollback | Every broad audit finding closed before first use |
| Priority control, old 03 | C1-C3, R3-R6: canonical fast turn, optional durable task, reserved front, context continuity | Unconditional deep-controller hop, compatibility bridge as permanent architecture |
| Health escalation, old 04 | H1-H5: deterministic checks, incidents, bounded independent repair, prioritized small/large inspectors | Model verdict on every frequent heartbeat |
| Monitors/live acceptance, old 05 | C5, H4-H5, B4, P4, A5: staged live proofs | Per-subsystem model-monitor fleet before contact works |
| Old control index | This index | Its serial 25-task delivery order |

The prior design files remain labeled historical evidence. Their protocol obligations survive where stated in the new design; their superseded execution sequence is not a second authority. No code is being deleted during planning.

## Task catalogue and dependency graph

Dependencies below refer to accepted task outputs, not merely agent completion. A range in an owning plan includes all named tasks; this table expands the execution edges. There are 33 parent tasks; P3 is deliberately dispatched as P3a and P3b with separate review gates. Other checkbox steps are local pieces of their parent, not ceremonial standalone agents.

| Task | Independently checkable outcome | Depends on | Owning plan |
| --- | --- | --- | --- |
| S0 | Reviewed exact source snapshot, isolated writers and task ledger | David's execution approval | [Swarm](2026-09-05-cointos-mvp-swarm.md#s0--establish-the-exact-source-and-task-ledger) |
| Q1 | Standard parsing, whole-policy validation and last-known-good reload | S0 | [Swarm](2026-09-05-cointos-mvp-swarm.md#q1--standard-parsing-owned-validation-and-safe-configuration-reload) |
| R1 | Atomic worker registration, drain and exclusive smoke admission | Q1 | [Resources](2026-09-05-cointos-mvp-resources.md) |
| R2 | Measured model/context selection without resident bypass | R1 | Resources |
| R3 | Trusted role priority and actual sequence reservations | R2 | Resources |
| R4 | Every inference caller, including OpenCode, passes admitted boundary | R3 | Resources |
| R8 | David's independently launched user-driven agents hold explicit operator leases that ordinary management cannot evict | R4 | Resources |
| R5 | Enforced execution/output/attempt budgets and real partial handoff | R4, R8, A1 | Resources |
| R6 | Destination-sized durable continuation across contexts/models | R5 | Resources |
| R7 | Pressure prevention, independent gates and exclusive OOM recovery | R6 | Resources |
| A1 | Validated inherited task contracts and extensible role contexts | R1 | [Autonomy](2026-09-05-cointos-mvp-autonomy.md) |
| C1 | Canonical four-outcome contact lifecycle and durable task/conversation identity | A1 | [Contact](2026-09-05-cointos-mvp-contact.md) |
| C2 | Reserved fast Coin decision and factual status view | C1, R4 | Contact |
| C3 | Ordinary inbox worker and gateway-owned ordinary result egress | C2 | Contact |
| C4 | Offline full contact/lifecycle composition and safe cutover | C3, R7 | Contact |
| C5 | Early live Coin milestone and reusable smoke evidence driver | C4 | Contact |
| H1 | Configured model-free health observations and deadlines | R7, C3 | [Health](2026-09-05-cointos-mvp-health.md) |
| H2 | Incident deduplication and independent hard supervision | H1 | Health |
| H3 | Bounded recovery outside the failed ordinary scheduler | H2 | Health |
| H4 | Truthful Coin status and independently observed recovery | H3, C5 | Health |
| A2 | Bounded evidence reading and restricted discovery tools | A1, R5 | Autonomy |
| A3 | Scoped spontaneous selection under resource and priority policy | A2, R7, H1 | Autonomy |
| H5 | Small/large inspections at enforced priority and bounded cadence | A3, H4 | Health |
| P1 | Isolated candidates with exact independently observed verification | A1 | [Approval/release](2026-09-05-cointos-mvp-approval-release.md) |
| A4 | Grounded observations, proposals, patches and bounded follow-ups | A3, P1 | Autonomy |
| P2 | Authenticated digest-bound approval through Coin | P1, C3 | Approval/release |
| P3 | Immutable activation and independent rollback (P3a then P3b) | P2, R7, H1, C4 | Approval/release |
| P4 | Real approved activation, failed-canary rollback, protected rehearsal | P3, C5 | Approval/release |
| B1 | Durable bounded mailboxes projected from authoritative live runs | A1 | [Messaging](2026-09-05-cointos-mvp-messaging.md) |
| B2 | Real boundary delivery, tools and explicit acknowledgement | B1, R4 | Messaging |
| B3 | Authorized wrap-up/cancel/handoff integrated with execution | B2, R6 | Messaging |
| B4 | Live bidirectional/broadcast communication through continuation | B3, C5 | Messaging |
| A5 | Two complete useful autonomous cycles and restart continuity | A4, H5, P4, B4 | Autonomy |

The graph is an implementation ordering aid, not a claim that the running architecture is acyclic. Health/work, pressure/recovery, messaging/continuation and approval/activation are explicit runtime feedback loops.

## Dispatch and integration order

1. S0/Q1/R1 establish the trustworthy base and resource fence. Until R1 exists, coordinator observation supplies the same conservative no-overlap rule; do not run uncontrolled local jobs to build the controller.
2. After R1, parallelize resource selection, task contracts/roles, and bounded test/evidence work. After A1, P1/B1/C1 can progress independently in disjoint files. Publish accepted interface revisions before callers start.
3. Give C1-C5 and R2-R7 first integration priority. Bring protected ordinary Coin online at C5; do not wait for A5 or broad hardening. H1-H3, P1-P2, B1-B3 and A2-A3 can progress where their dependencies and file ownership permit.
4. Add incident recovery, live messages, inspectors, and approved release control. Integrate shared smoke-driver changes serially; H4, B4 and P4 may be ready together but their live tests never overlap.
5. A5 proves the combined autonomous MVP after its prerequisites. Observe actual work and two cycles; do not call a scheduler's zero exit proof of autonomy.

A hosted coordinator's Sol workers use GPT-5.6 Sol **medium**, generally 15-25-minute parent tasks; a local coordinator dispatches local workers only. Each owning plan supplies concrete interfaces, files, a failing example, named edge cases and acceptance. Local workers get small, simple, independently checkable substeps: role context, pure reducer case, parser fixture, deterministic digest check, scope/evidence extraction or a bounded caller migration. The coordinator keeps architecture, ambiguous decisions and final acceptance. A timed-out parent returns a useful partial; it is not license to enlarge its budget or start an unbounded child chain.

Only one integrator writes shared `cli.py`, `executor.py`, `models.py`, `inference.py`, gateway/guardian, timing validators, installers or service catalogues at a time. Disjoint helper/test files can be written in parallel. A worker awaiting integration may finish/read/review; it must not silently edit the live checkout. The swarm packet states exact source revision, files, signatures, tests, scope, model lease, budget and stopping condition.

## Shared interfaces and ownership

| Meaning | Single owner | Consumers |
| --- | --- | --- |
| Validated configuration snapshots | Q1 parsing/adoption helpers; each family validates its semantics | All policy consumers receive records, not raw strings |
| Task identity, authority and cumulative budget | A1 task contract + existing job transitions | Contact, autonomy, repair, messaging, executor |
| Physical model/context capacity | R2 measured routes, R3 leases, R4 sole backend request path, R8 user-driven operator leases | Every local model invocation, including David's independently launched agent tools/OpenCode |
| Work/smoke admission | R1 workload control | Hosted coordinator, local workers, inference, release and smoke |
| Runtime budget and continuing logical run | R5/R6 | H3 repair, B2/B3 messages, autonomous and requested jobs |
| Telegram receipt/delivery | Existing protected gateway + C1/C3 | P2 approval and all ordinary/reporting consumers |
| Health truth and repair | H1 observations, H2 incident reducer, H3 installed repair adapter | H4 status, H5 inspectors, R7 recovery, P3 probes |
| Live recipients and delivery | B1 projection/mailboxes, B2 runner adapter | Agent tools, Coin, coordinator, authorized controls |
| Verified/approved bytes and active release | P1 manifest, P2 approval, P3 activation | A4 contributions, gateway status, independent verifier |
| Smoke scenarios/evidence | C4 creates `ecosystem/mvp_smoke.py`, `scripts/mvp_smoke`, `tests/integration/test_mvp_flow.py`; C5 adds live contact | H4, B4, P4, A5 extend C4's same dispatch/evidence contract |

No second roster, hidden status database, scheduler-specific role switch, compatibility controller or generic intra-process message framework may substitute for these owners. Messaging is required at the genuinely asynchronous agent-run boundary.

## Acceptance gates

**Before each live test:** use the complete R1/swarm handshake. Close admission, request wrap-up, wait for terminal/checkpoint artifacts and observed worker/process/request exit, wait for relevant hosted writers, then acquire exclusive smoke. Unknown ownership/deadline is a blocker. Never force a real host OOM to test recovery.

**G0 — early useful contact (C5):** authenticated ordinary text receives one substantive response; a requested task has one identity; replay does not duplicate it; delayed decisions survive an earlier bounded degraded notice; RESTART/RESET retain contact and ordinary response recovers; exactly one poller; no OOM increment. Record actual latency and process/delivery evidence. Old live contact is replaced only after offline composition passes and the approved cutover has a tested rollback.

**G1 — independent survival and communication (H4/H5/B4/R7):** busy work does not occupy Coin's slot; synthetic pressure stops admissions and preserves continuation; incident repair produces a fresh independent recovery observation; small inspectors outrank large and both outrank ordinary work. Bidirectional live delivery, role/global announcement, explicit ACK, authorized wrap-up and context turnover work without a second big inference process. Model-free controls continue if inference/messages fail.

**G2 — complete autonomous MVP (P4/A5):** actual environment discovery produces a grounded contribution and useful independently verified work; a new role can be added without scheduler/executor changes; a task completes across smaller context/model turnover; Coin approval controls exact candidate activation; failed startup restores the prior observed healthy release; two autonomous cycles survive restart. Protected self-update is advertised only after its unchanged-release continuity/rollback rehearsal passes. Worker admission resumes only if every independent gate permits it.

G2 additionally requires every evidence row in the thesis reconciliation above.
Neither G0 early contact nor serial autonomous cycles close the complete MVP.
Use controlled capacity limits for the contention cases, not deliberate host OOM.

Run focused tests at each task and the integrated offline suite at milestone boundaries, not a full-repository audit after every small edit. Every evidence record names agent, exact source/release, scenario, time/boot, asserted observation, result and remaining blocker. Unit tests, offline composition and live evidence prove different claims. No deployed/stable/OOM-proof claim follows merely from this design.

## One deferred hardening queue

These are separate bounded follow-ups, not prerequisites which grow unnoticed. A finding is promoted into the MVP only when evidence shows failure of ordinary operation, contact, resource safety, durable continuation, authority isolation or rollback.

| ID | Bounded follow-up / owner profile | Concrete later acceptance |
| --- | --- | --- |
| D1 | Hostile spool/filesystem matrix / security reviewer | Assigned path/race cases cannot escape installed authority or publish partial records |
| D2 | Extended crash/reboot matrix / Sol + local test worker | Enumerated extra crash sites reconcile once without duplicate actions |
| D3 | Wider subsystem monitoring / health maintainer | One newly scoped subsystem has real freshness/evidence and a bounded repair path |
| D4 | Model qualification sweep / local benchmark worker | One candidate model/context set has measured RAM/GTT/KV/transient/latency evidence |
| D5 | Long soak and policy tuning / observer | Agreed duration/traffic mix produces retained latency, pressure and handover evidence |
| D6 | Voice/attachments or another workspace / separate product plan | David approves its provenance, authority and user-facing scope before implementation |
| D7 | Broad code/test/record-format cleanup / Gardener or Refactorer | One evidenced cleanup changes no required behavior; no whole-repository campaign |
| D8 | Release-manager self-upgrade / operator-led plan | Independent recovery owner survives an explicitly approved manager replacement |
| D9 | Backend/runner/environment decoupling / Astra contracts, bounded local migration workers | [CointOS-native interfaces](../../decisions/0017-backend-independent-cointos-interfaces.md) select adapters by configuration; core roles/scheduling/communication survive substitution without backend-specific edits. Post-MVP, not a new bringup gate; remote use requires separate approval. |

Unscheduled ideas remain grounded notes. Speculator is allowed to think without manufacturing executable backlog; Innovator proposals require a separate accepted implementation task. The MVP stops at G2 with a compact operational handoff, not at exhaustion of everything agents can imagine.
