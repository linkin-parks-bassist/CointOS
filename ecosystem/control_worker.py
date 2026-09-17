"""Supervised concurrent workers for durable deep-control turns."""
from __future__ import annotations

import os
import signal
import time

from ecosystem import cli, conversation, control_turns
from ecosystem.control_agent import respond
from ecosystem.control_runtime import execute_tool, live_context
from ecosystem.telegram import reply


def process_turn(identifier: str, send=reply, controller=respond) -> None:
    turn = control_turns.load(identifier)
    user_id = int(turn["user_id"])
    history = conversation.recent_before(user_id, f"{identifier}:user")
    try:
        outcome = controller(
            turn["message"], history, turn.get("initial_response"), live_context(),
            lambda name, arguments: execute_tool(identifier, name, arguments),
        )
        followup = outcome.get("followup")
        control_turns.mark_deep_completed(identifier, followup)
        if not followup:
            cli.audit("control_turn.deep_completed_silently", turn_id=identifier, user_id=user_id)
            return
        control_turns.mark_followup_sending(identifier)
        try:
            send(os.environ["AGENT_TELEGRAM_BOT_TOKEN"], int(turn["chat_id"]), followup)
        except Exception as error:
            detail = f"{type(error).__name__}: {error}"
            control_turns.mark_followup_delivery_unknown(identifier, detail)
            cli.audit("control_turn.followup_delivery_unknown", turn_id=identifier,
                      user_id=user_id, error=detail)
            return
        control_turns.mark_followup_delivered(identifier)
        conversation.append(user_id, "assistant", followup, source_id=f"{identifier}:deep")
        cli.audit("control_turn.followup_delivered", turn_id=identifier, user_id=user_id)
    except Exception as error:
        detail = f"{type(error).__name__}: {error}"
        control_turns.mark_deep_retry(identifier, detail)
        cli.audit("control_turn.deep_retry_queued", turn_id=identifier, user_id=user_id, error=detail)


def _reap(active: dict[int, str]) -> None:
    for pid in list(active):
        finished, _ = os.waitpid(pid, os.WNOHANG)
        if finished:
            control_turns.release_reservation(active[pid], os.getpid())
            active.pop(pid, None)


def main() -> None:
    cli.initialize()
    active: dict[int, str] = {}
    stopping = False

    def stop(_signal: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while not stopping:
        _reap(active)
        control_turns.recover_interrupted()
        while True:
            identifier = control_turns.reserve_next(os.getpid())
            if not identifier:
                break
            pid = os.fork()
            if pid == 0:
                signal.signal(signal.SIGTERM, signal.SIG_DFL)
                signal.signal(signal.SIGINT, signal.SIG_DFL)
                claimed = control_turns.claim_reserved(identifier, os.getppid(), os.getpid())
                if claimed:
                    process_turn(identifier)
                os._exit(0)
            active[pid] = identifier
        time.sleep(0.25)
    for pid in active:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    while active:
        _reap(active)
        time.sleep(0.05)


if __name__ == "__main__":
    main()
