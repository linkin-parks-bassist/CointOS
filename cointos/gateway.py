"""The gateway: the OpenAI-compatible endpoint through which every agent thinks, plus the
loopback API and the dashboard.

A chat request becomes a thought of its agent. The reply streams back as the thought
advances, however often the scheduler suspends it; while it waits for a lane, the stream
carries keep-alive comments.
"""
from __future__ import annotations

import json
import queue
import secrets
import threading
import time
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from cointos import lanes, memory, queues, work
from cointos.config import ROOT
from cointos.state import BACKEND, CONFIG, LOCK, L, STOPPING, log, save

SAMPLING = ("temperature", "top_p", "top_k", "min_p", "presence_penalty", "frequency_penalty", "repeat_penalty", "seed")


def identity(key: str) -> tuple[str, str, str]:
    """(agent, class, conversation) for a gateway key. Agents' conversations are their tasks,
    so a resumed task resumes its context; any key CointOS did not issue is David's."""
    agent, klass = work.KEY_OWNERS.get(key, ("user", "user"))
    with LOCK:
        conversation = L["agents"][agent]["task"] if agent in L["agents"] else agent
    return agent, klass, conversation


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
                return self.reply(200, api(path[5:], body))
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
        try:
            rendered = BACKEND.render(CONFIG, model, {"messages": body["messages"], "tools": body.get("tools"),
                                                      "template": body.get("chat_template_kwargs")})
        except OSError as error:
            return self.reply(503, {"error": {"message": f"{model} is not reachable: {error}"}})
        sampling = {name: body[name] for name in SAMPLING if body.get(name) is not None}
        thought = lanes.begin(agent, klass, conversation, model, rendered, sampling, max_new)
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
            lanes.cancel(thought)  # the asker is gone
            return
        if end == "failed":
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
            return self.reply(200, {"id": reply_id, "object": "chat.completion", "created": int(time.time()),
                                    "model": model, "usage": usage,
                                    "choices": [{"index": 0, "message": message, "finish_reason": finish}]})
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


class ApiError(ValueError):
    pass


def api(action: str, body: dict):
    """Control actions for the CLI, Coin and the dashboard."""
    with LOCK:
        if action == "halt":
            STOPPING.set()
            for agent_id in list(L["agents"]):
                work.stop_agent(agent_id, "system halted", requeue=True, charge=False)
            log("halt requested")
            save()
            LOCK.notify_all()
            return {"ok": True}
        if action == "stop":
            L["paused"] = True
            for agent_id in list(L["agents"]):
                work.stop_agent(agent_id, "stopped by David", requeue=True, charge=False)
            log("paused")
            save()
            return {"ok": True, "paused": True}
        if action == "return":
            work.send_back(L["tasks"][body["task"]], body["notes"])
            save()
            return {"ok": True}
        if action in ("accept", "finish", "replace"):
            task = L["tasks"][body["task"]]
            if action == "accept":
                work.accept(task, body["commit"])
            elif action == "finish":
                work.finish_manager(task)
            else:
                if task["kind"] != "decompose":
                    raise ApiError("only a decomposition manager replaces tasks")
                children = body["children"]
                if not children or not isinstance(children, list):
                    raise ApiError("children must list existing replacement item names")
                records = queues.records()
                for child in children:
                    if child == task["item"] or f"{task['place']}:{child}" not in records:
                        raise ApiError("replacement children must exist and exclude the parent")
                for r in records.values():
                    if r["project"] == task["place"] and task["item"] in r["depends"]:
                        r["depends"] = list(dict.fromkeys(d for dep in r["depends"]
                                                         for d in (children if dep == task["item"] else [dep])))
                queues.update(task["place"], task["item"], "done")
            save()
            queues.publish()
            return {"ok": True}
        if action == "forget-task":
            # Operator cleanup: the queue leaf and worktree must be removed separately.
            # Keep the daemon the only ledger writer, including when discarding test work.
            if not L["paused"] or L["agents"]:
                raise ApiError("pause and stop all agents before forgetting work")
            task_id = body["task"]
            task = L["tasks"].get(task_id)
            if task is not None:
                lanes.forget_owner(task_id)
                for lane in L["lanes"]:
                    if lane["resident"] == task_id:
                        lane["resident"] = None  # a later graceful stop must not save this owner again
                del L["tasks"][task_id]
                log("task forgotten", task=task_id)
            save()
            return {"ok": True}
        if action == "go":
            L["paused"] = False
            log("resumed")
            return {"ok": True, "paused": False}
        if action == "stop-agent":
            if body.get("agent") not in L["agents"]:
                raise ApiError(f"no live agent {body.get('agent')!r}")
            work.stop_agent(body["agent"], "stopped by David", requeue=body.get("requeue", False), charge=False)
            return {"ok": True}
        if action == "viewers":
            L["viewers_showing"] = bool(body.get("show"))
            log("viewers", showing=L["viewers_showing"])
            return {"ok": True, "showing": L["viewers_showing"]}
        if action == "queue":
            project = work.project_named(body.get("project", ""))
            item = queues.add(project, body.get("kind", "queued"), body["name"], body["brief"])
            log("queued", project=project["name"], item=item)
            save()
            queues.publish()
            return {"ok": True, "item": item}
    raise ApiError(f"unknown action {action!r}")


def serve() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", CONFIG["port"]), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True, name="gateway").start()
