"""Allowlisted Telegram transport with a fast generated response lane."""
from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from collections.abc import Callable

from ecosystem import cli, conversation, control_turns
from ecosystem.control_runtime import friendly_status, recent_errors_text, status_text
from ecosystem.inference import chat
from ecosystem.resource_control import active_chat_model


DISASTER_FALLBACK = "the local response system has failed to answer this for five minutes. that's not normal."
FAST_SYSTEM = """You are Cointelprofessional's fast conversational front. Reply to
David using the recent conversation in one brief, natural sentence. Match his
informal tone without sounding like a support bot. You may directly answer ordinary
conversation from context. This update is already durably accepted, and a separate
capable deep controller will inspect it after this reply; that controller has live
facts, tools, and agents. Never say the system cannot act merely because this fast
front has no tools. Speak as one coherent agent: do not mention stages, queues,
handoffs, or the deep controller unless David asks how it works. If the message needs
machine facts, sustained reasoning, or action, briefly say what needs checking or
that you will handle it, without claiming that the requested action has already
started, completed, been queued, or succeeded. Never invent live state,
timestamps, downloads, dispatches, or promises. You have no current machine or agent
facts in this prompt: when asked for any current, recent, or local fact, say briefly
that you need to check the exact record and never supply a candidate fact, number,
name, time, or status. Never emit JSON, internal IDs, a
stock status phrase, or the five-minute failure notice. Output only the sentence."""


def api(token: str, method: str, values: dict) -> dict:
    data = urllib.parse.urlencode(values).encode()
    with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/{method}", data=data, timeout=40) as response:
        result = json.load(response)
    if not result.get("ok"):
        raise RuntimeError(f"Telegram {method} failed")
    return result


def reply(token: str, chat_id: int, message: str) -> None:
    api(token, "sendMessage", {"chat_id": chat_id, "text": message[:4000]})


def generate_first_response(history: list[dict[str, str]], infer: Callable[..., dict] = chat) -> str:
    model = active_chat_model(os.environ.get("AGENT_TELEGRAM_FIRST_RESPONSE_MODEL", "Qwen3.5-4B-GGUF"))
    assistant = infer(model=model, messages=[{"role": "system", "content": FAST_SYSTEM}, *history[-6:]],
                      max_tokens=96, timeout=20, temperature=0.45)
    content = (assistant.get("content") or "").strip()
    if not content:
        raise RuntimeError("fast model returned no visible response")
    return content


def accept_update(token: str, update: dict, allowed: set[int],
                  send: Callable[[str, int, str], None] = reply,
                  infer: Callable[..., dict] = chat) -> bool:
    message = update.get("message", {})
    sender = message.get("from", {}).get("id")
    chat_id = message.get("chat", {}).get("id")
    if sender not in allowed:
        cli.audit("telegram.denied", user_id=sender, chat_id=chat_id)
        return True
    if chat_id is None or not message.get("text"):
        return True
    incoming = message["text"].strip()
    if not incoming:
        return True
    turn, created = control_turns.accept(update["update_id"], chat_id, sender, incoming)
    identifier = turn["id"]
    conversation.append(sender, "user", incoming, source_id=f"{identifier}:user")
    if not created and turn.get("front_state") == "generating":
        control_turns.mark_front_failed(identifier, "gateway restarted during fast generation")
        return True
    if not created and turn.get("front_state") == "sending":
        control_turns.mark_front_delivery_unknown(identifier, "gateway restarted during Telegram delivery")
        return True
    if turn.get("front_state") == "ready":
        initial = turn["initial_response"]
    elif turn.get("front_state") != "pending":
        return True
    else:
        cli.audit("control_turn.front_attempted", turn_id=identifier, user_id=sender)
        control_turns.mark_front_attempt(identifier)
        try:
            history = [entry for entry in conversation.recent(sender, max_messages=6, max_characters=2500)
                       if entry.get("content") != DISASTER_FALLBACK]
            initial = generate_first_response(history, infer=infer)
            control_turns.mark_front_ready(identifier, initial)
        except Exception as error:
            detail = f"{type(error).__name__}: {error}"
            control_turns.mark_front_failed(identifier, detail)
            cli.audit("control_turn.front_failed", turn_id=identifier, user_id=sender, error=detail)
            return True
    control_turns.mark_front_sending(identifier)
    try:
        send(token, chat_id, initial)
    except Exception as error:
        detail = f"{type(error).__name__}: {error}"
        control_turns.mark_front_delivery_unknown(identifier, detail)
        cli.audit("control_turn.front_delivery_unknown", turn_id=identifier,
                  user_id=sender, error=detail)
        return True
    control_turns.mark_front_delivered(identifier)
    conversation.append(sender, "assistant", initial, source_id=f"{identifier}:front")
    cli.audit("control_turn.front_delivered", turn_id=identifier, user_id=sender)
    return True


def deliver_due_disaster_fallbacks(token: str, send: Callable[[str, int, str], None] = reply,
                                   seconds: int = 300) -> int:
    delivered = 0
    for turn in control_turns.due_for_disaster(seconds=seconds):
        try:
            send(token, int(turn["chat_id"]), DISASTER_FALLBACK)
        except Exception as error:
            cli.audit("telegram.disaster_delivery_failed", turn_id=turn["id"],
                      error=f"{type(error).__name__}: {error}")
            continue
        control_turns.mark_disaster_delivered(turn["id"])
        conversation.append(int(turn["user_id"]), "assistant", DISASTER_FALLBACK,
                            source_id=f"{turn['id']}:disaster")
        cli.audit("telegram.disaster_fallback", turn_id=turn["id"], user_id=turn["user_id"])
        delivered += 1
    return delivered


def main() -> None:
    token = os.environ.get("AGENT_TELEGRAM_BOT_TOKEN")
    allowed = {int(value) for value in os.environ.get("AGENT_TELEGRAM_ALLOWED_USER_IDS", "").split(",") if value.strip()}
    if not token or not allowed:
        raise SystemExit("set AGENT_TELEGRAM_BOT_TOKEN and AGENT_TELEGRAM_ALLOWED_USER_IDS")
    cli.initialize()
    offset_path = cli.ROOT / "state/telegram-offset"
    offset = int(offset_path.read_text()) if offset_path.exists() else 0
    while True:
        try:
            deliver_due_disaster_fallbacks(token)
            updates = api(token, "getUpdates", {"offset": offset, "timeout": 15,
                                                 "allowed_updates": '["message"]'})["result"]
            for update in updates:
                try:
                    consumed = accept_update(token, update, allowed)
                except Exception as error:
                    cli.audit("telegram.accept_error", update_id=update.get("update_id"),
                              error=f"{type(error).__name__}: {error}")
                    break
                if not consumed:
                    break
                offset = update["update_id"] + 1
                cli.atomic_text(offset_path, str(offset))
        except Exception as error:
            cli.audit("telegram.error", error=f"{type(error).__name__}: {error}")
            time.sleep(5)


if __name__ == "__main__":
    main()
