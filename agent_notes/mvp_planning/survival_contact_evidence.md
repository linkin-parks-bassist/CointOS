# Survival/contact MVP evidence

Flint (Codex) recorded this bounded planning handoff on 2026-09-05 for Astra in
David's personal repository. It is evidence and decomposition, not a decision or
live-operation record. No runtime, service, credential, Telegram, model, test, or
Git mutation was made.

## Current authoritative seams
### Permanent literal ingress and fallback
- `survival/gateway.py:handle_update(update, allowed, store, send, send_command,
  send_acknowledgement=None, monotonic_now=..., boot_id=...,
  degraded_response_deadline_seconds=None) -> dict` authenticates and persists
  every supported update through `survival.records.accept_update`.
- Literal `RESTART`/`RESET` become the exact protocol record returned by
  `survival/gateway.py:command_record(accepted, command)` and are sent through the
  peer-authenticated guardian socket. Ordinary text calls
  `survival.telegram_api.store_inbound(...)` and returns
  `{"kind":"ordinary","id":"telegram-N"}` without inference.
- `survival/records.py:accept_update(root, update, allowed_user_ids) -> dict`
  exclusively creates `commands/telegram-N.json`; replay must preserve update,
  user, chat, and text identity.
- `survival/telegram_api.py:store_inbound(root, accepted, monotonic_now,
  deadline_seconds, boot_id=...)` projects into `inbox/telegram-N.json` with
  acceptance time, deadline, boot identity, and `egress_state`. Its read/list/update
  functions are the actual inbox surface; Plan 03's `records.claim_inbound`,
  `records.complete_inbound`, and ordinary reply-outbox functions do not exist.
- `survival/gateway.py:send_due_degraded_responses(...)` skips only inbox records
  whose `egress_state` is `delivered` or `delivery_unknown`; `sending` is converted
  to `delivery_unknown`. Therefore the ordinary adapter must publish the terminal
  delivery observation before the deadline scan can safely stand down. It must not
  report success merely because a control turn was accepted.

### Existing conversation/control-turn route
- `ecosystem/telegram.py:accept_update(token, update, allowed, send=reply,
  infer=chat) -> bool` owns durable turn acceptance, conversation append, fast
  inference, and direct Telegram egress together. It returns polling consumption,
  not delivery state.
- Its durable core is `ecosystem/control_turns.py:accept(update_id, chat_id,
  user_id, message) -> tuple[dict, bool]`. It exclusively creates
  `state/control-turns/telegram-N.json`, validates replay identity, initializes
  `front_state="pending"`, `deep_state="queued"`, and is already the exact-once
  identity joint required by the survival inbox adapter.
- It appends sources `telegram-N:user` and `telegram-N:front`, marks front
  generation/sending/delivery, and turns interrupted send into `delivery_unknown`.
- `ecosystem/control_worker.py:process_turn(identifier, send=reply,
  controller=respond)` consumes the same record only after
  `control_turns.reserve_next(...)` sees a terminal front state. Thus merely
  calling `control_turns.accept` is insufficient: the adapter must also drive or
  observe the established front path so deep control becomes eligible.
- `agent-telegram.service` is a composite old long-poller plus fast-front process.
  It cannot remain enabled during permanent-gateway polling, and stopping it also
  removes its front processor. `agent-control-worker.service` is separate and may
  remain live.

### Guardian/lifecycle route
- `survival/guardian.py:handle_one_request(connection, config, ...) -> dict|None`
  authenticates `SO_PEERCRED`, strictly decodes, durably accepts/acknowledges, then
  calls `resume_pending_request`.
- `survival/guardian.py:resume_pending_request(config, adapters=None,
  recover_blocked=True)` advances only the oldest incomplete lifecycle through
  `survival.system_control.advance_request(path, adapters, policy, ...)`.
- `survival/system_control.py:advance_request(...)` persists reductions/effect
  results and returns phase/remaining effects. Production adapters own admission,
  checkpoint, reconcile, verify, restoration, and finish. Survival units are not
  destructible.
- Root-owned units already exist for gateway, guardian socket/service, checkpoint,
  and survival slice. `scripts/install-survival-plane` builds a content-addressed
  release and an authoritative `current` link; default is install-only, while
  `--enable` starts all four units. It does not stop the old user poller, so that
  flag alone is not a safe poller cutover.
- The installer makes the inbox `2750` under
  `cointelprofessional:agent_ecosystem_io` and adds David to that group. Whether an
  already-running user manager supplies it is unverified; prove it before cutover.

### Inference capacity
- `ecosystem/inference.py:chat(model, messages, max_tokens, timeout,
  temperature=0.35, tools=None, response_format=None) -> dict` calls Lemonade
  directly, without lane, durable identity, global admission, or reserve.
- `config/model-policy.json` declares two resident slots, fast-front parallelism
  two, and one reserved control slot. `scripts/load-resident-models` configures
  Lemonade `max_loaded_models=2` and loads the 4B model with `--parallel 2`.
  Those are model/backend capacities, not proof that one sequence remains free:
  unrelated callers can issue direct concurrent `chat` requests.
- No `ecosystem/inference_queue.py`, `ecosystem/inference_arbiter.py`,
  `ecosystem/fast_control.py`, or `ecosystem/fast_worker.py` exists. Plan 03 Tasks
  1-4 describe unimplemented architecture, not current seams.

## Disposition after Astra's synthesis

Astra retained the current-seam evidence above but rejected this handoff's initial
suggestion to preserve the unconditional front/deep route behind a bridge. David's
"nothing is sacred" policy and complete MVP request call for one canonical
respond-or-dispatch route in C1-C3. Reuse identity/persistence, not the rejected
controller decomposition. This is a maintained evidence note, not another plan.

The [MVP index](../../docs/plans/2026-09-05-cointos-mvp-index.md) owns
all task order and deferred work. C3 must distinguish a bounded degraded notice
from a later substantive answer; unknown delivery never permits replaying the same
message. C4/C5 own cross-UID access, one-poller cutover and actual contact proof.
R3/R4 enforce physical front reservation across every model caller. H2/H3 keep
repair independent of the ordinary scheduler; P1-P4 supply exact Coin-approved
activation and rollback. B1-B4 implement David's live agent-communication contract.

Installer caution: a non-default installation prefix is not hermetic while the
script still runs host group/user commands. Do not run it as a unit-test fixture;
substitute only the actual privilege/systemd/filesystem fingertips and perform
live installation solely within the authorized coordinator-owned cutover task.
