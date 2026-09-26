---
status: "green"
revised_at: "2026-09-26T10:51:15+10:00"
---

The design in one sentence: **one daemon owns the GPU lanes and hands them out one model request at a time, by priority; agents are ordinary processes that wait their turn.** Details not fixed here are for the builder to decide, within `how/to/keep/cointos/simple.md`.

## Processes

- **`cointosd`**: one long-running daemon (Python standard library, one systemd user unit). It is the only writer of the ledger and contains:
  - **Gateway:** an OpenAI-compatible endpoint on loopback. Every model call in CointOS goes through it: agents, Coin, Sole Survivor.
  - **Scheduler:** runs every second, and immediately on any event; assigns free lanes to waiting requests.
  - **Spawner:** starts agents when there is room and work (see *Autonomy*).
  - **Guard:** samples memory pressure every second and acts on the configured limits.
  - **Self-check:** evaluates the invariants every tick.
  - **API and dashboard:** a small loopback HTTP API for the `cointos` CLI, Coin and the web dashboard.
- **Agents:** OpenCode processes started by the daemon. Each has its own git worktree of its project and its own key for the gateway. An agent lives until OpenCode exits.
- **Coin:** a separate small service (Telegram in, replies out), so it can report on and restart the daemon. It uses the daemon's gateway and API for inference and system facts, and the kt MCP server for knowledge trees.

## Config and ledger

- `config/cointos.json` holds every number: models and their shapes, lane reservations, priorities, physical limits, spawner limits, intervals and ports. It is read at start.
- `state/cointos.json` is the ledger, written atomically by the daemon only. It holds lanes (occupant or free), waiting requests, live agents (role, project, item, worktree, pid, OpenCode session, request count, last activity), bounded recent history and current self-check results. It is the source for `cointos status`, the dashboard and Coin.

## GPU time: lanes and requests

- **Model shapes come from config and are loaded at daemon start:** Qwen3.8-27B with 2 lanes of 131,072 tokens as the work model, and Qwen3.5-4B with 2 lanes of 32,768 tokens as the front desk.
- **The unit of scheduling is one completion request.** An agent is a stream of short requests, one per step. When a lane frees, the scheduler gives it to the highest-priority waiting request for that model, oldest first within a class, preferring the agent that last used the lane so its prompt cache stays warm. Many agents share two lanes this way. Switching a lane between agents costs re-prefill; KV snapshots, when available, will reduce that cost.
- **Priority classes**, highest first: Sole Survivor, Coin, David's own work, autonomous background work.
- **Reservation:** one 4B lane is always kept for Coin's fast replies.
- **Bounded requests:** each request's output is capped by config, so a higher class waits at most one request.
- **David's own sessions:** local OpenCode sessions David starts use the gateway with a user key and get user priority. While user requests are active, the spawner starts no new background agents.

## Autonomy

- The spawner keeps up to `max_agents` agents alive, more than the number of lanes, so a request is always waiting when a lane frees.
- Work comes from knowledge-tree queues in the projects listed in the config (`what/are/the/cointos/roles.md`), in this order:
  1. urgent items, then queued items (worker);
  2. drafted ideas (manager);
  3. a periodic project survey (manager);
  4. maintenance (steward).
- Each agent works in its own git worktree on a branch named after its item. A finished worker merges its branch into the project's main branch; a merge conflict marks the item blocked.

## Guard and halt

- **Physical limits** (in config): minimum available host memory, maximum memory PSI and maximum swap. When one is crossed:
  1. background requests get no lanes;
  2. background agents are stopped and their tasks re-queued;
  3. Coin is alerted;
  4. if pressure persists, the work model is unloaded.

  Sole Survivor, an agent started in this state to diagnose and repair it, comes after the MVP.
- `cointos halt` stops the daemon, all agents and Coin, and unloads the models. `cointos up` starts everything from the config.
- **On daemon start**, leftover agent processes are stopped and their tasks re-queued, to resume their OpenCode sessions.

## Self-check

Every tick the daemon checks these invariants. A violation shows on the dashboard, appears in `cointos check`, and is sent to Coin:

1. No lane is free for more than 5 s while a request for that model is waiting.
2. Coin's reserved lane serves a waiting request within 10 s.
3. No agent is silent (no gateway request, no process activity) for more than 15 minutes.
4. No agent repeats an identical request more than 3 times in a row.
5. Every agent in the ledger has a live process, and every agent process is in the ledger.
6. Physical measurements are within limits.
