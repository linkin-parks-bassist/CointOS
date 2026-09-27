---
status: green
revised_at: "2026-09-27T16:41:31+10:00"
---

This leaf owns the CointOS frontier: the milestones, where each one stands, the evidence, and the ordered next steps. `what/is/broken.md` owns the current defects; this plan only schedules their fixes.

The goal is to build the architecture in `what/is/the/architecture/of/cointos.md` in milestones. Each milestone ends with a live demonstration on the real machine and a green `cointos check`. The core stays around 3,000 lines (`how/to/keep/cointos/simple.md`); it is 3,501 lines now.

## Milestones

1. **Config, models and backend.** `config/cointos.json`, and the backend layer that launches both models through Lemonade in their configured shapes. *Live:* both models load with the configured context and lanes, and the ledger shows memory and headroom.
2. **Pre-emptive lanes.** `cointosd` with the ledger, the gateway, thoughts advanced in steps, switches with snapshots, and the scheduler (classes, reading holders, slices, tool-call yields with grace, reservations), plus `cointos status` and `cointos check`. *Live:* a Coin thought takes a busy lane within a few seconds, and the pre-empted thought resumes warm. Four agents share two lanes, and each finishes its cold read before an equal pre-empts it.
3. **Agents.** OpenCode agents launched through the gateway in per-task git worktrees (`how/to/launch/opencode/for/a/cointos/agent.md`), with stopped runs resumed. Add `cointos agents`, `jobs`, `stop`, `go` and `watch`. *Live:* four agents with small real tasks share two lanes and finish. Killing one mid-run resumes its task.
4. **Autonomy.** The spawner, knowledge-tree queues and roles, with every level of work pipelined (`what/is/the/shape/of/cointos/work.md`) and one integrator per project landing committed changes. *Live:* in one unattended hour, queue items advance to done with commits, and the handoffs follow the construction pipeline.
5. **Coin.** The Telegram service, using the daemon API, the gateway (reserved lane) and kt MCP tools, with a bounded number of tool rounds per turn. `cointos halt` and `up` provide lifecycle control. *Live:* the Coin-under-load scenario from the spec.
6. **Memory and dashboard.** Headroom from both limits, snapshot tiers, distress, and the agents-first dashboard. *Live:* the full acceptance in `what/is/the/spec.md`.

## Where it stands (checked 2026-09-27)

All six milestones are implemented on `rebuild/simple-core`, including bounded gardening and separate tree auditors. This checkout is also the installed runtime. Full live acceptance remains open.

**Module map.**
- `backend_llama.py`: Lemonade and llama-server.
- `scheduler.py`: pure lane policy.
- `lanes.py`: stepped thoughts and context tiers.
- `gateway.py`: the gateway, the API and the live stream.
- `work.py`: task supervision and admission.
- `agents.py`: memory-capped systemd agent units.
- `memory.py`, `checks.py`, `daemon.py` and `state.py`: measurement, the guard and checks, and the single-writer ledger.
- Supporting modules: queues, trees, CLI, Coin, kt MCP and viewers.
- `web/dashboard.html`: the dashboard.
- `config/cointos.json`: operational limits and timeouts.

**Live operation.** `cointosd` and `cointos-coin` are active but paused, and `cointos check` passes all eight checks. The sandbox is the only configured project. The configuration is temporarily focused on a single pipeline exercise:
- `max_agents` is 2;
- the Qwen3.8 work model has one 131,072-token lane;
- `trees: []`, which disables gardening.

**Pipeline exercise.** The C JSON-parser exercise failed and was erased on 2026-09-27: its sandbox code and leaves, ledger tasks, OpenCode sessions, worktrees, branches and run directories. Landed Python utilities and completed task records are kept. David chose a simpler Todo CLI for the next attempt; its brief, product behavior and acceptance only, went in through ordinary intake at sandbox `what/is/the/drafted/todo-cli.md`. The manager's first run took about 22 minutes including its cold read. It outlined five stages (store, CLI, test contracts, implementations, integration) and queued two skeleton items, `todo-store-skeleton` then `todo-cli-skeleton`, which depends on it (sandbox `fb10fe5`). Both skeletons landed: the store at 16:15 (sandbox `380fa71`), then the CLI (`4738588`). CointOS was then paused (`cointos stop`) with the queue empty, for the layout rework in step 2. The exercise resumes in `~/Projects/todo-cli/`.

**Queues.** Project queues are now `what/is/queued.md` and `what/is/drafted.md`, indexes of endpoint leaves under `what/is/the/` in priority order. Urgent work is listed first. A worker's `Needs decomposition:` rejection now dispatches a `decompose` manager task. The architecture leaf owns the details. The sandbox is migrated; the old project-wide state and next leaves are retired from roles, prompts and the CLI.

**Verification.** `python3 -m unittest discover` passes 98 tests. They cover:
- pre-emption policy;
- snapshot identity and lifetime;
- halt settlement and pause preservation;
- ledger serialization;
- integrator delivery and dependencies;
- bounded gardener selection and completion;
- audit cadence and exclusion;
- guarded task erasure;
- snapshot owner liveness and the startup orphan sweep;
- queue index order, entry removal on landing, and decomposition dispatch;
- landing trailers counting only items whose leaves have left main. This is deployed, and step 2 retires trailers.

Sandbox main passes 217 tests. None of these tests shows that the role prompts produce good live work.

**Live acceptance evidence.** A two-hour soak on 2026-09-27 took 1,360 five-second samples:
- All seven checks that existed then stayed green.
- Four live agents appeared in 1,357 samples; the other three samples showed three agents, during handovers.
- Three sandbox items landed.

The soak predates the integrator and bounded roles, so it does not certify them. It did not exercise Coin timing, workstation priority or user priority. The logs are gitignored, in `logs/evidence/m3-20260927.log` and `logs/evidence/lanewatch.log`.

Earlier bounded observations:
- token-level resume and chunked reading work;
- slot saves and restores take 0.2–1.5 s;
- one owner can hold concurrent contexts; a shared 10,832-token start took 0.87 GB;
- after Coin pre-emption, the first token came at 1.6 s;
- a suspended-startup silence test recovered in 29.97 s;
- a single-task halt/up kept its worktree and session, refunded the run and later delivered.

**Not yet demonstrated live:**
- kill recovery within 30 s;
- Coin replies under load;
- workstation responsiveness and user priority;
- multi-agent halt/up;
- reboot snapshot recovery;
- integrator send-back;
- the quality of bounded manager, gardener and auditor work.

## Next, in priority order

1. **Observe the Todo CLI exercise.** `cointos go` is authorized for it. The manager derives the work, workers implement it, and the integrator reviews and lands it. Do not coach the product brief, and do not decompose or implement it for the agents. Report failures honestly. Check four things against `what/is/the/shape/of/cointos/work.md`:
   - whether the handoffs follow the construction order;
   - whether task sizes match the calibration, watching for the oversized runs recorded in `what/is/broken.md`;
   - whether any `Needs decomposition:` rejection reaches a `decompose` manager;
   - whether the finished software meets the brief's acceptance.

2. **Fix the misleading layout** in `what/is/broken.md`, to David's intended layout (2026-09-27):
   - The installed runtime copy lives in `~/.CointOS/`.
   - Its runtime-local tree `~/.CointOS/.knowledge` is globally accessible, so agents understand the system they run under.
   - Each managed project is its own repo under `~/Projects/`, such as `~/Projects/todo-cli/`, and its `where/am/i.md` orients to that project alone.
   - Worktree paths never name CointOS; a worktree is a plain worktree of the project repo.
   - Trees are federated. A new project gets `git init` and `kt init`, and its local tree holds only the project: orientation, spec, plan and broken.
   - The scheduler queue leaves project trees. It becomes daemon-owned bookkeeping in the runtime tree, with a single writer. Managers propose tasks through the daemon API, and an integrator finishing signals the daemon to settle the task. This retires `Landed:` trailers.
   - A general command queue replaces drafted. David queues commands such as "create a new project that…", and a manager turns them into plan items and scheduled tasks.
   - Workers report on their branch as before. Integrators review, accept or reject, maintain the project's local tree and plan, then commit and merge.
   - Move the Todo work into `~/Projects/todo-cli/`.

   First archive the dead install and its units. David has handed the build to a Codex agent (Astra). CointOS stays paused until the rework lands; then run `cointos go`.

3. **Restore the ambient configuration** once the exercise ends. Set:
   - `max_agents=4`;
   - work-model `lanes=2`;
   - `ctx_size=262144`;
   - `trees` to `[{"name":"cointos","path":"~/Projects/CointOS","tree":".knowledge","main_branch":"rebuild/simple-core"},{"name":"sandbox","path":"~/Projects/cointos-sandbox","tree":".knowledge","main_branch":"main"}]`.

   A lane-shape change needs a controlled model reload.

4. **Validate bounded gardening live** under the ambient configuration. Show one random 1–3-leaf pass, one non-green batch and one separate structural audit. Do not run an exhaustive whole-tree repair as a routine pass.

5. **Fix the cold resume after a reload** in `what/is/broken.md`: find the diverging prefix. Do not claim a warm restart until this is fixed.

6. **Fix the malformed OpenCode continuation** in `what/is/broken.md`, as part of robust interruption semantics at the gateway/OpenCode boundary.

7. **Fix steward admission** in `what/is/broken.md`. Either add CointOS to `projects` or retarget `maintenance_project`. This is David's call, because it widens autonomous scope.

8. **Finish the remaining acceptance tests** listed under "Not yet demonstrated live". Coin timing needs David's messages or a test he explicitly authorizes.

9. **Deferred design:**
    - ambient and focused operation;
    - runtime-adjustable project and task-kind priorities;
    - weighted or counted lane sharing in place of strict classes and equal-class slices;
    - a separate reviewer scheduler;
    - a CointOS MCP control surface;
    - choices for reshaping or forking memory;
    - network restrictions beyond prompt and OpenCode denials.

    David deferred implementing the scheduling items. Task admission rank and GPU class priority are distinct today.

OpenCode stays at 1.18.32 by David's direction; its launch procedure holds the V2 assessment. Sole Survivor is off the roadmap. Catastrophic recovery is left to David's remote intervention.
