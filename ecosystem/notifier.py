"""Background delivery of model-presented agent notifications."""
from __future__ import annotations

import os
import time

from ecosystem import cli, conversation
from ecosystem.outbox import drain, mark_interrupted_deliveries_unknown
from ecosystem.presentation import humanize_notification
from ecosystem.telegram import reply


def run_once(token: str, send=reply, present=humanize_notification) -> int:
    def prepare(user_id: int, message: str) -> str:
        return present(message, conversation.recent(user_id))

    def deliver(user_id: int, message: str) -> None:
        send(token, user_id, message)
        conversation.append(user_id, "assistant", message)

    return drain(deliver, prepare=prepare)


def main() -> None:
    token = os.environ.get("AGENT_TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("set AGENT_TELEGRAM_BOT_TOKEN")
    cli.initialize()
    mark_interrupted_deliveries_unknown()
    while True:
        try:
            delivered = run_once(token)
        except Exception as error:
            cli.audit("notifier.error", error=f"{type(error).__name__}: {error}")
            delivered = 0
        time.sleep(0.5 if delivered else 2.0)


if __name__ == "__main__":
    main()
