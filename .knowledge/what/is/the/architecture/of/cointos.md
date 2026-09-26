---
status: "green"
revised_at: "2026-09-27T00:59:56+10:00"
---

**CointOS is an operating system for agents.** The primitive is the agent. Model lanes are resources: a pre-emptive scheduler time-shares them among agents, the way an operating system time-shares CPUs among processes. Details not fixed here are for the builder to decide, within `how/to/keep/cointos/simple.md`.

## Concepts

- **Agent:** a worker with a task, a role and a conversation (an OpenCode session), living until its run ends. Agents are what CointOS is about; everything else serves them.
- **The four Rs:** an agent is always *Reading* (the model is reading its context into a lane), *Reasoning* (the model is thinking), *Writing* (the model is writing its message or tool calls), or *Running* (its tools run: commands, file edits, knowledge-tree lookups); or else *waiting* for a lane. Reading, reasoning and writing make up a thought, which needs a lane; a running agent needs none.
- **Thought:** one span of thinking, from the agent's conversation to the point where the model hands back control with a message or tool calls. A thought can be interrupted and resumed any number of times.
- **Context:** the agent's conversation as the model holds it: a token sequence and the lane state computed from it. A context is *resident* on a lane, *saved* as a snapshot, or *cold* (only its tokens are known, and the model must read them again). **A context is identified by its tokens**, not by who owns it: a lane is *warm* for a thought when the tokens its state holds begin the thought's tokens, and a snapshot is found by a digest of the tokens it holds. So concurrent conversations of one owner never collide, and an agent resuming a task's session (even after a daemon restart) finds that task's context. Owners (a task, Coin, David) govern snapshot lifetime, divergence cleanup and shared-start eligibility, but do not replace token identity.
- **Lane:** one execution slot of a loaded model, holding at most one resident context. A model has a fixed number of lanes, set when it is launched.
- **Class:** an agent's priority, highest first: Coin, David's own sessions, background work.

## The scheduler is pre-emptive

- **Any lane can be taken back at any moment.** The scheduler decides which thinking agents hold lanes. It never waits for an agent to finish a thought.
- **A switch** takes a lane from one agent and gives it to another: the outgoing context is saved if still useful and memory permits, and the incoming one is restored if a usable snapshot exists, otherwise read from its tokens. The outgoing agent's thought is suspended exactly where it stopped and loses nothing.
- **Granularity:** a thought advances in steps, each running to its own end: a step reads up to `read_chunk_tokens` of a context the lane does not hold yet, or, once it is read, generates up to `chunk_tokens`. A switch happens between steps. So a lane always holds exactly known tokens, and an agent waits at most one step plus one switch for a lane it is owed. (Nothing is ever cut mid-step: llama-server notices a dropped request only when it next writes, which during a long read can be minutes later.)
- **Reading and generating.** A thought is *reading* while no lane holds its context yet (a truly cold first turn, or a context whose snapshot was lost), and *generating* once the model is writing. The agent's state shows which.
- **Turns.** An agent's turn on a lane runs from when it gets the lane until it gives it up, across consecutive thoughts.
- **Policy**, applied at every step boundary, whenever an agent starts thinking, and every tick (a slice runs out between events):
  1. A thinking agent of a higher class takes a lane from a lower class at once. It takes a lane whose holder is generating before one whose holder is reading, so a cold read is displaced only when there is no other lane.
  2. Among equals, a reading holder keeps its lane until its context is read. A generating holder whose turn clock has reached `slice_seconds` gives the lane to the equal that has waited longest. The slice clock starts when the read is done and continues through quick tool-call grace, so a cold agent is never pre-empted the moment it finishes reading.
  3. A tool call yields the lane, like a system call: when a thought ends, the lane stays held for its agent for `yield_grace_seconds`, and a next thought arriving within that grace continues the same turn, so a burst of quick tool calls is not switched out. Only a higher class may take a held lane.
  4. A thought is placed on the cheapest lane open to it: the one it holds or that is held for it, then a warm one, then a free one, then an unreserved one.
- **Contexts stay resident when nothing needs the lane.** When a thought ends, the agent's context stays on its lane. A switch need not save/restore it while it stays resident. Checkpoint saves at the end of a cold read, shared-start saves and graceful-stop saves are separate from switching.
- **Shared starts.** Agents of one role share a long common start (tools, system prompt, role). When a context being read shares at least `shared_prefix_tokens` with a live or resident context of a different owner on the same model, the read stops exactly there once and saves that start as a shared snapshot. Later contexts can restore it through the ordinary longest-snapshot match while it remains available and restoration fits in headroom.
- **Checkpoints and suspended states.** When a thought's context has been read, before it generates, the lane holds the committed prompt except its final token (the hybrid model needs that token to extend the state); a *checkpoint* save is attempted if memory permits. A thought stopped part way (switched out, or on a graceful stop) is saved as a *suspended* state. A run that dies or is stopped mid-thought abandons that thought; its conversation goes on from the checkpoint, with any usable checkpoint avoiding a full reread. If the checkpoint could not be saved or was evicted, the committed conversation must be read again.
- **One line of snapshots per conversation.** A checkpoint supersedes its conversation's older snapshots; a suspended state supersedes only older suspended ones, so the checkpoint outlives an abandoned thought. A task's conversation is one line of history, so when its next thought starts, the task's snapshots that do not begin the new context are forgotten. Coin's and David's snapshots, which may belong to several conversations at once, leave by least recent use.
- **Reservation:** one lane of the front-desk model serves only Coin, so background work cannot occupy that lane. Model availability, Coin request contention and Telegram latency still bound visible response time.
- **Bound:** a thought generates at most `max_thought_tokens`.

## Backend layer

The core speaks only the concepts above. One backend module translates them for a particular model server, so no llama-server or Lemonade detail appears outside it. The interface:

- **launch(model, shape)** and **kill(model)**; **models()** reports what is loaded, in which shape, with how many lanes.
- **render(model, conversation)** turns a conversation (messages and tools) into context tokens.
- **prefill(lane, tokens)** makes the lane hold exactly `tokens`, reading only what it does not hold yet.
- **think(lane, tokens, max_new)** extends a context on a lane, streaming the new tokens, and stops at the end of the thought or after `max_new`; the lane then holds every token but the last one received.
- **save(lane, name)**, **restore(lane, name)** and **forget(name)** move contexts between lanes and snapshots.
- **read(model, reader, tokens, final)** turns a thought's tokens into what the agent sees: reasoning, message text and tool calls.

The first backend, for Lemonade-managed llama-server (`how/does/lemonade/serve/models.md`), uses raw token completions with `id_slot`, slot save and restore to a snapshot directory in `/dev/shm`, and the model's own chat template and tool-call format.

## Processes

- **`cointosd`**: one long-running daemon (Python standard library, one systemd user unit), the only writer of the ledger. It contains:
  - **Gateway:** the OpenAI-compatible endpoint on loopback through which every agent thinks (OpenCode agents, Coin, David's own sessions). A chat request starts a thought for its agent; the reply streams back as the thought advances, however often it is suspended.
  - **Scheduler** (above), **spawner**, **guard**, **self-check**, and a small loopback **API and dashboard**.
- **Agents:** OpenCode processes the daemon starts, each in its own git worktree with its own gateway key.
- **Coin:** a separate small service (Telegram in, replies out), so it can report on and restart the daemon. It thinks through the gateway and uses the daemon's API and the kt MCP server.

## Config and ledger

- `config/cointos.json` is the intended sole owner of operational numbers, including models and their shapes, reservations, classes, `chunk_tokens`, `slice_seconds`, bounds, physical limits, spawner limits, intervals and ports. The current implementation still has constants outside it; see the gap in `what/is/the/state.md`.
- `state/cointos.json` is the ledger, written atomically by the daemon only, holding the ledger lock through serialization and replacement so API and tick saves cannot overtake each other: agents (role, task, state: starting, reading, thinking, waiting or running; reasoning versus writing is in its live phase; lane; what it is doing), lanes (model, resident agent), saved contexts, recent history and self-check results. The CLI, the dashboard and Coin read it.

## Models

The backend's `models()` is the source of truth for what is loaded, because the model server is shared. Every `model_check_seconds` the daemon compares it with the config and launches any wanted model that is missing or in the wrong shape, one at a time. When a model goes away, its resident contexts are lost; their agents restore a matching snapshot if usable, otherwise read their contexts again when they next run.

## Agents

- **One owner per agent.** Each run is an independent transient `cointos-agent-<id>` systemd user unit running the OpenCode server and client. A daemon thread follows its event and exit files and settles the task. The run outlives a daemon restart.
- **One way to end.** For daemon-directed stops, the agent first leaves the ledger with its task settled; then its systemd unit is stopped. Runs that end externally are settled when observed. Until `exit_grace_seconds` pass, it is listed as exiting. A task's snapshots are forgotten when the task is done or failed, since only then is its conversation over; a requeued task keeps them for its next run.
- **Settling:** a run that ended by itself is finished when its item leaf says so (for surveys and maintenance, when the run stopped normally). Otherwise its task is requeued and the run counts against `max_runs_per_task`. API stops by David and guard stops pass `charge=False` and refund that run. CLI halt calls the daemon's halt API first, which uses the same uncharged settlement path for every live agent and saves the ledger before acknowledging. The existing stopping event prevents further admission; the prior pause setting is preserved.
- **Silence:** `checks.silent_agents` is the shared predicate for recovery and self-check: no outstanding thought and no OpenCode event for `agent_silent_seconds` (currently 30). It covers startup, tools and between-request stalls. Reading, generating and lane waits are exempt because they have a thought. The tick stops silent runs and requeues their task, charging an unfinished attempt. This is an event-silence bound, so a long tool that emits no OpenCode event can also reach it.
- **Looping:** an agent whose thoughts produce the same output more than `max_identical_thoughts` times in a row is stopped and its task requeued.
- **David's own sessions** think through the gateway with a user key, in the user class. A user thought updates `user_last_thought`; the spawner starts no new background agents for `user_quiet_seconds` after that request began. This is a timed admission rule, not continuous hosted-session detection.

## Autonomy

- The spawner keeps up to `max_agents` agents alive, more than the number of lanes, because acting agents hold no lane.
- Existing waiting tasks are resumed first. New work comes from knowledge-tree queues in the configured projects (`what/are/the/cointos/roles.md`), in this order: urgent then queued items (worker), drafted ideas (manager), a periodic survey (manager), maintenance (steward).
- Each agent works in its own git worktree on its own branch. Workers are instructed to commit, merge the current main into their branch, and run `cointos merge` (fast-forward only) to land it; refusal is recorded as blocked. Settlement accepts item status done or blocked as a finished ledger task, and records `branch not merged` when ancestry is absent. Thus ledger `done` alone does not prove delivery.
- Routine maintenance runs only if `maintenance_project` is also configured in `projects`; with sandbox-only scope no CointOS steward is spawned. Sole Survivor is off the current roadmap. The guard handles known recovery mechanically; David brings in a stronger remote agent for catastrophic diagnosis and repair.

## Memory

The machine is David's workstation first. Memory is one pool (unified GPU memory), managed by one rule.

- **Headroom** is available memory (`MemAvailable`) minus `reserve_gb`, the memory always left for David's normal use. Everything CointOS allocates (models, snapshots in `/dev/shm`, agent processes and what their tools run) shows up in this one measurement.
- **Admission uses estimated headroom.** Launching a model needs its `memory_gb`, starting an agent needs `agent_memory_gb`, and saving a context uses size estimated from existing snapshots of that model. With no prior snapshot the estimate is zero and the first save is measured afterwards. This is admission accounting, not a hard bound on agent tools' later allocations.
- **The model server's allowance counts too.** Lemonade runs in `inference.slice` with its own memory budget (`memory.high`), and snapshot files in `/dev/shm` are charged to it. Budget pressure previously caused systemd-oomd to kill Lemonade; crossing this budget is not itself a synchronous kill instruction. So headroom is the tighter of the machine's (available memory minus `reserve_gb`) and the server's (its budget minus its anonymous and shared memory; page cache it drops cheaply). The backend reports the server's.
- **Snapshots give way first, a tier at a time.** They are the only elastic memory. Whenever headroom is negative, or an allocation needs room, the least recently run snapshots in memory move to disk (`disk_snapshots`, at most `disk_snapshots_gb`, whose own least recently run snapshots are forgotten to make room), or are forgotten when the disk tier is full. A snapshot on disk comes back to memory for a restore if it fits; otherwise its context is read again. Moves run outside the daemon's lock.
- **Snapshots outlast everything but a reboot.** Snapshots in `/dev/shm` survive a daemon restart, a killed model and a killed Lemonade; only a reboot or power loss wipes them. When the machine shuts down (systemd reports `stopping`), the daemon attempts to move eligible memory snapshots into the bounded disk tier. Warm recovery requires a completed move, persisted metadata and a matching conversation; power loss can prevent it. Reboot recovery still needs a live demonstration. No snapshot is ever copied periodically: a snapshot is a whole state (about 3 GB for a 35k-token context), so periodic copies would cost terabytes of writes a day.
- **A snapshot is a cache, never a record.** OpenCode's session is the record of a conversation, tool calls and results included. A snapshot is used only when its tokens begin the conversation as it now is, so an old snapshot is never wrong, only shorter: the model reads, and does not repeat, whatever happened since.
- **When headroom stays negative with nothing left to move,** background agents get no lanes and no new agents start, until headroom returns.
- **Distress** is memory pressure (PSI `full avg10` above `max_psi`) sustained for `distress_seconds`. Swap in use is not a sign of it, since it lingers long after pressure is gone. Then background agents are stopped with their tasks requeued, the work model is killed, and Coin is alerted. The model is launched again once its `memory_gb` fits.

## Halt

- `cointos halt` requests durable uncharged settlement from the daemon, then stops its services and remaining agent units and kills the models. If the daemon is unreachable, the CLI reports that and performs process/model cleanup; it cannot retroactively settle work through a dead ledger owner. An API error other than unreachability aborts the CLI before unit teardown. `--keep-coin`, used by Coin's own halt tool, retains Coin. `cointos up` starts everything from the config.
- **On daemon restart**, agent units remain alive. The new daemon adopts prior agents with persisted gateway keys and tasks, follows their event files, and settles runs that ended meanwhile. Unknown agent processes are stopped; running tasks whose agent is absent return to waiting. A retried thought can use a matching checkpoint. This is distinct from `cointos halt`, which explicitly stops agent units too.

## Self-check

Every tick the daemon checks these invariants over the ledger; a violation shows on the dashboard, in `cointos check`, and is sent to Coin:

1. No lane is free (and not held for an agent's grace) for more than `idle_lane_seconds` while an agent is waiting to think on that model.
2. A waiting agent that outranks a lane holder gets a lane within `preempt_seconds`.
3. No waiting agent is passed over for more than `starve_seconds` by an equal that holds a lane past its slice (and is not reading), counted from when that slice ran out.
4. No agent is silent for longer than `agent_silent_seconds`.
5. No agent repeats the same thought more than `max_identical_thoughts` times.
6. Every running agent has a live process, and every agent process belongs to a ledger agent or an exiting one.
7. Headroom is not negative and there is no distress.

## Watching

The dashboard shows agents first: what each is working on, whether it is reading, reasoning, writing, waiting or running tools, and its last action. `/api/live` streams agent cards and memory at 10 Hz; the full ledger is polled once a second. Card elements update in place. The machine panel's memory donut uses physical RAM, configured model-size estimates and measured available memory/snapshot bytes; its Operating System segment is the remainder, not a separate kernel measurement. Values are converted to GiB, currently labelled GB. CLI and ledger memory values use decimal GB. Lanes, models and memory appear as resources after the work. `cointos watch [AGENT]` attaches OpenCode's live view to an agent's session.

**Viewers** are pop-up terminal windows on David's desktop, each showing one live agent (`cointos view N` attaches OpenCode's live view to whichever agent holds slot N). The daemon gives each started agent a viewer: an idle open window first, so idle monitors are captured by new agents, else, while David has asked for them with `cointos view --all` (until `--off`), a new window, up to `max_viewers`. A window David closes frees its slot.
