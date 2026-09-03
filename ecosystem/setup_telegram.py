"""Interactive first-time Telegram setup; keeps the bot token off the command line."""
from __future__ import annotations

import getpass
import json
import os
import stat
import urllib.parse
import urllib.request
from pathlib import Path


def api(token: str, method: str, values: dict | None = None) -> dict:
    data = urllib.parse.urlencode(values or {}).encode()
    with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/{method}", data=data, timeout=35) as response:
        result = json.load(response)
    if not result.get("ok"):
        raise RuntimeError(f"Telegram rejected {method}")
    return result["result"]


def main() -> None:
    print("Telegram bot setup\n")
    print("1. In Telegram, open the verified @BotFather account.")
    print("2. Send /newbot and follow its prompts.")
    print("3. Copy the token BotFather gives you. Treat it like a password.\n")
    token = getpass.getpass("Paste bot token (hidden): ").strip()
    bot = api(token, "getMe")
    username = bot["username"]
    print(f"\nConnected to @{username}.")
    print(f"Open https://t.me/{username}, tap Start, and send: hello")
    input("Then press Enter here... ")
    updates = api(token, "getUpdates", {"timeout": 10, "allowed_updates": '["message"]'})
    messages = [item["message"] for item in updates if item.get("message", {}).get("from", {}).get("id")]
    if not messages:
        raise SystemExit("No message arrived. Send the bot 'hello', wait a moment, and run setup again.")
    sender = messages[-1]["from"]
    user_id = sender["id"]
    label = sender.get("username") or sender.get("first_name") or str(user_id)
    answer = input(f"Allow Telegram user {label!r} (ID {user_id})? [y/N] ").strip().lower()
    if answer != "y":
        raise SystemExit("Nothing was saved.")
    config_dir = Path.home() / ".config/agent-ecosystem"
    config_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    config_path = config_dir / "telegram.env"
    config_path.write_text(
        f"AGENT_TELEGRAM_BOT_TOKEN={token}\nAGENT_TELEGRAM_ALLOWED_USER_IDS={user_id}\n",
        encoding="utf-8",
    )
    config_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    print(f"\nSaved {config_path} with owner-only permissions.")
    print("The gateway has not been enabled. Ask the ecosystem steward to enable it when ready.")


if __name__ == "__main__":
    main()

