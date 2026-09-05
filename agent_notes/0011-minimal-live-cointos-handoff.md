# Minimal live CointOS handoff

Recorded by the root Codex agent on 2026-09-05 from David's explicit correction
of implementation priority. This is the authoritative handoff for the next Astra
planning session.

## Governing delivery order

CointOS must be built and improved in three stages:

1. Put the base architectural skeleton in place, bring it online, and prove the
   ordinary live path works.
2. Run basic tests and incrementally repair failures while the system exists and
   remains useful.
3. Apply exhaustive review, adversarial testing, security hardening, and deeper
   architectural extraction over time through autonomous system maintainers.

Stage 1 is not gated by exhaustive review. A private Telegram bot known only to
David does not need every hostile-input edge closed before it can exist. Security
and durability findings must be recorded rather than forgotten, but they do not
block initial onlining unless they prevent ordinary operation, risk OOM, sacrifice
Coin or GUI responsiveness, make rollback unsafe, or would render the system
unrecoverable.

## Current reality

- The old user-owned Coin Telegram gateway, control worker, notifier, and model
  services are live.
- The new permanent, model-independent survival gateway, privileged guardian,
  checkpoint consumer, `RESTART`/`RESET` lifecycle machinery, durable records, and
  systemd units are implemented in the topic branch.
- The new survival services have never been installed or enabled on the live
  machine.
- Commit `12b1c19` minimally contains the two known faults most likely to cause
  ordinary guardian or gateway restart loops. It deliberately does not close the
  entire adversarial Task 4 review.
- The local `Qwen3.8-27B-GGUF` worker is loaded alongside the pinned 4B Coin front.
  Its server and OpenCode limits are now 131,072 context tokens and 32,768 output
  tokens. The interrupted local bridge attempt made no filesystem changes.

## The actual missing vertical slice

The permanent gateway accepts and durably writes ordinary Telegram messages under
`/var/lib/cointelprofessional/inbox`, but the existing Coin pipeline does not
consume that spool. Enabling the permanent gateway as the sole poller today would
make literal lifecycle commands available while ordinary conversation appeared
dead.

Only three joints are required for the first honest live slice:

1. A narrow user-owned adapter consumes schema-valid survival inbox records and
   maps `telegram_update_id`, `chat_id`, `telegram_user_id`, and `text` into the
   existing durable `control_turns`/Coin pipeline exactly once.
2. Successful ordinary handling produces the minimal acknowledgement understood
   by the survival gateway, preventing its deadline-based degraded fallback after
   Coin has already replied. Direct Telegram egress from the existing Coin worker
   is acceptable temporarily; an ordinary gateway-owned outbound spool is later
   work.
3. Cutover enables the new survival guardian/gateway/checkpoint services and
   disables only the old Telegram long-poller. The existing fast-response and deep
   control workers remain available. The old poller configuration remains a
   rollback route, but must not run concurrently with the permanent poller.

## Minimal Astra plan

Replace the current sequencing with this bounded Stage 1 plan:

1. Implement the survival-inbox-to-`control_turns` adapter.
2. Implement the ordinary-response acknowledgement.
3. Run one focused exact-once adapter test and syntax checks.
4. Provision the existing private Telegram credentials into the survival-plane
   credential paths without exposing their values.
5. Install the survival release and start guardian/checkpoint.
6. Switch Telegram polling atomically enough for practical use: stop the old
   poller, start the permanent gateway, and retain a direct rollback command.
7. Live-smoke one ordinary message and one literal lifecycle command.
8. If both work and Coin remains responsive, declare Stage 1 online. Do not delay
   that declaration for the deferred audit queue.

## Explicitly deferred work

Retain these as autonomous-maintenance tasks after onlining:

- canonical incident/message identity grammar and path containment;
- distinct immutable identities for changing quarantine outcomes;
- full adversarial critical-delivery reconstruction;
- extraction of reporting concerns from the oversized
  `survival/system_control.py` boundary;
- progress cadence during individual long-running lifecycle effects;
- full cross-UID, filesystem-permission, systemd, Telegram, rollback, and hostile
  input verification;
- broader Coin identity/voice restoration, duplicate-response cleanup, stale job
  cleanup, and truthful tool/agent status presentation;
- the system-wide spontaneous agent spawning, monitoring, resource management,
  context handover, and continual self-improvement engine.

These are important, but their intended home is a running CointOS whose maintainers
can improve it incrementally. Do not spend the bootstrap budget proving every nook
and cranny before the basic vertical slice exists.
