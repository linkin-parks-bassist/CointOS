"""Backend for Lemonade-managed llama-server: the only module that knows about either.

The core speaks in models, lanes, contexts and snapshots; this module turns those into
Lemonade's load API and llama-server's token completions and slot snapshots
(`how/does/lemonade/serve/models.md`). Facts it relies on:
- a completion with `n_predict: 0` leaves the lane holding exactly the tokens sent;
- a step reports its retained token count; a speculative tail beyond the returned
  token history is unknown state, even when the complete reply is valid;
- prompt preparation streams progress so a lost prefix can be abandoned within a batch;
  generation returns a complete bounded token vector, without parsing per-step UTF-8 text;
- the server can drop a lane's state between requests (seen after a restore, without any
  warning). Its first progress report says how much it kept (`cache`), before it reads.
"""

from __future__ import annotations

import http.client
import json
import os
import re
import shlex
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

class Lost(Exception):
    """The server no longer holds the context the lane was known to hold, so this request
    would read it all again: an unbounded step. Raised before the read starts."""


_urls: dict[str, str] = {}  # model -> its llama-server, as last reported by Lemonade

# Native token steps have no chat message to parse. In b10723, even /completion
# otherwise runs the UTF-8 chat parser on each isolated step's text; a continuation
# byte at a step boundary is valid token history but invalid standalone text.
TOKEN_PARSER = json.dumps({"parsers": [{"type": "epsilon"}], "rules": {}, "root": 0})
TOKEN_FIELDS = ["tokens", "stop", "stop_type", "tokens_predicted", "tokens_cached", "timings"]


def _call(url: str, body: dict | None, timeout: float):
    request = urllib.request.Request(url, None if body is None else json.dumps(body).encode(),
                                     {"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def _server(model: str, path: str, body: dict | None, timeout: float):
    return _call(_urls[model] + path, body, timeout)


# ---------------------------------------------------------------- models

def _wanted_args(config: dict, shape: dict) -> str:
    return f"--parallel {shape['lanes']} {shape['args']} --slot-save-path {config['snapshots']}"


def _problems(config: dict, shape: dict, entry: dict | None) -> list[str]:
    if entry is None or not entry.get("loaded"):
        return ["not loaded"]
    argv = entry.get("launch_command") or []

    def value(flag):
        return argv[argv.index(flag) + 1] if flag in argv[:-1] else None

    problems = [] if value("--ctx-size") == str(shape["ctx_size"]) else [f"ctx-size {value('--ctx-size')}"]
    wanted = shlex.split(_wanted_args(config, shape))
    for index, token in enumerate(wanted):
        if token.startswith("--"):
            following = wanted[index + 1] if index + 1 < len(wanted) and not wanted[index + 1].startswith("--") else None
            if token not in argv or (following is not None and value(token) != following):
                problems.append(f"{token} {value(token)}")
    return problems


def models(config: dict) -> dict[str, dict]:
    """Each configured model: {"lanes": n} when loaded in its configured shape, else {"problems": [...]}."""
    health = {entry["model_name"]: entry
              for entry in _call(config["lemonade"] + "/api/v1/health", None, config["timeouts"]["lemonade_health_seconds"])["all_models_loaded"]}
    found = {}
    for name, shape in config["models"].items():
        problems = _problems(config, shape, health.get(name))
        if problems:
            found[name] = {"problems": problems}
        else:
            _urls[name] = health[name]["backend_url"].removesuffix("/v1").rstrip("/")
            found[name] = {"lanes": shape["lanes"]}
    return found


def budget(config: dict) -> dict | None:
    """The model server's own memory allowance, when it runs under one: {"limit_gb", "used_gb"}.
    Lemonade's cgroup (`server_cgroup`) is charged for everything llama-server holds, snapshot
    files in /dev/shm included, and systemd-oomd kills it when it overflows into swap. Used is
    what the kernel cannot simply drop (anonymous and shared memory); page cache, such as the
    model files, it reclaims cheaply."""
    group = Path(config["server_cgroup"])
    try:
        limit = (group / "memory.high").read_text().strip()
        if limit == "max":
            limit = (group / "memory.max").read_text().strip()
        stat = dict(line.split() for line in (group / "memory.stat").read_text().splitlines())
        used = int(stat["anon"]) + int(stat["shmem"])
    except (OSError, ValueError, KeyError):
        return None
    return None if limit == "max" else {"limit_gb": round(int(limit) / 1e9, 1), "used_gb": round(used / 1e9, 1)}


def launch(config: dict, name: str) -> None:
    """Load `name` in its configured shape. A failed load can make Lemonade evict every model."""
    shape = config["models"][name]
    Path(config["snapshots"]).mkdir(mode=0o777, parents=True, exist_ok=True)
    os.chmod(config["snapshots"], 0o777)  # llama-server runs as the lemonade user and writes here
    kill(config, name)
    _call(config["lemonade"] + "/v1/load", {
        "model_name": name, "ctx_size": shape["ctx_size"], "llamacpp_args": _wanted_args(config, shape),
        "merge_args": False, "save_options": False, "pinned": True}, config["timeouts"]["model_launch_seconds"])
    problems = models(config)[name].get("problems")
    if problems:
        raise RuntimeError(f"{name} launched in the wrong shape: {'; '.join(problems)}")


def kill(config: dict, name: str) -> None:
    try:
        _call(config["lemonade"] + "/v1/unload", {"model_name": name}, config["timeouts"]["model_kill_seconds"])
    except urllib.error.HTTPError as error:
        if error.code != 404:  # 404: it was not loaded
            raise


# ---------------------------------------------------------------- contexts

def render(config: dict, model: str, conversation: dict) -> dict:
    """A conversation ({"messages", "tools", "template"}) as context tokens, plus what `read`
    needs to interpret the thought that follows them."""
    body = {"messages": conversation["messages"]}
    if conversation.get("tools"):
        body["tools"] = conversation["tools"]
    if conversation.get("template"):
        body["chat_template_kwargs"] = conversation["template"]
    text = _server(model, "/apply-template", body, config["timeouts"]["server_seconds"])["prompt"]
    tokens = _server(model, "/tokenize", {"content": text, "add_special": False, "parse_special": True},
                     config["timeouts"]["render_seconds"])["tokens"]
    reader = {"thinking": text.endswith("<think>\n"), "tools": conversation.get("tools") or []}
    if reader["thinking"] and conversation.get("reasoning_budget") is not None:
        # Resolve model-specific tokens; never assume another tokenizer's special IDs.
        def tokenize(value):
            return _server(model, "/tokenize", {"content": value, "add_special": False, "parse_special": True},
                           config["timeouts"]["render_seconds"])["tokens"]
        marker = tokenize("</think>")
        if len(marker) != 1:
            raise ValueError("Reasoning budgets require a single closing-think special token")
        reader.update(reasoning_budget=conversation["reasoning_budget"], think_end=marker[0],
                      think_close=tokenize("\n</think>\n\n"))
    return {"tokens": tokens, "reader": reader}


def prefill(config: dict, model: str, lane: int, tokens: list[int], held: int) -> None:
    """Read a bounded prefix, checking both initial cache retention and final state.

    Prompt progress can abandon a lost prefix before an unbounded reread. The
    sampled token from an n_predict=0 request is discarded; only its prompt is held.
    """
    target = urllib.parse.urlparse(_urls[model])
    connection = http.client.HTTPConnection(target.hostname, target.port, timeout=config["timeouts"]["server_seconds"])
    body = {"prompt": tokens, "n_predict": 0, "stream": True, "return_progress": True,
            "id_slot": lane, "cache_prompt": True, "return_tokens": True,
            "chat_parser": TOKEN_PARSER, "response_fields": TOKEN_FIELDS}
    try:
        connection.request("POST", "/completion", json.dumps(body), {"Content-Type": "application/json"})
        response = connection.getresponse()
        if response.status != 200:
            raise RuntimeError(f"{model} lane {lane}: HTTP {response.status} {response.read()[:300]!r}")
        for line in response:
            if not line.startswith(b"data: "):
                continue
            event = json.loads(line[6:])
            if "error" in event:
                raise RuntimeError(f"{model} lane {lane}: {event['error']}")
            progress = event.get("prompt_progress")
            if progress is not None:
                if progress["cache"] < held - config["scheduler"]["read_chunk_tokens"]:
                    raise Lost(f"{model} lane {lane} kept {progress['cache']} of {held} tokens")
            elif event.get("stop"):
                if event.get("tokens_cached") != len(tokens):
                    raise RuntimeError(f"{model} lane {lane}: prefill retained an unknown prefix {event}")
                return
        raise RuntimeError(f"{model} lane {lane}: completion stream ended without a stop event")
    finally:
        connection.close()


def think(config: dict, model: str, lane: int, tokens: list[int], held: int, max_new: int, sampling: dict,
          on_tokens) -> dict:
    """Extend a context on a lane known to hold `tokens[:held]` by up to `max_new` tokens, calling
    `on_tokens(new)` as they come. Returns {"tokens": the new tokens, "done": the thought ended,
    "rate": the model's own generation speed, "held": the exact known retained prefix}.
    Speculative decoding can retain draft tokens beyond a terminal reply; such state
    is cold, even though the complete reply itself is valid."""
    # Streamed text suppresses tokens inside incomplete UTF-8 characters. A bounded
    # token step needs the complete token vector, independent of text encoding.
    # Verify the prepared prefix with prompt progress before the buffered generation.
    prefill(config, model, lane, tokens[:-1], held)
    started = time.monotonic()  # prefix preparation does not spend the agent's generation budget
    event = _server(model, "/completion", {**sampling, "prompt": tokens, "n_predict": max_new,
                    "id_slot": lane, "cache_prompt": True, "stream": False, "return_tokens": True,
                    "chat_parser": TOKEN_PARSER,
                    "response_fields": TOKEN_FIELDS},
                    config["timeouts"]["server_seconds"])
    new = event.get("tokens") or []
    cached = event.get("tokens_cached")
    if (not event.get("stop") or event.get("tokens_predicted") != len(new)
            or (not new and event.get("stop_type") == "limit")
            or not isinstance(cached, int) or cached < 0):
        raise RuntimeError(f"{model} lane {lane}: incomplete token step {event}")
    if new:
        on_tokens(new)
    timings = event.get("timings") or {}
    rate = (timings["predicted_n"] * 1000 / timings["predicted_ms"]
            if timings.get("predicted_n", 0) >= 16 and timings.get("predicted_ms") else None)
    known = tokens + new
    return {"tokens": new, "done": event.get("stop_type") != "limit", "rate": rate,
            "held": known[:cached] if cached <= len(known) else [],
            "generation_seconds": time.monotonic() - started}


def _snapshot(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", name) + ".bin"


def save(config: dict, model: str, lane: int, name: str) -> dict:
    """Save the lane's context as snapshot `name`: {"tokens": how many it holds, "bytes": its size}."""
    saved = _server(model, f"/slots/{lane}?action=save", {"filename": _snapshot(name)}, config["timeouts"]["snapshot_seconds"])
    return {"tokens": saved["n_saved"], "bytes": os.path.getsize(Path(config["snapshots"]) / _snapshot(name))}


def restore(config: dict, model: str, lane: int, name: str) -> bool:
    try:
        return bool(_server(model, f"/slots/{lane}?action=restore", {"filename": _snapshot(name)},
                            config["timeouts"]["snapshot_seconds"]).get("n_restored"))
    except (OSError, ValueError):
        return False


def spill(config: dict, name: str) -> None:
    """Move a snapshot from memory to disk. (llama-server cannot read the disk directory,
    which is under David's home, so `unspill` brings it back before a restore.)"""
    disk = Path(config["disk_snapshots"]).expanduser()
    disk.mkdir(parents=True, exist_ok=True)
    shutil.move(Path(config["snapshots"]) / _snapshot(name), disk / _snapshot(name))


def unspill(config: dict, name: str) -> None:
    """Move a snapshot from disk back to memory, where llama-server can restore it."""
    shutil.copyfile(Path(config["disk_snapshots"]).expanduser() / _snapshot(name), Path(config["snapshots"]) / _snapshot(name))
    os.chmod(Path(config["snapshots"]) / _snapshot(name), 0o644)
    os.remove(Path(config["disk_snapshots"]).expanduser() / _snapshot(name))


def forget(config: dict, name: str) -> None:
    for place in (Path(config["snapshots"]), Path(config["disk_snapshots"]).expanduser()):
        try:
            os.remove(place / _snapshot(name))
        except FileNotFoundError:
            pass


# ---------------------------------------------------------------- reading a thought

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
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def read(config: dict, model: str, reader: dict, tokens: list[int], final: bool) -> dict:
    """What a thought says so far: {"reasoning", "content", "tool_calls", "phase"}, phase being
    "reasoning" while the model is still thinking, then "writing" (its message or tool calls).
    Before the thought is final, text that may still turn into a marker is held back, and tool
    calls are not given.

    The split mirrors how the Qwen template renders an assistant turn, so that the next render
    reproduces these tokens exactly and the lane state can be continued."""
    text = _server(model, "/detokenize", {"tokens": tokens}, config["timeouts"]["server_seconds"])["content"] if tokens else ""
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
    content, calling, calls = rest.partition("<tool_call>")
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
