"""Background delivery of model-presented agent notifications."""
from __future__ import annotations

import os
import time

from ecosystem import cli, conversation
from ecosystem.outbox import drain, mark_interrupted_deliveries_unknown
from ecosystem.presentation import humanize_notification
from ecosystem.telegram import reply


def deliver(user_id: int, message: str) -> None:
    friendly = humanize_notification(message, conversation.recent(user_id))
    reply(os.environ["AGENT_TELEGRAM_BOT_TOKEN"], user_id, friendly)
    conversation.append(user_id, "assistant", friendly)


def main() -> None:
    cli.initialize()
    mark_interrupted_deliveries_unknown()
    while True:
        try:
            delivered = drain(deliver)
        except Exception as error:
            cli.audit("notifier.error", error=f"{type(error).__name__}: {error}")
            delivered = 0
        time.sleep(0.5 if delivered else 2.0)


if __name__ == "__main__":
    main()
