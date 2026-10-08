---
status: green
revised_at: "2026-10-09T01:05:13+11:00"
---

# CointOS architecture

CointOS is an operating system for local agents. The primitive is an agent with a task, role and OpenCode conversation; model lanes are pre-emptible compute resources shared among more agents than can think simultaneously. The daemon owns scheduling and lifecycle truth. Everything else is an adapter, projection or cache.

The governing constraints are `how/to/keep/cointos/simple.md`; bounded work construction is `what/is/the/shape/of/cointos/work.md`; completion is `what/is/the/agent/completion/model.md`.

## Runtime representations

- **Task:** durable assignment state: identity, generated personal name, place, kind/role, branch/worktree, queue relation and the record version it was made for, dependencies, budget, reasoning effort, status, current run, session, receipt and retry/recovery metadata.
- **Retirement:** once a task settles and no run of it remains, `lifecycle.retire` removes its checkout and settles its branch: deleted when main contains it, archived under `refs/cointos/archive/<branch>` (commits stay reachable) when it is dead, and kept only while `cointos revise` could still restart it (a failed item whose record is blocked; `git.add_worktree` recreates the checkout from it). A checkout with uncommitted work, or of a project no longer configured, is kept for inspection. An integrator's release retires its accepted worker at once; each `reconcile` pass retires up to `recovery.retire_per_tick` other settled tasks, so leftovers drain without intervention. The outcome is recorded on the task as `retired`.
- **Run/agent:** one transient attempt to execute a task, represented by a systemd unit, OpenCode server/client, gateway identity and observed activity. A run never owns task outcome.
- **Conversation:** OpenCode's durable session messages. It survives ordinary run replacement.
- **Thought:** one model reply from rendered conversation to answer/tool calls. It may be suspended between bounded GPU steps.
- **Lane:** one loaded-model execution slot holding at most one known token state.
- **Snapshot:** a disposable cache of a known token prefix, in RAM or on disk. It is never the conversation record.
- **Receipt:** the sole semantic statement that a bounded assignment completed, blocked or returned, and a worker's whole account of its work. The lifecycle reducer validates and records it.
- **Queue record:** desired project work: what is asked (brief, dependencies, stage, effort, budget), its order, holds, a `version` counting revisions, and one terminal fact written once by the lifecycle, `done` (or `replaced_by` when replaced). Where it stands otherwise (queued, blocked, awaiting its manager, and the blocker text) is never stored: `queues.state` derives it from the tasks made for its current version, and `queues.view` serves records with it.

Stable identities and explicit relations connect these representations. Session IDs do not imply live processes; systemd units do not imply valid task ownership; snapshot files do not imply reachable conversations; Git ancestry does not imply acceptance.

## Processes

- **cointosd:** one Python daemon and the only ledger writer. It hosts the OpenAI-compatible gateway, control/dashboard API, scheduler, lane workers, spawner, lifecycle/recovery, model reconciliation, memory guard, journal and self-check.
- **Agent unit:** one transient `cointos-agent-<id>.service` containing a private OpenCode server and client in the task worktree. It carries explicit run/task identities and a memory cap.
- **Coin:** a separate Telegram service using the same gateway and control API. One front-model lane is reserved for it. Control lookup and front inference share the configured 12-second first-reply preparation budget; a slow lookup reduces the model's remaining allowance and exhaustion produces a fallback acknowledgement.
- **Lemonade/llama-server:** machine-level model service outside CointOS. `backend_llama.py` is the sole adapter for its literal API and token/tool representation.

The ledger is plain JSON guarded by one in-process lock and saved atomically. The API and CLI call domain functions; they do not implement parallel state machines. A request made from inside an agent run names its `caller` (task and run) and is checked once by `api.caller`/`api.running`.

## Pre-emptive scheduler

An agent is waiting, reading, reasoning, writing or running a tool. Reading/reasoning/writing require a lane; tools do not.

A thought advances in bounded steps: up to `read_chunk_tokens` while establishing context, then up to `chunk_tokens` while generating. Scheduling decisions occur between steps, so a running backend request is not torn in half.

At each boundary:

1. Higher-class work pre-empts lower-class work. Coin outranks user sessions, which outrank background agents. A generating holder is displaced before a reading holder when possible.
2. Equal-class cold reading is protected until its context is established; equals then share lanes by weighted slot lottery (`how/does/the/cointos/scheduler/share/a/lane/among/equal/agents.md`).
3. A tool call yields the lane. A bounded grace may retain it for a quick follow-up within the same unexpired slice; grace never extends the slice.
4. Placement prefers the agent's held lane, then a warm lane, then a free lane, then an eligible unreserved lane.

The backend verifies retained prompt state before each generation step by extending its prepared prefix with the pending real token. This creates the hybrid-model checkpoint needed for the following buffered step; an equal-length check after disk restoration would discard the cache. Prompt preparation streams progress so a lost prefix can be refused before an unbounded reread; generation returns the complete bounded token vector without per-step text parsing. Complete token counts and cached-state lengths are checked. The backend returns the sole authoritative known retained prefix; speculative draft state beyond the returned token history is marked cold without rejecting a valid reply. UTF-8 fragments are valid token history and are assembled before outward text streaming. Missing terminal events, backend error events, incomplete vectors and nonterminal steps with no tokens cannot become known lane state: the thought fails and the lane becomes cold.

Every thought belongs to its gateway request. The handler cancels it on every exit, including errors before response headers. It also polls for peer EOF while waiting for both JSON and streaming replies. A waiting thought is removed immediately; an in-flight step finishes before releasing its lane. HTTP callers timing out cannot leave detached high-priority work behind. A run's gateway key is revoked when the run is released, and a later request carrying it is refused (410) before any thought starts. During shutdown, a newly arriving request gets a retryable refusal.

Task reasoning effort (low, medium or xhigh) is pinned at creation by `schema.default_effort` (`what/are/the/cointos/roles.md` owns the defaults). The gateway caps each uninterrupted reasoning block at 256, 384 or 1,024 tokens and continues the same reply into answer/tool generation; whole replies remain bounded by `max_thought_tokens`. Coin carries the configured default effort on taskless gateway requests.

## Context and snapshot ownership

Token identity, not owner name, determines reuse. A lane is warm when its known tokens prefix the next rendered context. Snapshots are keyed by model plus token digest. Owners govern lifetime and shared-start eligibility but do not replace token identity.

A committed checkpoint is saved after context establishment and before generation. A suspended state may be saved when a thought yields mid-generation. Killing or losing a run abandons uncommitted thought output and resumes from durable conversation plus any compatible checkpoint.

A fresh managed prompt is ordered from what varies least between tasks to what varies most: OpenCode's instructions, tools and skill catalog (constant), the knowledge-tree startup (per project), role guidance (per role), then the assignment (per task). Hybrid-model state cannot be truncated, so a cached start is reusable only by prompts identical through its whole length; anything task-specific placed early makes every later token unshareable. `gateway.stable_environment` therefore removes OpenCode's per-task `<env>` lines (stated in the assignment instead) and the startup's `=== kt dict ===` line (it changes with every new leaf; agents call `kt_dict`) from the pinned system prefix. Agents run with `OPENCODE_DISABLE_CLAUDE_CODE_SKILLS`, so the skill catalog comes only from `~/.agents/skills`. A task's normalized system prefix and tool definitions (`gateway.stable_tools`) are pinned at its first request, so a conversation keeps the prefix it started with.

One conversation retains only useful prefix states; divergent task snapshots are forgotten. On a fresh managed launch, `prompts.shared_launch_tiers` names three semantic boundaries in the user message (its start, the end of `_base.md`, the end of the role guidance), and gateway rendering derives each exact token boundary from the model chat template; boundaries shorter than `scheduler.shared_prefix_tokens` are dropped. While reading, the lane stops exactly at each boundary that has no snapshot yet and saves it under the shared owner, even when no peer context is concurrently alive. Later sequential tasks restore the longest matching tier through ordinary token-digest matching: any task of the project reuses the system tier, any role the `_base.md` tier, and the same role its role tier. Opportunistic comparison can still discover longer shared starts between live contexts, saved the same way. Coin/user shared ownership and task reachability are explicit lifetime queries. Startup and each lifecycle reconciliation discard caches of unreachable conversations, including workers accepted after their own run has ended. A terminal task with a surviving run still retains its cache until that run releases.

Save admission uses the nearest measured same-model context at least as large, without scaling its fixed state overhead downward. Above the measured range it scales the largest sample upward and never predicts less than a smaller measured file. Estimates round upward; actual saves are measured and reconciled. An unseen model's first save remains unestimated.

RAM snapshots are bounded by `memory.snapshots_gb` (40) and spill to the disk tier (`memory.disk_snapshots_gb`, 300). A full tier discards shared launch starts first (rebuilt by one short read), least recently run first, and a conversation's own state only after none remain; evictions log `snapshot evicted`. A save that does not fit while spills are in flight is declined (`what/is/broken.md`). Transfers stay charged until complete, and discarding a moving snapshot waits for its transfer. The ledger owns each tier's files: startup and each daemon tick remove abandoned files and interrupted copies against those owners. A cache miss or eviction causes rereading, never semantic loss. Full shutdown attempts context saving, RAM-to-disk spill and ledger saving independently.

## Task and receipt lifecycle

`tasks.create` is the sole constructor. `schema.KINDS` describes each kind's role, rank, scope, queue relation, allowed receipt and landing behavior. `lifecycle.py` alone writes task status, run ownership, receipts, acceptance, a record's `done`, retry state and agent removal. The spawner admits runnable waiting tasks before creating new work, ordering those retained assignments by rank and creation time. Only when none are waiting does it compare new queue, integration, tree-maintenance and periodic candidates by rank. Project priority therefore does not let a new recovery manager displace a retained waiting worker; running-task admission is separate from GPU thought pre-emption.

A run becomes assignment-engaged on its first admitted gateway thought. Exit before engagement is an infrastructure launch failure: the attempt is refunded, consecutive launch failures are separately bounded, and repeated failure places a durable admission hold plus an alert. After engagement, an unreceipted exit follows bounded assignment recovery.

Receipts are run-owned and idempotent. `cointos finish` handles ordinary roles; verified land/incorporate/return handles integrators. Evidence rules are data-driven: clean branch, production-free test packets, checked packets, merged planning work or system summary as appropriate, and a refusal states the evidence it found. Delivery acknowledgement is the process boundary that retires the exact run after the receipt has been printed/flushed.

Ordinary death retains the OpenCode session. Directed `cointos kill` stops only the run, refunds its attempt and adds a durable task hold; only `cointos resume` releases it. Budget exhaustion ends only the run: any task continues in up to `recovery.fresh_retries` fresh sessions from its branch/files and a compact evidence packet. A failed worker item automatically receives one bounded manager pass; an unresolved or exhausted manager escalates for intervention. Hidden reasoning is never copied.

A record whose current worker item failed (including a test-contract item `spawner.dispatch` refused before any run) awaits one manager recovery pass, which receives the assignment, worker receipt evidence and final failure (`queues.blocker`). Report words do not control admission. Recovery managers receive their own configured reasoning and default generation limits rather than inheriting worker record overrides; explicit recovery-task overrides still win. They may revise the brief (a new record version, queued afresh) or replace the work (`queues.replace`, which repoints dependents and marks it `replaced_by`, as the user's `cointos supersede` does); their own blocked or exhausted outcome blocks the record without further automatic recovery. Manager admission does not depend on the failed assignment's prerequisite readiness, but explicit holds and project enablement still apply. Brief revision replaces the assignment and dependencies while preserving omitted construction stage and reasoning metadata; named budget limits merge with existing limits. `queues.revise` owns this candidate validation and metadata preservation; `lifecycle.revise` restarts the task with its branch intact. An existing waiting integrator is eligible only while its worker is in review and unheld; a changed brief refreshes that waiting integrator's assignment and conversation while preserving its branch/worktree and any explicit admission hold. `how/to/revise/queued/cointos/work.md` owns the control procedure. A queue item cannot be made done by deleting a leaf, moving a branch or ending a process. Controls name tasks and reach queue records through the task's `record` link (`api.queue_key`). `cointos cancel` withdraws unaccepted records for good through `lifecycle.cancel`, releasing their runs and integration/decomposition tasks, marking them failed with `cancelled`, deleting the records and retiring the branches, and refusing while uncancelled live work depends on them; a live task without a record (garden, audit, scout, operator) just ends through `lifecycle.cancel_task`. `queues.move` reorders a project's live records; the spawner re-ranks waiting tasks from record position every pass. A fresh session of an assignment is told which records that assignment already proposed (`proposed_by`). Agent-proposed worker briefs, and managers' revisions of them, must carry a `Summary:` line of `summary_words` plain words, stored as the record's `summary`. The daemon republishes the runtime queue leaves whenever their text changes.

History cleanup is a reachability operation over the same task/queue relations. `queues.history_frontier` retains unfinished queue work and its transitive prerequisites/replacements. The API protects all active tasks and their worker/record relations, even without live runs, then retains terminal tasks associated with that queue frontier. Only unreferenced terminal records and their disposable cache ownership are forgotten. `how/to/clear/cointos/task/history.md` owns the operator-facing procedure.

## Work construction and landing

Managers advance a small frontier and queue explicit dependency edges. Workers execute one skeleton, test-contract, implementation or integration stage. Integrators own review, current project knowledge and the exact landing boundary. Gardeners and tree auditors maintain bounded knowledge scope; stewards/test auditors inspect system-wide evidence and may propose at most one managerial correction. Any non-worker run may start an operator for work the pipeline has no route for.

`contracts.stage_history` checks task commits after the pinned base, excluding main's commits. Test writers cannot edit production; implementers cannot edit tests/harnesses. Importing main is legal; reverted forbidden edits and invented merge resolutions are not. The base bounds history, not the diff.

Every landing requires a complete receipt. Blocked work reaches review for assessment only. `landing.py` rejects production changes in test-packet candidates and runs the full suite in memory-capped units. Run ownership, receipt commit and refs are rechecked before main moves. Concurrent-main conflicts are resolved/staged and resubmitted with `cointos land`; planning/maintenance keeps `cointos merge`. Caused test failures return the item. Interrupted landings settle only from their persisted landing record. `incorporate` requires pinned main/worker commits, identical changed production files and packet tests already on main.

## Memory and recovery

The workstation's unified RAM is one pool. `memory.py` derives headroom from `MemAvailable`, configured workstation reserve and the inference-slice allowance. Admission estimates model, agent and snapshot cost; agent and landing units also have hard memory caps.

Snapshots give way first. Sustained negative headroom stops background agents uncharged, then unloads the work model. Sustained PSI distress shortcuts to the protective top rung. Recovery descends only after configured calm time. Swap use is diagnostic, not itself a stop threshold.

Self-check covers idle lanes with work waiting, priority pre-emption, starvation, agent silence, repeated thoughts, stalled thoughts, stray agent processes, dead dependencies, memory bounds and journal writability. An agent with no thought and no OpenCode event is silent after `checks.agent_silent_seconds` (600), or `checks.tool_silent_seconds` (660, above OpenCode's 10-minute tool cap) while running tools after a reply that ended in tool calls, and is stopped and resumed in its session. A held thought must advance context preparation or generate within `checks.thought_stalled_seconds` (60); waiting for a lane does not count. Successful bounded rereading after displacement or cache loss refreshes progress even below an earlier read frontier; restoring a snapshot or recording a failed step does not. The daemon cancels stalled thoughts at the next safe step boundary.

Checks are current observations; `check_incidents` owns notification lifetime. A new failing check produces one Coin alert. Brief green observations do not rearm it: it must remain clear for `checks.alert_recovery_seconds` (30). Incident state survives daemon replacement, while CLI/dashboard details continue updating each tick.

## Replacement hierarchy

1. `scheduler.slice_seconds` and `scheduler.chunk_tokens` reload live.
2. `cointos restart` drains spawn admission while existing conversations/receipts finish, then replaces only cointosd and adopts still-active agent units.
3. `scripts/install --live` copies prompts, dashboard and CLI in place without touching the daemon when nothing it runs changed; otherwise it replaces cointosd at once: shutdown saves each lane's state, cut replies are retried by OpenCode and resume from it.
4. Full paused installation, halt/up or reboot is reserved for gateway/model-process identity, model shape or other incompatible changes.

Adoption requires both persisted identity and an active systemd unit. Unknown units are stopped; missing units return their tasks to waiting uncharged. A resumed session receives the smallest OpenCode-supported handoff; adoption injects nothing.

## Source ownership

- `config.py`, `schema.py`, `state.py`: configuration/project registry, task vocabulary, ledger/lock/journal/alerts.
- `tasks.py`, `names.py`, `queues.py`, `lifecycle.py`, `recovery.py`, `messages.py`, `trees.py`: durable work, names, queue records and their derived state, reducer, bounded recovery, message delivery and the gardener's knowledge-tree health/selection.
- `spawner.py`, `runs.py`, `keys.py`: admission, transient execution and gateway identity.
- `scheduler.py`, `lanes.py`, `snapshots.py`, `memory.py`, `daemon.py`: GPU scheduling, context execution/cache, resource measurement and orchestration.
- `landing.py`, `contracts.py`, `git.py`: exact candidate acceptance and repository mutation.
- `gateway.py`, `backend_llama.py`, `opencode.py`, `prompts.py`, `client.py`, `kt.py`, `kt_mcp.py`, `mcp.py`, `viewers.py`: external representation fingertips.
- `api.py`, `cli.py`, `coin.py`, `settings.py`, `projects.py`, `checks.py`, `journal.py`, `metrics.py`, `web/dashboard.html`: control, presentation and diagnostics.

The source repository and installed runtime are distinct. `scripts/install` owns full/live deployment; isolated dashboard or Coin-only copies follow `how/to/install/cointos.md`; `scripts/upgrade-ledger` is the one migration boundary, run at every installation while the daemon is stopped, and the runtime carries no compatibility branches. Installed project enrollment is preserved separately from source defaults. Coin's imported code and startup settings survive a live installation; when changed they require a separate quiet Coin-only refresh. New repository creation commits orientation, spec, plan and known-defects leaves before enrollment, and inherits the configured `project_defaults.test_policy` unless explicitly overridden. Imported repositories require a profile before worker landing. Missing optional policy lists mean empty. Registry mutation writes its sorted candidate before replacing the shared in-memory list; a persistence failure leaves both unchanged. `how/to/manage/the/cointos/project/registry.md` owns enrollment and its control boundaries. Runtime queue leaves are daemon projections and are never edited by agents.

## Observability and current boundary

The CLI, dashboard, run directories, systemd journals and bounded event journal are projections/evidence over the same owners. They do not decide lifecycle state. `what/is/the/live/acceptance/evidence/for/cointos.md` records what has actually worked live; `what/is/broken.md` records unresolved boundaries; `what/is/the/plan.md` is the only remaining-work frontier.
