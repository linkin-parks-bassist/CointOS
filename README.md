# CointOS

David's autonomous local-agent ecosystem. The daemon owns scheduling; agents work
in independent project repositories and share pre-emptive GPU lanes.

Run `scripts/install` from this repository to copy the runtime into `~/.CointOS/`
and configure its systemd user services. Pause first with `cointos stop` and wait
until `cointos agents` reports none. Installation leaves services stopped; start
with `cointos up`. Autonomous work remains paused until `cointos go`.

The source knowledge tree explains development. The installed runtime has its own
globally readable tree explaining runtime operation and daemon-owned task and command
queues. Each project owns its orientation, spec, plan and broken leaves. Submit work
through `cointos queue PROJECT NAME "BRIEF" --kind queued|urgent|command`.

Project enrollment lives in `config/projects.json`, separate from operational daemon
settings. `cointos project new NAME` creates `~/Projects/NAME`, initializes Git and a
project knowledge tree, commits that tree, and registers the project. Use `cointos
project add PATH` for an existing repository, `cointos project set NAME --priority N`
to change its scheduling priority, and `--enable`/`--disable` to control admission.
`cointos project list` and the dashboard Projects panel expose the same registry.
Lower project priority numbers run first within the same lifecycle class.

Coin exposes those project operations over Telegram. It can also request a bounded
ad-hoc operator with `run_agent`; the matching CLI is `cointos agent run NAME BRIEF`
with optional `--project`, `--reasoning-effort`, generation limits, and repeated
`--ability standard|control|network`. Abilities change the operator's actual tool
permissions. They do not grant sudo, package installation, systemd control, Git push,
or access to Avnet/professional data.

Worker tasks carry `--stage skeleton|test-contract|implementation|integration` and
an optional `--reasoning-effort low|medium|xhigh`. The global default is low; only
test-contract workers default to medium. Explicit per-task overrides still win.
Snapshot RAM has a separate `memory.snapshots_gb` budget (24 decimal GB);
cold caches spill to disk before active ones. Transfers are not credited as freed
memory until complete. Budget changes need a drained daemon replacement.

Per-reply reasoning is capped at 256/384/1,024 tokens for low/medium/xhigh,
then generation continues into the answer or tool call. `reasoning.budgets` owns these
limits; changing them currently needs a drained daemon replacement, not a model reload.
Use `cointos reasoning PROJECT:TASK low|medium|xhigh` to change an existing task from its next reply.
Test writers register adversarial checks and code dependencies in the project's
configured test-contract manifest. Implementation landings cannot change protected
tests or their harness; the daemon tests the exact candidate against all registered
contracts covering changed code before advancing main. Unrelated red tests may remain.
The verified acceptance receipt is the terminal authority for task and queue state:
acceptance marks the queue item done, removes obsolete blocker/decomposition data, and
the daemon reconciles legacy contradictions before computing dependencies. Successful
land/incorporate API calls republish the derived runtime queue answers.
For Python, named imports and private helpers follow their same-file callers; shared
module changes still select the whole file. Reviewers must declare dynamic and cross-file dependencies.
Failed implementation checks automatically return the task with failure details for another attempt.
Every agent run ends with exactly one completion receipt that the daemon checks against its
artifacts: `cointos finish --complete "evidence"`, or `--blocked "reason"` for a real blocker.
An integrator's verified `cointos land`, `incorporate` or `return` is its receipt. Process exit,
OpenCode finish markers and final text never complete a task; a run ending without a receipt is
retried a bounded number of times (`cointos/lifecycle.py`, `what/is/the/agent/completion/model.md`).
Managers record remaining work in the project plan before finishing their bounded stage.
Periodic low-reasoning stewards inspect the runtime and all configured projects for concrete loose ends and
may enqueue one bounded manager command; they never implement the work themselves. If a scout needs David,
`cointos attention` raises a daemon alert that Coin delivers instead of leaving the request in its terminal. Their
cadence uses a six-hour idle baseline multiplied by one plus the active/queued concern
count, so scouting becomes less frequent while the factory is busy. The dashboard's Work
header can schedule the same deduplicated scout immediately with **Spawn scout**. Scouts are
system tasks launched from the installed runtime, with no project place, branch or worktree.

A medium-reasoning test auditor runs after recent accepted product work. It samples one landing,
compares its tests with the owning specification, runs bounded relevant suites, and asks whether
plausible wrong implementations could still pass. A concrete semantic coverage gap becomes one
manager command in the owning project; a clean audit is valid. This retrospective loop provides
eventual correction without requiring every landing to be perfect.

Gardeners periodically sample and maintain the CointOS source tree and every registered project's
knowledge tree. They do maintenance only: current-truth verification, repair, and renewal in a bounded
batch. Structural tree auditors remain a separate slower pass.
When a queue-backed task fails terminally, the daemon marks its matching queued record
blocked with the failure reason and republishes the queue; failed tasks cannot remain live-looking zombies.
The dashboard leaves active and queued work open, folds **Gave up** and **Done**, and its
**Clear task history** action removes unreferenced terminal task records plus unneeded
done/blocked queue history while retaining terminal prerequisites still used by live work.
`cointos supersede PROJECT:FAILED REPLACEMENT... --reason "evidence"` repairs failed
prerequisites without accepting the failed task. `cointos incorporate PROJECT:ITEM
--commit MAIN_SHA --worker-commit WORKER_SHA` verifies exact submitted implementation
already present on main and records acceptance. Integration also runs accepted contracts
for carried production changes and preserves existing tests and contracts.
`cointos clear-review PROJECT:ITEM --reason "evidence"` withdraws obsolete infrastructure
feedback from inactive waiting work and starts the next run in a fresh session.

`recovery` defaults each run to 1,800 seconds of generation or 36,000 generated tokens,
including reasoning and excluding lane wait, prefill and tools. Tasks carry daemon-owned
`budget` metadata with `generation_seconds` and `generation_tokens`; omitted limits inherit
the defaults and are pinned when the task is created. Queue with
`--generation-seconds 1800 --generation-tokens 36000` to override them, or use
`cointos budget PROJECT:TASK --generation-tokens 36000` on waiting/undispatched work.
The API accepts `budget` on `/api/queue` and `{task, budget}` on `/api/budget`.
Every new or fresh-recovery run gets an FYI at the end of its launch prompt describing both
limits and the accounting, plus its exact per-reply reasoning limit and an instruction to decide
succinctly before using a tool or answering. A same-session continuation under three hours gets
only `Continue.` because OpenCode rejects an empty invocation; after that it gets one concise reorientation. Active runs
cannot have their limits changed underneath them.
Worker items with no branch artifact at 600 generation seconds or 12,000 generated tokens
recover early. Fresh recovery includes a bounded 6,000-character packet of recent outward
text, tool actions/results and Git state; hidden reasoning is never copied.
Up to two fresh-session retries preserve the branch
and files; ordinary death/restart still resumes the same session. Committed done/blocked
reports take precedence over the limit.
A process that exits before its first gateway request is an infrastructure launch failure,
not an assignment attempt. CointOS refunds it, retries at most twice, then durably holds the
task and alerts instead of consuming work attempts or respawning forever.
`state/events.jsonl` plus one rotated file retain bounded diagnostic events (8 MiB each),
including snapshot and acceptance evidence without model prompts. Managed tasks pin their
complete initial system/developer prefix by digest, so later runs do not invalidate warm context
merely because generated startup context changed; each request journals only its system-prompt digest.
These settings need
a drained daemon replacement. Dashboard rows show replacements, acceptance receipts and incidents.
Use `cointos task PROJECT:ITEM` to inspect its exact metadata, queue dependencies and receipts.
See `kt what is the shape of cointos work` for coverage and enforcement boundaries.

Use `kt where am i` for orientation and `python3 -m unittest discover` for checks.

The dashboard's Machine panel changes GPU time slice (seconds) and generation step
(tokens). `scheduler.slice_seconds` and `scheduler.chunk_tokens` reload from the
active runtime config each tick once this version is installed. Current GPU steps
finish before the new chunk size is used. Other settings do not reload live yet. The restart hierarchy and current deployment
limitations are documented in `kt how to restart cointos`. Restart drain closes spawn admission
while allowing existing conversations and receipts to continue to a quiet request boundary;
broader live replacement acceptance remains open.
For configuration-compatible code or guidance changes, `scripts/install --live` lets admitted
thoughts finish, retryably blocks new thoughts, replaces the installed runtime and restarts only
cointosd while preserving live agent units. Daemon-policy configuration changes—including reasoning,
recovery, scheduling and spawning policy—are compatible. Changes to the gateway endpoint, backend or
loaded-model identity/topology are refused; use the paused full installation for those. The live drain cancels after 60 seconds by default without
stopping anything; `--wait-seconds N` changes that bound.
