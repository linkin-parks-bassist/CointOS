"""Conversation preparation and Qwen-dialect output shared by native backends."""
from __future__ import annotations
import json
import os
import re


def prepare(conversation: dict) -> dict:
    messages = conversation["messages"]
    prefix = 0
    while prefix < len(messages) and messages[prefix].get("role") in ("system", "developer"):
        prefix += 1
    if prefix > 1 or (prefix and messages[0].get("role") == "developer"):
        if any(not isinstance(m.get("content"), str) for m in messages[:prefix]):
            raise ValueError("leading system/developer messages must contain text")
        messages = [{"role": "system", "content": "\n\n".join(m["content"] for m in messages[:prefix])},
                    *messages[prefix:]]
    body = {"messages": messages}
    # Empty interrupted steps are part of history, but have nothing to continue.
    if messages and messages[-1].get("role") == "assistant" and not any(
            messages[-1].get(key) for key in
            ("content", "reasoning_content", "reasoning", "tool_calls", "function_call", "refusal", "audio")):
        body.update(continue_final_message=False, add_generation_prompt=True)
    elif (len(messages) >= 2 and all(m.get("role") == "assistant" for m in messages[-2:])
            and not messages[-1].get("tool_calls")):
        body.update(continue_final_message=True, add_generation_prompt=False)
    if conversation.get("tools"):
        body["tools"] = conversation["tools"]
    if conversation.get("template"):
        body["chat_template_kwargs"] = conversation["template"]
    return body


def reader(conversation: dict, text: str, tokenize) -> dict:
    # A resumed assistant may already contain part of its reasoning. Detect
    # the opening of the current assistant, rather than requiring an empty
    # think block at the very end of the prompt.
    opening = "<think>\n"
    assistant = text.rsplit("<|im_start|>assistant\n", 1)[-1]
    reader = {"thinking": assistant.startswith(opening) and "</think>" not in assistant,
              "tools": conversation.get("tools") or []}
    if reader["thinking"] and conversation.get("reasoning_budget") is not None:
        # Resolve model-specific tokens; never assume another tokenizer's special IDs.
        marker = tokenize("</think>")
        if len(marker) != 1:
            raise ValueError("Reasoning budgets require a single closing-think special token")
        reader.update(reasoning_budget=conversation["reasoning_budget"], think_end=marker[0],
                      think_close=tokenize("\n</think>\n\n"))
        if assistant != opening:
            reader["reasoning_used"] = max(0, len(tokenize(assistant)) - len(tokenize(opening)))
    return reader


MARKERS = ("</think>", "<tool_call>")
END_OF_TURN = ("<|im_end|>", "<|endoftext|>")  # the model's end-of-turn tokens: the format, not the message


def _withhold(text: str) -> str:
    """Drop a trailing partial marker, which the next tokens may complete."""
    for cut in range(min(len(text), max(map(len, MARKERS)) - 1), 0, -1):
        if any(marker.startswith(text[-cut:]) for marker in MARKERS):
            return text[:-cut]
    return text


def _value(raw: str, schema: dict):
    if schema.get("type") == "string":
        return raw
    # XML parameters are scalar text, not necessarily JSON literals. Decode
    # booleans by their declared type so native True/False cannot become truthy strings.
    if schema.get("type") == "boolean" and raw.strip().lower() in ("true", "false"):
        return raw.strip().lower() == "true"
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def read(reader: dict, text: str, final: bool) -> dict:
    if not final:
        text = text.rstrip("\ufffd")  # a UTF-8 fragment must not be streamed as irreversible replacement text
    for end in END_OF_TURN:
        text = text.removesuffix(end)
    reasoning, rest = "", text
    if reader["thinking"]:
        if "</think>" in text:
            reasoning, rest = text.split("</think>", 1)
            rest = rest.lstrip("\n")
        else:
            reasoning, rest = (text if final else _withhold(text)), ""
    content, calling, calls = rest.partition("<tool_call>") if reader.get("allow_tools", True) else (rest, "", "")
    if not final and not calling:
        content = _withhold(content)
    phase = "reasoning" if reader["thinking"] and "</think>" not in text else "writing"
    thought = {"reasoning": reasoning.strip(), "content": content.rstrip("\n") if calling else content, "tool_calls": [],
               "phase": phase}
    if final and calling:
        schemas = {tool["function"]["name"]: tool["function"].get("parameters", {}).get("properties", {})
                   for tool in reader["tools"]}
        for index, call in enumerate(re.findall(r"<function=([^>\n]+)>\n(.*?)</function>", "<tool_call>" + calls, re.S)):
            name, body = call
            arguments = {key: _value(raw, schemas.get(name, {}).get(key, {}))
                         for key, raw in re.findall(r"<parameter=([^>\n]+)>\n(.*?)\n</parameter>", body, re.S)}
            thought["tool_calls"].append({"id": f"call_{index}_{os.urandom(4).hex()}", "type": "function",
                                          "function": {"name": name, "arguments": json.dumps(arguments)}})
    return thought
