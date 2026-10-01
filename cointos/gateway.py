"""The gateway: the loopback HTTP server. It carries the OpenAI-compatible endpoint through which
every agent thinks, the dashboard, and the control API (`cointos/api.py`).

A chat request becomes a thought of its agent. The reply streams back as the thought
advances, however often the scheduler suspends it; while it waits for a lane, the stream
carries keep-alive comments.
"""
from __future__ import annotations

import json
import hashlib
import queue
import re
import secrets
import select
import socket
import threading
import time
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from cointos import api, journal, keys, lanes, lifecycle, memory, prompts
from cointos.config import ROOT
from cointos.state import ACTIVE, BACKEND, CONFIG, LOCK, L, STOPPING, now

KT_STARTUP = "Knowledge-tree startup:"


def stable_environment(messages: list[dict], agent: str) -> list[dict]:
    """Pin the parts of a managed task's system prefix that must survive later runs.

    The task-start date and complete system/developer prefix are properties of the conversation,
    not of whichever OpenCode server happens to serve its next request. The normalized prefix is
    stored once per digest in the ledger; tasks carry only its identity. Coin and the user pass through.
    """
    with LOCK:
        owner = L["agents"].get(agent)
        task = L["tasks"].get(owner["task"]) if owner else None
        if task is None:
            return messages
        date = task["prompt_date"]

    def environment(match):
        return re.sub(r"(?m)^([ \t]*)Today's date: [A-Za-z]{3} [A-Za-z]{3} \d{1,2} \d{4}$",
                      lambda line: line[1] + f"Task start date: {date} (fixed; run date for the current date and time)",
                      match[0])

    with LOCK:
        normalized = []
        for message in messages:
            content = message.get("content")
            if message.get("role") in ("system", "developer") and isinstance(content, str):
                content = re.sub(r"<env>\n.*?\n</env>", environment, content, flags=re.S)
                message = {**message, "content": content}
            normalized.append(message)

        system = [message for message in normalized if message.get("role") in ("system", "developer")]
        encoded = json.dumps(system, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        pinned_digest = task.get("system_context")
        pinned = L["system_contexts"].get(pinned_digest) if pinned_digest else None
        if pinned is None:  # includes migration from the earlier KT-suffix-only representation
            pinned_digest = hashlib.sha256(encoded.encode()).hexdigest()
            pinned = L["system_contexts"].setdefault(pinned_digest, encoded)
            task["system_context"] = pinned_digest
            task.pop("prompt_context", None)
        pinned_system = json.loads(pinned)
        result, inserted = [], False
        for message in normalized:
            if message.get("role") in ("system", "developer"):
                if not inserted:
                    result.extend(pinned_system)
                    inserted = True
            else:
                result.append(message)
        if not inserted:
            result = pinned_system + result
        digest = hashlib.sha256(pinned.encode()).hexdigest()
        try:
            journal.write({"at": now(), "event": "system prompt", "agent": agent,
                           "task": task["id"], "digest": digest,
                           "components": [{"role": message.get("role"),
                                           "digest": hashlib.sha256(json.dumps(message, sort_keys=True,
                                                        ensure_ascii=False, separators=(",", ":")).encode()).hexdigest(),
                                           "chars": len(str(message.get("content", "")))}
                                          for message in pinned_system]}, CONFIG["journal"]["bytes"])
            L.pop("journal_error", None)
        except OSError as error:
            L["journal_error"] = str(error)
        return result


SAMPLING = ("temperature", "top_p", "top_k", "min_p", "presence_penalty", "frequency_penalty", "repeat_penalty", "seed")


def identity(key: str) -> tuple[str, str, str]:
    """(agent, class, conversation) for a gateway key. Agents' conversations are their tasks,
    so a resumed task resumes its context; any key CointOS did not issue is the user's."""
    agent, klass = keys.owner(key)
    with LOCK:
        conversation = L["agents"][agent]["task"] if agent in L["agents"] else agent
    return agent, klass, conversation


def template_options(body: dict, agent: str) -> dict:
    options = dict(body.get("chat_template_kwargs") or {})
    if body.get("reasoning_effort") is not None:
        options["reasoning_effort"] = body["reasoning_effort"]
    with LOCK:
        owner = L["agents"].get(agent)
        task = L["tasks"].get(owner["task"]) if owner else None
        if task and task.get("reasoning_effort"):
            options["reasoning_effort"] = task["reasoning_effort"]
    if options.get("reasoning_effort") not in (None, "low", "medium", "xhigh"):
        raise ValueError("reasoning_effort must be low, medium or xhigh")
    return options


def render_request(body: dict, agent: str, model: str, template: dict) -> dict:
    """Render a request and identify any reusable fresh-role prefix by exact tokens.

    Prompt construction names the semantic boundary; the backend remains the authority on
    literal chat-template tokens. Rendering the same conversation with the assignment removed
    makes their common token prefix safe to share across sequential tasks of the same role.
    """
    messages = stable_environment(body["messages"], agent)
    conversation = {"messages": messages, "tools": body.get("tools"), "template": template,
                    "reasoning_budget": CONFIG.get("reasoning", {}).get("budgets", {}).get(
                        template.get("reasoning_effort"))}
    rendered = BACKEND.render(CONFIG, model, conversation)
    with LOCK:
        owner = L["agents"].get(agent)
        task = L["tasks"].get(owner["task"]) if owner else None
    if task is None or task.get("session") or task.get("review"):
        return rendered
    prefix = prompts.shared_launch_prefix(task)
    user = next((index for index in range(len(messages) - 1, -1, -1)
                 if messages[index].get("role") == "user"), None)
    if user is None or not isinstance(messages[user].get("content"), str) or not messages[user]["content"].startswith(prefix):
        return rendered
    prefix_messages = list(messages)
    prefix_messages[user] = {**messages[user], "content": prefix}
    prefix_rendered = BACKEND.render(CONFIG, model, {**conversation, "messages": prefix_messages})
    shared = lanes.common(rendered["tokens"], prefix_rendered["tokens"])
    if CONFIG["scheduler"]["shared_prefix_tokens"] <= shared < len(rendered["tokens"]):
        rendered["shared"] = shared
    return rendered


def chunk(reply_id: str, model: str, delta: dict, finish: str | None = None) -> bytes:
    return b"data: " + json.dumps({"id": reply_id, "object": "chat.completion.chunk", "created": int(time.time()),
                                   "model": model, "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}).encode() + b"\n\n"


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, *args):
        pass

    def reply(self, status: int, value, content_type="application/json"):
        body = value if isinstance(value, bytes) else json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/v1/models":
            return self.reply(200, {"object": "list", "data": [
                {"id": name, "object": "model", "owned_by": "cointos"} for name in CONFIG["models"]]})
        if path == "/api/ledger":
            with LOCK:
                return self.reply(200, L)
        if path == "/api/live":
            return self.live()
        if path in ("/", "/index.html"):
            return self.reply(200, (ROOT / "web/dashboard.html").read_bytes(), "text/html; charset=utf-8")
        self.reply(404, {"error": "not found"})

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
            if path == "/v1/chat/completions":
                return self.think(body)
            if path.startswith("/api/"):
                return self.reply(200, api.dispatch(path[5:], body))
            self.reply(404, {"error": "not found"})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except (ValueError, KeyError) as error:
            self.reply(400, {"error": str(error)})
        except Exception as error:  # a handler error must never take the daemon down
            traceback.print_exc()
            try:
                self.reply(500, {"error": f"{type(error).__name__}: {error}"})
            except OSError:
                pass

    def live(self):
        """Stream, `dashboard.live_hz` times a second, what changes fast: each agent's state, words, speed and
        progress, and the machine's memory. The page updates its agent cards and memory from it in
        place; the rest of the ledger it reads once a second."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            while True:
                measured = memory.measure()
                with LOCK:
                    frame = {"agents": L["agents"], "thoughts": L["thoughts"],
                             "memory": {**L["memory"], **measured}, "models": L["models"], "model_memory": L["model_memory"],
                             "saved_bytes": sum(s["bytes"] for s in L["snapshots"].values() if s["tier"] == "memory")}
                    data = json.dumps(frame)
                self.wfile.write(b"data: " + data.encode() + b"\n\n")
                self.wfile.flush()
                time.sleep(1 / CONFIG["dashboard"]["live_hz"])
        except OSError:
            return  # the page went away

    def think(self, body: dict):
        with LOCK:
            # Keep new callers at the admission gate during deployment. Repeated 503s
            # consume OpenCode's finite retries and leave it in exponential backoff
            # after replacement, where it can be mistaken for a silent agent.
            while L["quiescing"] and not STOPPING.is_set():
                if self.peer_closed():
                    return
                LOCK.wait(timeout=CONFIG["tick_seconds"])
            if STOPPING.is_set():
                return self.reply(503, {"error": {"message": "daemon restarting; retry shortly"}})
            ACTIVE["chats"] += 1
        try:
            return self.stream_thought(body)
        finally:
            with LOCK:
                ACTIVE["chats"] -= 1
                LOCK.notify_all()

    def peer_closed(self) -> bool:
        """Whether the request's socket has reached EOF without consuming its bytes."""
        try:
            return bool(select.select([self.connection], [], [], 0)[0]) and not self.connection.recv(1, socket.MSG_PEEK)
        except OSError:
            return True

    def stream_thought(self, body: dict):
        key = (self.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
        agent, klass, conversation = identity(key)
        model = {"work": CONFIG["work_model"], "front": CONFIG["front_model"]}.get(body.get("model"), body.get("model"))
        if model not in CONFIG["models"]:
            return self.reply(404, {"error": {"message": f"unknown model {model!r}"}})
        with LOCK:
            up = L["models"][model]["up"]
        if not up:
            return self.reply(503, {"error": {"message": f"{model} is not running right now"}})
        cap = CONFIG["scheduler"]["max_thought_tokens"]
        max_new = min(int(body.get("max_tokens") or body.get("max_completion_tokens") or cap), cap)
        template = template_options(body, agent)
        try:
            rendered = render_request(body, agent, model, template)
        except OSError as error:
            return self.reply(503, {"error": {"message": f"{model} is not reachable: {error}"}})
        sampling = {name: body[name] for name in SAMPLING if body.get(name) is not None}
        with LOCK:
            thought = lanes.begin(agent, klass, conversation, model, rendered, sampling, max_new)
            L["thoughts"][thought]["reasoning_effort"] = template.get("reasoning_effort")
            lifecycle.engaged(agent)
        try:
            return self.answer_thought(body, agent, model, rendered, thought)
        finally:
            lanes.cancel(thought)  # request ownership ends on every return or handler failure

    def answer_thought(self, body: dict, agent: str, model: str, rendered: dict, thought: str):
        run = lanes.RUNS[thought]
        stream = bool(body.get("stream"))
        reply_id = "chatcmpl-" + secrets.token_hex(8)
        if stream:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
        generated, sent, end = [], {"reasoning": "", "content": ""}, None
        try:
            while end is None:
                # HTTP/1.0 carries one request per connection. A readable socket
                # returning EOF means its caller left, even before a JSON reply.
                if self.peer_closed():
                    return
                try:
                    item = run["queue"].get(timeout=CONFIG["keepalive_seconds"])
                except queue.Empty:
                    if stream:
                        self.wfile.write(b": waiting for a lane\n\n")
                        self.wfile.flush()
                    continue
                if isinstance(item, dict):
                    end = item["end"]
                    continue
                generated += item
                current = BACKEND.read(CONFIG, model, rendered["reader"], generated, False)
                show(agent, current)
                if stream:
                    self.send_new(reply_id, model, current, sent)
        except OSError:
            return
        if end in ("failed", "cancelled"):
            error = {"error": {"message": "the thought failed on the model server; try again"}}
            return self.wfile.write(b"data: " + json.dumps(error).encode() + b"\n\n") if stream else self.reply(502, error)
        final = BACKEND.read(CONFIG, model, rendered["reader"], generated, True)
        show(agent, final)
        finish = "tool_calls" if final["tool_calls"] else "length" if end == "limit" else "stop"
        usage = {"prompt_tokens": len(rendered["tokens"]), "completion_tokens": len(generated),
                 "total_tokens": len(rendered["tokens"]) + len(generated)}
        if not stream:
            message = {"role": "assistant", "content": final["content"], "reasoning_content": final["reasoning"]}
            if final["tool_calls"]:
                message["tool_calls"] = final["tool_calls"]
            self.reply(200, {"id": reply_id, "object": "chat.completion", "created": int(time.time()),
                             "model": model, "usage": usage,
                             "choices": [{"index": 0, "message": message, "finish_reason": finish}]})
        else:
            try:
                self.send_new(reply_id, model, final, sent)
                for index, call in enumerate(final["tool_calls"]):
                    self.wfile.write(chunk(reply_id, model, {"tool_calls": [{"index": index, **call}]}))
                self.wfile.write(chunk(reply_id, model, {}, finish))
                if (body.get("stream_options") or {}).get("include_usage"):
                    self.wfile.write(b"data: " + json.dumps({"id": reply_id, "object": "chat.completion.chunk",
                                                             "model": model, "choices": [], "usage": usage}).encode() + b"\n\n")
                self.wfile.write(b"data: [DONE]\n\n")
            except OSError:
                pass

    def send_new(self, reply_id: str, model: str, thought: dict, sent: dict) -> None:
        """Stream what the thought says beyond what was already sent."""
        delta = {}
        for part, field in (("reasoning", "reasoning_content"), ("content", "content")):
            if thought[part].startswith(sent[part]) and len(thought[part]) > len(sent[part]):
                delta[field] = thought[part][len(sent[part]):]
                sent[part] = thought[part]
        if delta:
            self.wfile.write(chunk(reply_id, model, delta))
            self.wfile.flush()


def show(agent: str, thought: dict) -> None:
    """Keep the end of what an agent is saying, for the dashboard's live view of it."""
    with LOCK:
        if agent in L["agents"]:
            L["agents"][agent]["live"] = {"reasoning": thought["reasoning"][-CONFIG["dashboard"]["live_chars"]:],
                                          "content": thought["content"][-CONFIG["dashboard"]["live_chars"]:], "phase": thought["phase"]}


def serve() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", CONFIG["port"]), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True, name="gateway").start()
