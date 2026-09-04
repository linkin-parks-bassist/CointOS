# Operations

## Manual operation

Run `./scripts/ecosystem run-once`. `status` reports queue counts. Inputs are
accepted only as `inbox/new/*.md`. A SHA-256-derived job ID makes rescanning the
same content idempotent.

Use `./scripts/ecosystem pause` as the global kill switch. While paused,
`run-once` exits with status 75 before scanning or processing. Use `resume` to
clear it.

Failed work remains in `state/jobs/*.json`; the current CLI does not retry it
automatically. This is deliberate until retry limits and operator controls are
implemented. Logs in `logs/runs/YYYY-MM-DD.jsonl` are append-only.

## Optional systemd user units

Install or refresh the checked-in units with:

```bash
mkdir -p ~/.config/systemd/user
cp services/systemd/agent-ecosystem.{service,path,timer} ~/.config/systemd/user/
cp services/systemd/agent-watchdog.{service,timer} ~/.config/systemd/user/
cp services/systemd/agent-{telegram,control-worker,notifier,models}.service ~/.config/systemd/user/
cp services/systemd/agent-resource-guard.service ~/.config/systemd/user/
cp services/systemd/{control,background}.slice ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user disable --now agent-resource-guard.service
systemctl --user enable --now agent-models.service agent-telegram.service \
  agent-control-worker.service agent-notifier.service \
  agent-ecosystem.path agent-ecosystem.timer agent-watchdog.timer
```

These are the current user services. They are recoverable development infrastructure,
not the root-installed permanent gateway and hard guardian designed for the survival
plane. Do not describe them as permanent or test `RESTART`/`RESET` against them until
Plan 5 installs that boundary and its live acceptance sequence passes.

## Permanent survival-plane package

`scripts/install-survival-plane` packages the model-independent gateway, guardian,
and unprivileged checkpoint consumer without enabling or starting anything by
default. It creates the dedicated
`cointelprofessional` system account, the private `cointelprofessional_command`
socket group, and the shared `agent_ecosystem_io` spool group. The installed code,
entry points, lifecycle catalogue, and this operations file are immutable root-owned
copies under content-addressed `releases/`. The single `current` symlink is the
authoritative package value; services resolve code, units, and documentation through
it and never execute the mutable checkout. Unit links are constructed before
`current`, so an interrupted first install has no resolvable operational surface and
a retry completes it without exposing a partial release.

Before installation, provision the Telegram bot token at
`/etc/cointelprofessional/telegram_bot_token` and the allowed numeric Telegram user
identities, one per line, at `/etc/cointelprofessional/allowed_user_ids`. Do not pass
either value on a command line. The installer deliberately does not create
placeholder credentials. It creates the mutable, root-owned timing policy at
`/etc/cointelprofessional/time.cfg` only when absent and enforces mode `0644` so all
three services can read this non-secret policy, resolves the actual gateway and David user IDs
into a root-readable guardian environment file, and creates these runtime boundaries:

```text
/run/cointelprofessional/       root:cointelprofessional_command  0750
/var/lib/cointelprofessional/   root:root                          0755
inbox/                          cointelprofessional:agent_ecosystem_io 2750
outbox/critical/                root:cointelprofessional           2750
gateway private state          cointelprofessional:cointelprofessional 0700
guardian lifecycle state       root:root                          0700
checkpoint-requests/            root:david                         0750
checkpoint-results/             david:root                         0750
guardian.sock                   root:cointelprofessional_command  0660
```

Inbox records are `0640`: only the gateway writes them and David's ordinary plane
may consume them. Root critical records are also `0640`; the gateway may read but
cannot alter them, and keeps delivery state in its own private directory. Neither
ordinary work nor the gateway can rename or inject entries at the store root.

The checkpoint consumer runs as David, has no guardian socket or system-manager
authority, and remains outside the ordinary admission and destructible-unit sets.
It can read only fixed-schema checkpoint requests, canonical job records, and the
corresponding durable OpenCode logs; it can write only request-scoped result facts.
The guardian service restores the volatile `/run/cointelprofessional` directory
with its owner and mode after each boot and preserves it across guardian restarts.

After reviewing the pending diff, install the files without activation with:

```bash
sudo ./scripts/install-survival-plane
```

The install-only path verifies the installed units but does not call `systemctl`,
reload the manager, or disturb the current user gateway. `--enable` performs the
separate daemon-reload and enable/start transition; it is reserved for Plan 5's
credential-aware live acceptance sequence and must not be used as an offline test.
The systemd units supply `NOTIFY_SOCKET`; never put a literal notification socket in
the environment. `NotifyAccess=main` is intentional: gateway workers publish their
health to their parent, and only the service main process emits readiness/watchdog
datagrams. The guardian likewise stops watchdog renewal while a lifecycle operation
is wedged. During a legitimate bounded checkpoint, systemd operation, or escalation
grace, its adapter emits progress watchdog observations; the configured policy still
owns each operation deadline.

`RESTART` and `RESET` are serialized durable lifecycles. The guardian commits
recoverable pending work before acknowledging the socket, resumes the oldest request
at startup and on idle polls, and records an immutable result attempt before reducing
the next phase. `RESTART` closes activation, checkpoints, then performs cooperative
stop with TERM/KILL escalation; `RESET` skips the handoff and escalates immediately.
The restart checkpoint request is published as a David-readable `0640`
`checkpoint-requests/<request-id>.json` before one absolute monotonic deadline. The
David-owned consumer atomically publishes exactly one result per requested job under
`checkpoint-results/<request-id>/`: `checkpointed`, `already_terminal`,
`unsupported`, or `deadline_expired`. A `checkpointed` result is accepted only when
its exact `ses_*` identity is still present in that job's canonical durable OpenCode
log. Sleeping to the deadline is not checkpoint success. The guardian then moves
every still-active requested job through its sole crash-safe per-job interruption
intent/mutation/completion route; a verified session makes that interruption
resumable, while absent, malformed, stale, or forged evidence does not.
Both clear systemd failed/start-limit state, start Lemonade and inference/control prerequisites, reconcile jobs, control
turns, uncertain outbox delivery, and pending verification, verify the pinned-model
canary, and only then restore prior activation and pause state. The resource guard is
catalogued as intentionally inactive and is not started.

Monotonic inbox deadlines carry the originating boot identity; an unknown or changed
boot makes the response immediately due. Unsupported Telegram update bodies receive
a durable ignored disposition and advance a durable poll offset. A malformed spool
record is quarantined without withholding worker watchdog renewal. The gateway writes
a separate durable degraded data-health fact for every incident and the guardian
emits one root-owned critical report per incident. A failed quarantine move is
reported truthfully while later egress and watchdog renewal continue.

Both services validate the complete timing schema. Valid live edits are adopted as
one projection. Invalid edits keep `/var/lib/cointelprofessional/policy/time.json` as
the guardian's last-known-good value, persist `policy/status.json`, and enqueue a
deduplicated critical explanation. Inspect offline state with:

```bash
jq . /var/lib/cointelprofessional/policy/{time,status}.json
jq '.state | {phase,pending_effects,completed_effects}' \
  /var/lib/cointelprofessional/lifecycle/telegram-*.json
find /var/lib/cointelprofessional/{quarantine,lifecycle-result-quarantine} \
  -maxdepth 1 -type f -print
```

Keep `agent-resource-guard.service` disabled and stopped across login and reboot. Its
pending `context_overflow` escalation cannot yet complete automatically; Plan 4 must
implement that escalation and the final live acceptance gate must pass before the
guard may be enabled or started.

The resource guard samples the kernel OOM counter, Linux available memory, swap,
memory PSI, and AMD GTT use once per second. `pressure` checkpoints and interrupts
background inference, unloads dynamic models while preserving chat, and resumes
after 60 healthy seconds. `emergency` flushes durable run boundaries, unloads every model, loads
only the bounded Qwen3.5 4B chatbot, and admits exactly one `sole_survivor` run. Ordinary
dispatch remains mechanically closed until that run calls
`scripts/resource-control recover` and the live health gate passes.

Install the root-owned inference boundary with
`sudo scripts/install-resource-controls`. It reduces the boot/runtime TTM allocation
domain to 64 GiB, places Lemonade in `inference.slice`, makes inference the preferred
OOM victim, and gives the desktop and chatbot higher CPU/I/O/memory protection.
The TTM boundary is decisive on this APU: Lemonade's Vulkan GTT is not fully charged
to its systemd memory cgroup, so `MemoryMax=` alone is not a GPU allocation limit.

Lemonade's configured local API is `http://127.0.0.1:13305`; port 8000 is obsolete
for this installation. A resource transition is successful only when its observed
postcondition agrees: stopped units have no live control-group processes, an
unloaded model is absent according to valid Lemonade health, the pinned model is
loaded with a live backend, started clients have live processes, and recovery has
independently verified every required restart. A zero `systemctl` exit status or an
`active` unit state alone is insufficient.

The guard persists these fail-closed phases:

```text
recorded -> clients_stopped -> models_unloaded -> model_loaded
         -> survivor_ready -> active
```

Each retry resumes the durable phase rather than replaying completed effects. Loaded,
backend-alive `ready`, `busy`, and `in_use` models are live; liveness is distinct from
admission availability. Non-OOM pressure must remain above its configured threshold
for the configured confirmation window. Kernel OOM-counter increments remain
immediate emergencies. Resource durations, including the one-second poll period,
are owned by `config/time.cfg`.

The failure chain this procedure prevents occurred on 2026-09-04: a transient
non-OOM sample latched emergency; underscore-rejecting role validation prevented
survivor creation; and exact-`ready` model validation interpreted a busy pinned model
as dead. The old retry loop restarted the contact services every second until
Telegram reached its systemd start limit. Unit tests had passed because their mocks
did not compose these boundaries. Preserve this history when changing phase,
role-resolution, or model-health contracts.

After any live reconciliation, capture evidence without rewriting runtime records:

```bash
systemctl --user show agent-telegram.service agent-control-worker.service \
  agent-notifier.service agent-resource-guard.service \
  -p Id -p ActiveState -p SubState -p Result -p NRestarts -p MainPID
jq '{mode, emergency_phase, sole_survivor_job, emergency_error}' \
  state/resource-control.json
curl --fail --silent http://127.0.0.1:13305/api/v1/health
python3 -m unittest discover -s tests -v
```

Sample these facts more than once and perform an approved end-to-end Telegram probe
before claiming contact is healthy. Also require the real survivor to ingest its
incident and reach a meaningful terminal result: backend `--ctx-size` is shared
across parallel sequences and is not a per-request allowance. On 2026-09-04 the
initial Task 4 gate observed stable identities and zero restarts across six samples
over 25 seconds and passed 113/113 tests, but the survivor's 25,523-token request
then exceeded the effective 16,384-token per-sequence context of a 32,768-token,
two-sequence backend. The guard repeated the unchanged failed-survivor error every
second and was stopped again while Telegram remained stable.

The contained retry later observed total `ctx_size=65536`, parallel two; preserved
the old failed records byte-for-byte; and admitted only canonical replacement
`task-a02f3a746e5a0914`. Its first rollover wrote a 3,956-byte semantic handoff and
started a fresh session, but that session reread the full incident and attempted
33,891 tokens against its 32,768-token per-sequence capacity. One foreground tick
persisted a deduplicated `emergency_escalation` with reason `context_overflow`.
Telegram and notifier retained PIDs 272721 and 272720 with zero restarts, and the
guard remains stopped.

Treat this as safe containment, not completed recovery. Do not restart the guard to
replay the same failure. Plan 4 owns automatic context-overflow escalation to a
larger safely admitted model/context and completion from the preserved finding and
handoff. None of this deploys or proves the future permanent survival plane.

Stop all automatic intake with:

```bash
./scripts/ecosystem pause
systemctl --user stop agent-ecosystem.path agent-ecosystem.timer agent-watchdog.timer
```

Inspect with `systemctl --user status agent-ecosystem.path
agent-ecosystem.timer agent-watchdog.timer` and `journalctl --user -u
agent-ecosystem.service -u agent-watchdog.service`.

## Scoped package installation

`scripts/install-package NAME...` lets Workers and Refactorers install named
packages from existing APT repositories without general sudo. The installed
root-owned boundary comes from `services/privileged/agent-package-install`; its
sudo policy authorizes only that wrapper. Direct APT commands, options, local files,
repository changes, removals, upgrades, and other privileged operations remain
blocked. Inspect records with `journalctl -t agent-package-install`.

## Roles and remote spawning

Roles are Markdown files in `roles/`. A valid role includes `Mission`,
`Permissions`, `Approval required`, and `Handoff` headings. Test context injection:

```bash
./scripts/ecosystem enqueue --role worker --task "Inspect project X and propose its first test"
./scripts/ecosystem prepare-next
```

The resulting `state/jobs/*.prompt.md` is the exact context packet passed to the
serialized OpenCode executor. It runs as David (never root), uses Lemonade locally,
and records output in `logs/runs/<job-id>.opencode.log`.

The executor may modify David-owned files. Its dedicated OpenCode policy blocks
obvious privilege, package-management, service-management, destructive deletion,
Git push, and web tools. Shell containment is best-effort rather than a security
boundary; elevated actions will move through a separate approval broker.
Completion and failure summaries are durable `outbound-message` jobs dependent on
the agent job reaching a terminal state. The Telegram gateway drains this outbox,
retries transient delivery failures, and returns the useful tail of agent output;
the complete transcript remains on disk. This same dependency mechanism is the
foundation for future state watchers and scheduled reminders.

A clean executor exit now moves ordinary work to `awaiting_verification`. A linked
Verifier on a separately selected local model inspects the original request, full
run evidence, artifacts, checks, and current state. Only a schema-valid accepted
verdict becomes `completed` and produces a success notice; a missing, malformed, or
negative verdict becomes `rejected`. Verifiers are never recursively verified.

Production execution is preemptible. Telegram work outranks ordinary local work,
which outranks verification and periodic stewardship; `sole_survivor` outranks all
normal work. A higher-priority arrival interrupts the OpenCode process group after
its durable session identifier appears. Equal-priority work rotates at a five-minute
quantum. The job retains its prompt, JSONL output, `ses_…` identifier, and returns to
`ready`; resumption uses the same OpenCode session.

The router chooses a generous context allocation from a mechanically validated menu
up to the model's advertised capacity. Validation estimates KV demand against live
GTT, preserves the desktop/control reserve, and writes a per-job OpenCode limit.
At 75 percent of the chosen window, the executor interrupts the main turn, resumes
that session only to write `state/jobs/<job-id>.handoff.md`, archives its transcript,
and starts a fresh session from the original prompt, handoff, and current filesystem.
Failure to produce the semantic handoff creates a visibly degraded mechanical
recovery artifact rather than silently losing the task.

The Telegram gateway uses outbound long polling and accepts only configured user
IDs. Put the following in `~/.config/agent-ecosystem/telegram.env` with mode `0600`:

```text
AGENT_TELEGRAM_BOT_TOKEN=replace-me
AGENT_TELEGRAM_ALLOWED_USER_IDS=123456789
```

It supports `/spawn ROLE TASK`, `/roles`, `/status`, and `/pause`; arbitrary text
is never shell input. Installing/enabling `agent-telegram.service` waits for an
explicit decision on credentials and remote data handling.

Ordinary English first reaches resident `Qwen3.5-4B-GGUF` with only a small recent
conversation window and a strict 96-token output bound. This is generated speech,
not an intent classifier or canned acknowledgement. It may converse immediately but
must not claim live facts or action. Override it with
`AGENT_TELEGRAM_FIRST_RESPONSE_MODEL` in the protected environment file.

Every admitted update is already a durable control turn before that inference.
`agent-control-worker.service` then runs up to two Qwen3.5 turns outside the polling
process. The controller can combine narrow validated tools for status inspection, role
discovery, dispatch control, task amendment, and task creation. It finishes through
an internal typed decision: either publish material new information or remain silent
when the first response already handled the exchange. Override it with `AGENT_TELEGRAM_MODEL`.

The deep controller receives conversation, live state, roles, resources, and narrow
executable tools; there is no user-visible JSON envelope. A literal failure notice
appears only after five minutes without a known generated delivery. Receipt, first-
response attempt, delivery, deep work, and follow-up are separate audited states.
Queued work uses deterministic per-turn idempotency keys so a recovered control turn
cannot silently spawn the same task twice.

Only Qwen3.5 4B is pinned, with two request sequences for chatbot and routing/control.
At most one additional work model is loaded, always unpinned. When a capable large
work model is already loaded, the routing model preferentially sends compatible
smaller work through it as an inference upgrade. New model loads are explicit and
context-bounded; Lemonade auto-load defaults are not trusted.

The control agent can request exact local status through a validated read-only tool.
Status includes active job identity, role, selected model, elapsed time, output-idle
time, and a possible-stall warning after five minutes. The model turns that evidence
into ordinary prose; detailed structured state remains internal. All natural-language
actions—including status, roles, and pause—are retained in conversation memory with
the actual reply.

The bot's durable identity and operating knowledge live in
`roles/_control-plane.md`. The underscore marks it as infrastructure rather than a
spawnable worker role. Every natural-language turn combines that complete role
with conversation history, live queue status, resources, model residency, and the
model scheduling policy. Spawned agents receive their role plus a concise ecosystem
situation preamble and their recorded model decision.

Periodic Steward instances draw one assignment from `steward-tasks/*.md`. Selection
is randomized with overdue weighting and per-card maximum intervals, providing
variation without proliferating roles or neglecting low-frequency maintenance.
The chosen card, overdue ratio, job, and findings are recorded in watchdog state
and append-only audit events.

All main roles can call `scripts/tell-david` to create a durable agent-originated
outbox message with severity and an optional response requirement. Executor jobs
receive their job ID through `AGENT_JOB_ID`, so messages are traceable. Delivered
messages are appended to the private bot conversation, allowing David's natural
reply to be interpreted with the originating question or warning in context.
Before delivery, the pinned control model rewrites internal notifications into a
concise informal message. Job IDs, raw JSON, log paths, tool chatter, and queue
jargon remain in local records unless David explicitly asks for technical detail.

Each Telegram-spawned job receives a name invented by the control-plane model under
`config/naming-policy.json`. The generator sees active names, honors explicit user
choices, and targets a modest 8% tasteful-odd-name rate without a fixed pool.
The ordinary baseline is intentionally international rather than Anglocentric;
rare variants include pronounceable alien names and genuinely clever task-linked
puns. The policy explicitly rejects cultural caricature, lazy wordplay, and mascot energy.
Non-Telegram jobs use the same pinned control model to generate their identity.
Names are validated before use. Identity is injected
into context and retained through retries, audit events, agent-originated messages,
and completion notices; it does not create a separate role or pretend agents are human.

For every spawn and again immediately before dispatch, the control-plane model
receives a live inventory of downloaded models, capability labels, sizes, safe
context choices, loaded/busy/pinned state, available memory, GTT, and host load. It
chooses `use_loaded`, `load`, or `defer`, a model, and a context allocation. Caller
model requests are hints. A deterministic validator rejects invented models,
role-incompatible choices, unsafe loads, excess residency, and unvalidated contexts.
Every decision, realization, and later reassessment remains in the durable job.

The bot stores a private per-user JSONL conversation under `state/conversations/`.
The fast front receives at most six messages / 2,500 characters; deep control receives at
most the prior 20 messages / 12,000 characters. This lets
follow-ups refer to prior discussion without putting chat history in Git or audit
events. `/forget` clears conversational memory without deleting jobs or audit logs.
Corrections to the most recent queued/prepared task use the validated `amend`
intent and regenerate its context. Running or completed jobs are never rewritten.

For first-time users, `./scripts/setup-telegram` walks through bot creation,
validates the token, discovers the user ID from a message, and writes the protected
environment file. It does not enable the gateway.
