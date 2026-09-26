---
status: "green"
revised_at: "2026-09-26T15:48:50+10:00"
---

**CointOS is an operating system for agents.** The primitive is the agent. Model lanes are resources: a pre-emptive scheduler time-shares them among agents, the way an operating system time-shares CPUs among processes. Details not fixed here are for the builder to decide, within `how/to/keep/cointos/simple.md`.

## Concepts

- **Agent:** a worker with a task, a role and a conversation (an OpenCode session), living until its run ends. Agents are what CointOS is about; everything else serves them.
- **Thinking and acting:** an agent is always doing one of two things. It is *thinking* while the model extends its conversation, and *acting* while it runs the tools the model called (commands, file edits, knowledge-tree lookups). An agent that is thinking needs a lane; an acting agent does not.
- **Thought:** one span of thinking, from the agent's conversation to the point where the model hands back control with a message or tool calls. A thought can be interrupted and resumed any number of times.
- **Context:** the agent's conversation as the model holds it: a token sequence and the lane state computed from it. A context is *resident* on a lane, *saved* as a snapshot, or *cold* (only its tokens are known, and the model must read them again). **A context is identified by its tokens**, not by who owns it: a lane is *warm* for a thought when the tokens its state holds begin the thought's tokens, and a snapshot is found by a digest of the tokens it holds. So concurrent conversations of one owner never collide, and an agent resuming a task's session (even after a daemon restart) finds that task's context. Owners (a task, Coin, David) serve only display and the forgetting of a finished task's snapshots.
- **Lane:** one execution slot of a loaded model, holding at most one resident context. A model has a fixed number of lanes, set when it is launched.
- **Class:** an agent's priority, highest first: Sole Survivor, Coin, David's own sessions, background work.

## The scheduler is pre-emptive

- **Any lane can be taken back at any moment.** The scheduler decides which thinking agents hold lanes. It never waits for an agent to finish a thought.
- **A switch** takes a lane from one agent and gives it to another: the outgoing context is saved, and the incoming one is restored, or read from its tokens if it has no snapshot. The outgoing agent's thought is suspended exactly where it stopped and loses nothing.
- **Granularity:** a thought advances in steps, each running to its own end: a step reads up to `read_chunk_tokens` of a context the lane does not hold yet, or, once it is read, generates up to `chunk_tokens`. A switch happens between steps. So a lane always holds exactly known tokens, and an agent waits at most one step plus one switch for a lane it is owed. (Nothing is ever cut mid-step: llama-server notices a dropped request only when it next writes, which during a long read can be minutes later.)
- **Reading and generating.** A thought is *reading* while no lane holds its context yet (a truly cold first turn, or a context whose snapshot was lost), and *generating* once the model is writing. The agent's state shows which.
- **Turns.** An agent's turn on a lane runs from when it gets the lane until it gives it up, across consecutive thoughts.
- **Policy**, applied at every step boundary, whenever an agent starts thinking, and every tick (a slice runs out between events):
  1. A thinking agent of a higher class takes a lane from a lower class at once. It takes a lane whose holder is generating before one whose holder is reading, so a cold read is displaced only when there is no other lane.
  2. Among equals, a reading holder keeps its lane until its context is read. A generating holder whose turn has lasted `slice_seconds` gives the lane to the equal that has waited longest.
  3. A tool call yields the lane, like a system call: when a thought ends, the lane stays held for its agent for `yield_grace_seconds`, and a next thought arriving within that grace continues the same turn, so a burst of quick tool calls is not switched out. Only a higher class may take a held lane.
  4. A thought is placed on the cheapest lane open to it: the one it holds or that is held for it, then a warm one, then a free one, then an unreserved one.
- **Contexts stay resident when nothing needs the lane.** When a thought ends, the agent's context stays on its lane. It is saved only when another agent needs that lane, so an agent that keeps a lane between thoughts pays nothing.
- **Shared starts.** Agents of one role share a long common start (tools, system prompt, role). When a context being read shares at least `shared_prefix_tokens` with another context CointOS holds, the read stops exactly there once and saves that start as a shared snapshot. Every later context that begins with it restores it instead of reading it, through the ordinary longest-snapshot match.
- **One snapshot per conversation.** Saving a context forgets its conversation's older snapshots, which are starts of it.
- **Reservation:** one lane of the front-desk model serves only Coin and Sole Survivor, so Coin's first reply never waits.
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
  - **Gateway:** the OpenAI-compatible endpoint on loopback through which every agent thinks (OpenCode agents, Coin, Sole Survivor, David's own sessions). A chat request starts a thought for its agent; the reply streams back as the thought advances, however often it is suspended.
  - **Scheduler** (above), **spawner**, **guard**, **self-check**, and a small loopback **API and dashboard**.
- **Agents:** OpenCode processes the daemon starts, each in its own git worktree with its own gateway key.
- **Coin:** a separate small service (Telegram in, replies out), so it can report on and restart the daemon. It thinks through the gateway and uses the daemon's API and the kt MCP server.

## Config and ledger

- `config/cointos.json` holds every number: models and their shapes, reservations, classes, `chunk_tokens`, `slice_seconds`, bounds, physical limits, spawner limits, intervals and ports.
- `state/cointos.json` is the ledger, written atomically by the daemon only: agents (role, task, state: starting, thinking, waiting or acting; lane; what it is doing), lanes (model, resident agent), saved contexts, recent history and self-check results. The CLI, the dashboard and Coin read it.

## Models

The backend's `models()` is the source of truth for what is loaded, because the model server is shared. Every `model_check_seconds` the daemon compares it with the config and launches any wanted model that is missing or in the wrong shape, one at a time. When a model goes away, its resident contexts are lost; their agents read their contexts again when they next run.

## Agents

- **One owner per agent.** A thread in the daemon starts the agent's OpenCode server and client as one process group, follows its events, and alone reports how its run ended.
- **One way to end.** However an agent ends, it first leaves the ledger with its task settled; then its process group is stopped. Until `exit_grace_seconds` pass, it is listed as exiting. A task's snapshots are forgotten when the task is done or failed, since only then is its conversation over; a requeued task keeps them for its next run.
- **Settling:** a run that ended by itself is finished when its item leaf says so (for surveys and maintenance, when the run stopped normally). Otherwise its task is requeued and the run counts against `max_runs_per_task`. Stops by David, the guard or a halt do not count.
- **Silence:** an agent that has been acting (not thinking, not waiting) for `agent_silent_seconds` with no OpenCode event is stopped and its task requeued.
- **Looping:** an agent whose thoughts produce the same output more than `max_identical_thoughts` times in a row is stopped and its task requeued.
- **David's own sessions** think through the gateway with a user key, in the user class. While one is active, the spawner starts no new background agents.

## Autonomy

- The spawner keeps up to `max_agents` agents alive, more than the number of lanes, because acting agents hold no lane.
- Work comes from knowledge-tree queues in the configured projects (`what/are/the/cointos/roles.md`), in this order: urgent then queued items (worker), drafted ideas (manager), a periodic survey (manager), maintenance (steward).
- Each agent works in its own git worktree on its own branch; a finished worker lands its branch on the project's main branch, and a merge conflict marks the item blocked.

## Memory

The machine is David's workstation first. Memory is one pool (unified GPU memory), managed by one rule.

- **Headroom** is available memory (`MemAvailable`) minus `reserve_gb`, the memory always left for David's normal use. Everything CointOS allocates (models, snapshots in `/dev/shm`, agent processes and what their tools run) shows up in this one measurement.
- **An allocation happens only if it fits in the headroom; otherwise it waits.** Launching a model needs its `memory_gb`, starting an agent needs `agent_memory_gb`, and saving a context needs its size, estimated from the last snapshots of that model.
- **The model server's allowance counts too.** Lemonade runs in `inference.slice` with its own memory budget (`memory.high`), and snapshot files in `/dev/shm` are charged to it. When it overflows into swap, systemd-oomd kills Lemonade. So headroom is the tighter of the machine's (available memory minus `reserve_gb`) and the server's (its budget minus its anonymous and shared memory; page cache it drops cheaply). The backend reports the server's.
- **Snapshots give way first, a tier at a time.** They are the only elastic memory. Whenever headroom is negative, or an allocation needs room, the least recently run snapshots in memory move to disk (`disk_snapshots`, at most `disk_snapshots_gb`, whose own least recently run snapshots are forgotten to make room), or are forgotten when the disk tier is full. A snapshot on disk comes back to memory for a restore if it fits; otherwise its context is read again. Moves run outside the daemon's lock.
- **When headroom stays negative with nothing left to move,** background agents get no lanes and no new agents start, until headroom returns.
- **Distress** is memory pressure (PSI `full avg10` above `max_psi`) sustained for `distress_seconds`. Swap in use is not a sign of it, since it lingers long after pressure is gone. Then background agents are stopped with their tasks requeued, the work model is killed, and Coin is alerted. The model is launched again once its `memory_gb` fits.

## Halt

- `cointos halt` stops the daemon, all agents and Coin, and kills the models. `cointos up` starts everything from the config.
- **On daemon start**, leftover agent processes are stopped and their tasks requeued, to resume their OpenCode sessions.

## Self-check

Every tick the daemon checks these invariants over the ledger; a violation shows on the dashboard, in `cointos check`, and is sent to Coin:

1. No lane is free (and not held for an agent's grace) for more than `idle_lane_seconds` while an agent is waiting to think on that model.
2. A waiting agent that outranks a lane holder gets a lane within `preempt_seconds`.
3. No waiting agent is passed over for more than `starve_seconds` while an equal past its slice, and not reading, holds a lane it could use.
4. No agent is silent for longer than `agent_silent_seconds`.
5. No agent repeats the same thought more than `max_identical_thoughts` times.
6. Every running agent has a live process, and every agent process belongs to a ledger agent or an exiting one.
7. Headroom is not negative and there is no distress.

## Watching

The dashboard shows agents first: what each is working on, whether it is thinking, waiting or acting, and its last action. Lanes, models and memory appear as resources after the work. `cointos watch [AGENT]` attaches OpenCode's live view to an agent's session.
