---
status: green
revised_at: "2026-10-01T22:24:34+10:00"
---

# CointOS architecture

CointOS is an operating system for local agents. The primitive is an agent with a task, role and OpenCode conversation; model lanes are pre-emptible compute resources shared among more agents than can think simultaneously. The daemon owns scheduling and lifecycle truth. Everything else is an adapter, projection or cache.

The governing constraints are `how/to/keep/cointos/simple.md`; bounded work construction is `what/is/the/shape/of/cointos/work.md`; completion is `what/is/the/agent/completion/model.md`.

## Runtime representations

- **Task:** durable assignment state: identity, place, kind/role, branch/worktree, queue relation, dependencies, budget, reasoning effort, status, current run, session, receipt and retry/recovery metadata.
- **Retirement:** once a task settles (done or failed) and no run of it remains, `lifecycle.retire` removes its checkout and settles its branch: deleted when main contains it, archived under `refs/cointos/archive/<branch>` (commits stay reachable) when it is dead, and kept only while `cointos revise` could still restart it (a failed item whose queue record is live, unaccepted and not superseded; `git.add_worktree` recreates the checkout from it). A checkout with uncommitted work, or of a project no longer configured, is kept for inspection. An integrator's release retires its accepted worker at once; each `reconcile` pass retires up to `RETIRE_PER_TICK` (4) other settled tasks, so leftovers drain without intervention. The outcome is recorded on the task as `retired`.
- **Run/agent:** one transient attempt to execute a task, represented by a systemd unit, OpenCode server/client, gateway identity and observed activity. A run never owns task outcome.
- **Conversation:** OpenCode's durable session messages. It survives ordinary run replacement.
- **Thought:** one model reply from rendered conversation to answer/tool calls. It may be suspended between bounded GPU steps.
- **Lane:** one loaded-model execution slot holding at most one known token state.
- **Snapshot:** a disposable cache of a known token prefix, in RAM or on disk. It is never the conversation record.
- **Receipt:** the sole semantic statement that a bounded assignment completed, blocked or returned. The lifecycle reducer validates and records it.
- **Queue record:** desired project work. Its visible state is projected from task/receipt truth rather than maintained as a second lifecycle.

Stable identities and explicit relations connect these representations. Session IDs do not imply live processes; systemd units do not imply valid task ownership; snapshot files do not imply reachable conversations; Git ancestry does not imply acceptance.

## Processes

- **cointosd:** one Python daemon and the only ledger writer. It hosts the OpenAI-compatible gateway, control/dashboard API, scheduler, lane workers, spawner, lifecycle/recovery, model reconciliation, memory guard, journal and self-check.
- **Agent unit:** one transient `cointos-agent-<id>.service` containing a private OpenCode server and client in the task worktree. It carries explicit run/task identities and a memory cap.
- **Coin:** a separate Telegram service using the same gateway and control API. One front-model lane is reserved for it.
- **Lemonade/llama-server:** machine-level model service outside CointOS. `backend_llama.py` is the sole adapter for its literal API and token/tool representation.

The ledger is plain JSON guarded by one in-process lock and saved atomically. cointosd is the only writer. The API and CLI call domain functions; they do not implement parallel state machines.

## Pre-emptive scheduler

An agent is waiting, reading, reasoning, writing or running a tool. Reading/reasoning/writing require a lane; tools do not.

A thought advances in bounded steps: up to `read_chunk_tokens` while establishing context, then up to `chunk_tokens` while generating. Scheduling decisions occur between steps, so a running backend request is not torn in half.

At each boundary:

1. Higher-class work pre-empts lower-class work. Coin outranks user sessions, which outrank background agents. A generating holder is displaced before a reading holder when possible.
2. Equal-class cold reading is protected until its context is established. After that, a generating turn whose `slice_seconds` expired yields to the longest-waiting equal.
3. A tool call yields the lane. A bounded grace may retain it for a quick follow-up within the same unexpired slice; grace never extends the slice.
4. Placement prefers the agent's held lane, then a warm lane, then a free lane, then an eligible unreserved lane.

The backend verifies retained prompt state before each generation step. Prompt preparation streams progress so a lost prefix can be refused before an unbounded reread; generation returns the complete bounded token vector without per-step text parsing. Complete token counts and cached-state lengths are checked. The backend returns the sole authoritative known retained prefix; speculative draft state beyond the returned token history is marked cold without rejecting a valid reply. UTF-8 fragments are valid token history and are assembled before outward text streaming. Missing terminal events, backend error events, incomplete vectors and nonterminal steps with no tokens cannot become known lane state: the thought fails and the lane becomes cold.

Every thought belongs to its gateway request. The handler cancels it on every exit, including errors before response headers. It also polls for peer EOF while waiting for both JSON and streaming replies. A waiting thought is removed immediately; an in-flight step finishes before releasing its lane. HTTP callers timing out cannot leave detached high-priority work behind.

Task reasoning effort is low, medium or xhigh, pinned on the task at creation by `schema.default_effort`: an explicit override, else the test-contract entry for test-contract workers, else the task role's entry in `reasoning` config (managers are medium), else the low default. The gateway caps each uninterrupted reasoning block at 256, 384 or 1,024 tokens and continues the same reply into answer/tool generation. Whole replies remain bounded by `max_thought_tokens`.

## Context and snapshot ownership

Token identity, not owner name, determines reuse. A lane is warm when its known tokens prefix the next rendered context. Snapshots are keyed by model plus token digest. Owners govern lifetime and shared-start eligibility but do not replace token identity.

A committed checkpoint is saved after context establishment and before generation. A suspended state may be saved when a thought yields mid-generation. Killing or losing a run abandons uncommitted thought output and resumes from durable conversation plus any compatible checkpoint.

One conversation retains only useful prefix states; divergent task snapshots are forgotten. On a fresh managed launch, prompt construction identifies the task-independent role boundary while gateway rendering derives its exact token boundary from the model chat template. The lane saves that prefix under the shared owner even when no peer context is concurrently alive, so later sequential tasks of the same role can restore it through ordinary token-digest matching. Opportunistic comparison can still discover longer shared starts between live contexts. Coin/user shared ownership and task reachability are explicit lifetime queries.

RAM snapshots are bounded by `memory.snapshots_gb` and spill to the bounded disk tier by reachability and recency. Transfers remain charged until completion. A cache miss or eviction causes rereading, never semantic loss. Full shutdown attempts context saving, RAM-to-disk spill and ledger saving independently.

## Task and receipt lifecycle

`tasks.create` is the sole constructor. `schema.KINDS` describes each kind's role, rank, scope, queue relation, allowed receipt and landing behavior. `lifecycle.py` alone writes task status, run ownership, receipts, acceptance, retry state and agent removal.

A run becomes assignment-engaged on its first admitted gateway thought. Exit before engagement is an infrastructure launch failure: the attempt is refunded, consecutive launch failures are separately bounded, and repeated failure places a durable admission hold plus an alert. After engagement, an unreceipted exit follows bounded assignment recovery.

Receipts are run-owned and idempotent. `cointos finish` handles ordinary roles; verified land/incorporate/return handles integrators. Evidence rules are data-driven: clean branch, report state, merged planning work or system summary as appropriate. Delivery acknowledgement is the process boundary that retires the exact run after the receipt has been printed/flushed.

Ordinary death retains the OpenCode session. Directed `cointos kill` stops only the run, refunds its attempt and adds a durable task hold; only `cointos resume` releases it. Budget exhaustion may create a bounded fresh session with branch/files and a compact evidence packet, then fails the assignment. A failed worker item automatically receives one bounded manager pass; an unresolved or exhausted manager escalates for intervention. Hidden reasoning is never copied.

Queue state is derived from accepted/failed task state on every reconciliation. Failed worker items carry the assignment, worker receipt evidence and final failure into one manager recovery pass through the existing decomposition route. Report words do not control admission. Recovery managers may correct the brief or replace the work; their own blocked or exhausted outcome disables further automatic recovery for that unchanged failure. Manager admission does not depend on the failed assignment's prerequisite readiness, but explicit holds and project enablement still apply. Completing a manager revision does not accept the failed work or settle its revised queue record. A queue item cannot be made done by deleting a leaf, moving a branch or ending a process.

## Work construction and landing

Managers advance a small frontier and queue explicit dependency edges. Workers execute one skeleton, test-contract, implementation or integration stage. Integrators own review, current project knowledge and the exact landing boundary. Gardeners and tree auditors maintain bounded knowledge scope; stewards/test auditors inspect system-wide evidence and may propose at most one managerial correction.

Implementation candidates cannot alter protected tests/harnesses. `contracts.py` selects accepted checks from the owning manifest, including same-file Python dependency propagation, and `landing.py` runs them on the exact clean candidate in a transient memory-capped unit before main moves. Run ownership, worker receipt commit and refs are checked again at mutation time. A failed gate returns the item; an interrupted post-fast-forward landing is settled only from its persisted landing record. `incorporate` handles already-present implementation only with pinned main/worker commits and the same structural/contract checks.

## Memory and recovery

The workstation's unified RAM is one pool. `memory.py` derives headroom from `MemAvailable`, configured workstation reserve and the inference-slice allowance. Admission estimates model, agent and snapshot cost; agent and landing units also have hard memory caps.

Snapshots give way first. Sustained negative headroom stops background agents uncharged, then unloads the work model. Sustained PSI distress shortcuts to the protective top rung. Recovery descends only after configured calm time. Swap use is diagnostic, not itself a stop threshold.

Self-check covers idle lanes with work waiting, priority pre-emption, starvation, agent silence, repeated thoughts, stalled thoughts, stray agent processes, dead dependencies, memory bounds and journal writability. A held thought must advance context preparation or generate within `checks.thought_stalled_seconds` (60); Coin and user thoughts share this rule with managed agents. Waiting for a lane does not count. Successful bounded rereading after displacement or cache loss refreshes progress even below an earlier read frontier; restoring a snapshot or recording a failed step does not. The daemon cancels stalled thoughts at the next safe step boundary.

Checks are current observations; `check_incidents` owns notification lifetime. A new failing check produces one Coin alert. Brief green observations do not rearm it: it must remain clear for `checks.alert_recovery_seconds` (30). Incident state survives daemon replacement, while CLI/dashboard details continue updating each tick. This prevents changing wait durations and read/generate transitions from flooding Telegram.

## Replacement hierarchy

1. `scheduler.slice_seconds` and `scheduler.chunk_tokens` reload live.
2. `cointos restart` drains spawn admission while existing conversations/receipts finish, then replaces only cointosd and adopts still-active agent units.
3. `scripts/install --live` uses deployment quiescence: admitted work reaches a request boundary, new thoughts are retryably blocked, compatible source/config is copied, and cointosd is replaced around surviving processes.
4. Full paused installation, halt/up or reboot is reserved for gateway/model-process identity, model shape or other incompatible changes.

Adoption requires both persisted identity and an active systemd unit. Unknown units are stopped; missing units return their tasks to waiting uncharged. A resumed session receives the smallest OpenCode-supported handoff; adoption injects nothing.

## Source ownership

- `config.py`, `schema.py`, `state.py`: configuration/project registry, task vocabulary, ledger/lock/journal/alerts.
- `tasks.py`, `queues.py`, `lifecycle.py`, `recovery.py`: durable work, projections, reducer and bounded recovery.
- `spawner.py`, `runs.py`, `keys.py`: admission, transient execution and gateway identity.
- `scheduler.py`, `lanes.py`, `snapshots.py`, `memory.py`, `daemon.py`: GPU scheduling, context execution/cache, resource measurement and orchestration.
- `landing.py`, `contracts.py`, `git.py`: exact candidate acceptance and repository mutation.
- `gateway.py`, `backend_llama.py`, `opencode.py`, `prompts.py`, `client.py`, `kt.py`, `kt_mcp.py`, `viewers.py`: external representation fingertips.
- `api.py`, `cli.py`, `coin.py`, `settings.py`, `projects.py`, `checks.py`, `journal.py`, `web/dashboard.html`: control, presentation and diagnostics.

The source repository and installed runtime are distinct. `scripts/install` is their only deployment route; `scripts/upgrade-ledger` is the one-shot schema migration boundary. Installed project enrollment is preserved separately from source defaults. Runtime queue leaves are daemon projections and are never edited by agents.

## Observability and current boundary

The CLI, dashboard, run directories, systemd journals and bounded event journal are projections/evidence over the same owners. They do not decide lifecycle state. `what/is/the/live/acceptance/evidence/for/cointos.md` records what has actually worked live; `what/is/broken.md` records unresolved boundaries; `what/is/the/plan.md` is the only remaining-work frontier.
