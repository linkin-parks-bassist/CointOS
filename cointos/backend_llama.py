"""Backend for Lemonade-managed llama-server: the only module that knows about either.

The core speaks in models, lanes, contexts and snapshots; this module turns those into
Lemonade's load API and llama-server's token completions and slot snapshots
(`how/does/lemonade/serve/models.md`). Facts it relies on:
- a completion with `n_predict: 0` leaves the lane holding exactly the tokens sent;
- a step reports its retained token count; a speculative tail beyond the returned
  token history is unknown state, even when the complete reply is valid;
- prompt preparation streams progress so a lost prefix can be abandoned within a batch;
  generation returns a complete bounded token vector, without parsing per-step UTF-8 text;
- the server can invalidate retained state. Its first progress report says how much it
  kept (`cache`), before it reads; checking a restored hybrid prefix must extend it by
  the pending real token so that verification does not itself discard the cache.
"""

from __future__ import annotations

import http.client
import json
import os
import re
import shlex
import shutil
import stat
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import backend_chat

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
    def tokenize(text):
        return _server(model, "/tokenize", {"content": text, "add_special": False, "parse_special": True},
                       config["timeouts"]["render_seconds"])["tokens"]
    text = _server(model, "/apply-template", backend_chat.prepare(conversation),
                   config["timeouts"]["server_seconds"])["prompt"]
    return {"tokens": tokenize(text), "reader": backend_chat.reader(conversation, text, tokenize)}


def can_continue(config: dict, model: str, held: list[int] | None, tokens: list[int]) -> bool:
    """The buffered completion endpoint needs a pending real token to avoid rewind."""
    return bool(held) and len(held) < len(tokens) and tokens[:len(held)] == held


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
    # Extend the known prefix by the pending real token while checking prompt progress.
    # Rechecking an equal-length restored prefix makes hybrid memory rewind without
    # an internal checkpoint and discards the cache. This extension establishes the
    # checkpoint the following buffered request needs to reevaluate its last token.
    prefill(config, model, lane, tokens, held)
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
    which is under the user's home, so `unspill` brings it back before a restore.)"""
    disk = Path(config["disk_snapshots"]).expanduser()
    disk.mkdir(parents=True, exist_ok=True)
    shutil.move(Path(config["snapshots"]) / _snapshot(name), disk / _snapshot(name))


def unspill(config: dict, name: str) -> None:
    """Move a snapshot from disk back to memory, where llama-server can restore it."""
    copy_back(config, name)
    os.remove(Path(config["disk_snapshots"]).expanduser() / _snapshot(name))


def copy_back(config: dict, name: str) -> None:
    """Copy into RAM; the snapshot owner retires the disk copy separately."""
    shutil.copyfile(Path(config["disk_snapshots"]).expanduser() / _snapshot(name), Path(config["snapshots"]) / _snapshot(name))
    os.chmod(Path(config["snapshots"]) / _snapshot(name), 0o644)


def forget(config: dict, name: str) -> None:
    for place in (Path(config["snapshots"]), Path(config["disk_snapshots"]).expanduser()):
        try:
            os.remove(place / _snapshot(name))
        except FileNotFoundError:
            pass


def cache_kind(config: dict, model: str | None) -> str:
    return 'llama'


def snapshot_path(config: dict, entry: dict) -> Path:
    name, tier = entry['name'], entry['tier']
    if not isinstance(name, str) or _snapshot(name) != name + '.bin':
        raise ValueError('invalid cache cleanup name')
    if tier not in ('memory', 'disk'):
        raise ValueError('invalid cache cleanup tier')
    return Path(config['snapshots' if tier == 'memory' else 'disk_snapshots']).expanduser() / _snapshot(name)


def delete_snapshot_file(config: dict, entry: dict) -> int:
    """Unlink one owned file; return its formerly allocated regular-file bytes."""
    path = snapshot_path(config, entry)
    try:
        info = path.lstat()
        os.remove(path)
    except FileNotFoundError:
        return 0
    return info.st_blocks * 512 if stat.S_ISREG(info.st_mode) else 0


def snapshot_files(config: dict, tier: str | None = None) -> list[dict]:
    entries = []
    for tier in (tier,) if tier else ('memory', 'disk'):
        place = Path(config['snapshots' if tier == 'memory' else 'disk_snapshots']).expanduser()
        try:
            paths = list(place.iterdir())
        except FileNotFoundError:
            continue
        for path in paths:
            if not path.name.endswith('.bin'):
                continue
            name = path.name[:-4]
            if _snapshot(name) != path.name:
                continue
            try:
                info = path.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
                entries.append({'backend': 'llama', 'tier': tier, 'name': name,
                                'bytes': info.st_size if stat.S_ISREG(info.st_mode) else 0})
    return entries


def recover_transfer(config: dict, name: str, expected_bytes: int) -> str | None:
    """Recover a completed immutable copy after the copying process has exited.

    Copy/move writes sequentially and removes its source only after completion.
    The native restore still validates its opaque payload before using it.
    """
    if type(expected_bytes) is not int or expected_bytes <= 0:
        return None
    places = [(tier, Path(config[key]).expanduser() / _snapshot(name))
              for tier, key in (('memory', 'snapshots'), ('disk', 'disk_snapshots'))]
    for tier, path in places:
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISREG(info.st_mode) and info.st_size == expected_bytes:
            for _, other in places:
                if other != path:
                    other.unlink(missing_ok=True)
            return tier
    return None


def forget_untracked(config: dict, memory_names: set[str], disk_names: set[str]) -> list[str]:
    """Remove abandoned cache files from CointOS's two dedicated cache directories."""
    removed = []
    for place, names in ((Path(config["snapshots"]), memory_names),
                         (Path(config["disk_snapshots"]).expanduser(), disk_names)):
        kept = {_snapshot(name) for name in names}
        for path in place.glob("*.bin"):
            if path.name in kept or not path.is_file():
                continue
            try:
                path.unlink()
                removed.append(str(path))
            except FileNotFoundError:
                pass
    return removed


# ---------------------------------------------------------------- reading a thought

def text(config: dict, model: str, tokens: list[int]) -> str:
    """The literal text of `tokens`."""
    return _server(model, "/detokenize", {"tokens": tokens}, config["timeouts"]["server_seconds"])["content"] if tokens else ""


def read(config: dict, model: str, reader: dict, tokens: list[int], final: bool) -> dict:
    return backend_chat.read(reader, text(config, model, tokens), final)
