"""The gateway: the loopback HTTP server. It carries the OpenAI-compatible endpoint through which
every agent thinks, the dashboard, and the control API (`cointos/api.py`).

A chat request becomes a thought of its agent. The reply streams back as the thought
advances, however often the scheduler suspends it; while it waits for a lane, the stream
carries keep-alive comments.
"""
from __future__ import annotations

import json
import gzip
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
import urllib.error
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from cointos import api, journal, keys, lanes, lifecycle, memory, projects, prompts, queues, scheduler, snapshot_cleanup, startup, tool_history, schema, performance, wakeups
from cointos.config import ROOT
from cointos.state import STARTUP, ACTIVE, BACKEND, CONFIG, LOCK, L, STOPPING, now, log, _snapshot

def coin_view():
    """An old busy report cannot keep a stopped Coin visible as active."""
    value = dict(L['coin'])
    identity = value.get('process')
    if identity:
        current = wakeups.process(identity['pid'])
        if (current is None or current['state'] == 'Z'
                or current['start_ticks'] != identity['start_ticks']
                or identity['boot_id'] != wakeups.boot_id()):
            value.update(busy=False, doing=None, gpu_since=None)
    return value


KT_STARTUP = "Knowledge-tree startup:"
TOOL_HISTORY: dict[str, dict] = {}  # private recovery-cache mirrors, never task authority


def _history_owner(agent):
    task = L['tasks'].get((L['agents'].get(agent) or {}).get('task'))
    if task and task.get('agent') == agent and task['status'] == 'running':
        return agent, task['id'], task.get('record_version', 1)


def _prepare_tool_history(agent, model, conversation, rendered):
    if CONFIG['models'][model].get('backend') != 'gufo':
        return rendered
    with LOCK:
        for gone in [a for a,r in TOOL_HISTORY.items() if _history_owner(a) != r['owner']]:
            del TOOL_HISTORY[gone]
        owner = _history_owner(agent)
        record = TOOL_HISTORY.get(agent)
    if owner is None:
        return rendered
    def owner_of(cached_owner):
        with LOCK:
            task = L['tasks'].get(cached_owner[1])
            # During startup, durable task ownership precedes process adoption.
            # Do not discard another run's cache merely because its server has
            # not yet been added to the new daemon's live-agent map.
            if (task and task['status'] in schema.ACTIVE and task.get('agent') == cached_owner[0]
                    and task.get('record_version', 1) == cached_owner[2]):
                return cached_owner
    try:
        if record is None:
            tool_history.prune_cache(ROOT, owner_of)
            record = tool_history.load_cache(ROOT, owner)
            if record is not None:
                with LOCK:
                    if _history_owner(agent) == owner:
                        TOOL_HISTORY[agent] = record
        candidate = tool_history.extend(CONFIG, model, record.get('record') if record else None,
                                        conversation, rendered)
    except Exception as error:
        candidate = rendered
        with LOCK:
            log('tool history unavailable', agent=agent, detail=f'{type(error).__name__}: {error}')
    with LOCK:
        if _history_owner(agent) != owner:
            return rendered
        if candidate is not rendered:
            log('tool history preserved', agent=agent, model=model, kept=len(record['record']['held']),
                tokens=len(candidate['tokens']), canonical_tokens=len(rendered['tokens']))
    return {**candidate, '_tool_history': {'owner': owner, 'conversation': conversation}}


def _remember_tool_history(agent, model, rendered, generated, parsed, delivered, end):
    context = rendered.get('_tool_history')
    if context is None:
        return
    with LOCK:
        if _history_owner(agent) != context['owner']:
            return
    try:
        record = tool_history.capture(CONFIG, model, context['conversation'], rendered['tokens'],
                                      generated, parsed, delivered) if end == 'done' else None
    except Exception as error:  # optional reuse never fails a model reply
        record = None
        with LOCK:
            log('tool history unavailable', agent=agent, detail=f'{type(error).__name__}: {error}')
    def still_owned():
        with LOCK:
            return _history_owner(agent) == context['owner']
    try:
        tool_history.store_cache(ROOT, context['owner'], record, still_owned)
    except Exception as error:
        with LOCK:
            log('tool history cache unavailable', agent=agent, detail=f'{type(error).__name__}: {error}')
    with LOCK:
        if _history_owner(agent) == context['owner']:
            if record is None:
                TOOL_HISTORY.pop(agent, None)
            else:
                TOOL_HISTORY[agent] = {'owner': context['owner'], 'record': record}
    return record


def _discard_tool_history(agent, rendered, record):
    context = rendered.get('_tool_history')
    if context is None or record is None:
        return
    with LOCK:
        if TOOL_HISTORY.get(agent) == {'owner': context['owner'], 'record': record}:
            TOOL_HISTORY.pop(agent, None)
    try:
        tool_history.discard_cache(ROOT, context['owner'], record)
    except Exception as error:
        with LOCK:
            log('tool history cache unavailable', agent=agent, detail=f'{type(error).__name__}: {error}')
# OpenCode environment lines that differ between tasks; the assignment states them instead.
TASK_ENVIRONMENT = re.compile(r"[ \t]*(Working directory|Workspace root folder|Is directory a git repo|Today's date):")
ENVIRONMENT_POINTER = "  Working directory, repository and task start date: stated in your assignment"


def pre_stop_check(body: dict, agent: str, final: dict) -> dict:
    """One read-only tool check before an unreceipted project run's plain final reply."""
    if final['tool_calls'] or body.get('tool_choice') not in (None, 'auto'):
        return final
    names = [t['function']['name'] for t in (body.get('tools') or [])
             if isinstance(t, dict) and t.get('type') == 'function'
             and isinstance(t.get('function'), dict) and isinstance(t['function'].get('name'), str)]
    tool = next((name for name in names if name == 'cointos_check_work' or name.endswith('_cointos_check_work')), None)
    if not tool:
        return final
    with LOCK:
        run = L['agents'].get(agent)
        task = L['tasks'].get(run['task']) if run else None
        if (not task or task['status'] != 'running' or task.get('agent') != agent or task['role'] not in ('worker', 'manager', 'integrator')
                or task['place'] == 'system' or run.get('pre_stop_checked')):
            return final
        run['pre_stop_checked'] = True
        log('pre-stop check', task=task['id'], agent=agent)
    return {**final, 'tool_calls': [{'id': 'call-' + secrets.token_hex(12), 'type': 'function',
                                   'function': {'name': tool, 'arguments': '{}'}}]}


def stable_environment(messages: list[dict], agent: str) -> list[dict]:
    """Pin a managed task's system prefix and keep it identical across tasks.

    A fresh run's prompt is ordered from what varies least to what varies most, so the longest
    possible start is a cached state other tasks can restore: OpenCode's instructions, tools and
    skills (never), the knowledge-tree startup (per project), role guidance (per role), then the
    assignment (per task). OpenCode's `<env>` block would break that order, since it names the
    task's worktree, scope and date near the top; those lines are removed here and the assignment
    states them instead. The normalized prefix is pinned per task and stored once per digest in
    the ledger, so later runs of a conversation keep the prefix it started with.
    Coin and the user pass through.
    """
    with LOCK:
        owner = L["agents"].get(agent)
        task = L["tasks"].get(owner["task"]) if owner else None
        if task is None:
            return messages

    def environment(match):
        kept = [line for line in match[1].split("\n") if not TASK_ENVIRONMENT.match(line)]
        return "<env>\n" + "\n".join(kept + [ENVIRONMENT_POINTER]) + "\n</env>"

    with LOCK:
        normalized = []
        for message in messages:
            content = message.get("content")
            if message.get("role") in ("system", "developer") and isinstance(content, str):
                content = re.sub(r"<env>\n(.*?)\n</env>", environment, content, flags=re.S)
                # The knowledge-tree dictionary lists every leaf path word, so any tree edit would
                # change the prefix every new task shares; agents look it up with kt_dict instead.
                content = re.sub(r"=== kt dict ===\n[^\n]*\n", "", content)
                message = {**message, "content": content}
            normalized.append(message)

        system = [message for message in normalized if message.get("role") in ("system", "developer")]
        encoded = json.dumps(system, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        pinned_digest = task.get("system_context")
        pinned = L["system_contexts"].get(pinned_digest) if pinned_digest else None
        if pinned is None:  # the task's first request pins its system prefix
            pinned_digest = hashlib.sha256(encoded.encode()).hexdigest()
            pinned = L["system_contexts"].setdefault(pinned_digest, encoded)
            task["system_context"] = pinned_digest
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
        journal.write({"at": now(), "event": "system prompt", "agent": agent,
                       "task": task["id"], "digest": digest,
                       "components": [{"role": message.get("role"),
                                       "digest": hashlib.sha256(json.dumps(message, sort_keys=True,
                                                    ensure_ascii=False, separators=(",", ":")).encode()).hexdigest(),
                                       "chars": len(str(message.get("content", "")))}
                                      for message in pinned_system]}, CONFIG["journal"]["bytes"])
        return result


def stable_tools(tools, agent: str):
    """Pin a managed task's tool definitions at its first request, as its system prefix is pinned.

    The chat template renders tools near the start of the prompt, so a relaunched session that
    loaded newer tool schemas would diverge from every saved state and reread it whole.
    Ordinary tools remain pinned. CointOS's executable contracts must track its live MCP
    handlers, so those definitions deliberately refresh without discarding the session."""
    with LOCK:
        owner = L["agents"].get(agent)
        task = L["tasks"].get(owner["task"]) if owner else None
        if task is None or tools is None:
            return tools
        def owned(tool):
            return tool.get("function", {}).get("name", "").startswith("cointos_")
        pinned = L["system_contexts"].get(task.get("tool_context") or "")
        if pinned is not None:
            current = [t for t in tools if owned(t)]
            if current:
                refreshed, inserted = [], False
                for tool in json.loads(pinned):
                    if owned(tool):
                        if not inserted:
                            refreshed.extend(current)
                            inserted = True
                    else:
                        refreshed.append(tool)
                if not inserted:
                    refreshed.extend(current)
                encoded = json.dumps(refreshed, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
                if encoded != pinned:
                    task["tool_context"] = hashlib.sha256(encoded.encode()).hexdigest()
                    pinned = L["system_contexts"].setdefault(task["tool_context"], encoded)
        if pinned is None:
            # OpenCode puts its per-run temporary path in Bash's description,
            # ahead of every shared instruction. Keep that capability expressed
            # through the run's existing environment instead of its unique ID.
            tools = deepcopy(tools)
            # A role's CointOS tools must not split the common declarations.
            # Stable sorting retains each group's original order and schemas.
            tools.sort(key=owned)
            temporary = ROOT / 'state' / 'agents' / agent / 'scratch' / 'opencode'
            literal = f"Use `{temporary}` for temporary work outside the workspace."
            portable = ("Use `$COINTOS_SCRATCH/opencode` for temporary work outside the workspace. "
                        "Expand the environment variable before passing an absolute path to a tool.")
            for tool in tools:
                function = tool.get('function', {})
                if function.get('name') == 'bash' and isinstance(function.get('description'), str):
                    function['description'] = function['description'].replace(literal, portable)
            encoded = json.dumps(tools, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
            task["tool_context"] = hashlib.sha256(encoded.encode()).hexdigest()
            pinned = L["system_contexts"].setdefault(task["tool_context"], encoded)
        return json.loads(pinned)


SAMPLING = ("temperature", "top_p", "top_k", "min_p", "presence_penalty", "frequency_penalty", "repeat_penalty", "seed")


def identity(key: str, user: str | None = None) -> tuple[str, str, str]:
    """(agent, class, conversation) for a gateway key. Agents' conversations are their tasks,
    so a resumed task resumes its context; any key CointOS did not issue is the user's."""
    agent, klass = keys.owner(key)
    with LOCK:
        conversation = L["agents"][agent]["task"] if agent in L["agents"] else agent
    if agent == "coin" and user is not None:
        if not isinstance(user, str) or not user:
            raise ValueError("Coin user must be a nonempty string")
        conversation = "coin/" + hashlib.sha256(user.encode()).hexdigest()
    return agent, klass, conversation


def request_class(body: dict, owner_class: str) -> str:
    """A request may yield scheduling priority without changing its owner."""
    if 'request_class' not in body:
        return owner_class
    requested = body['request_class']
    if not isinstance(requested, str) or requested not in CONFIG['classes']:
        raise ValueError('request_class must name a configured scheduling class')
    if owner_class not in CONFIG['classes'] or scheduler.rank(CONFIG, requested) < scheduler.rank(CONFIG, owner_class):
        raise ValueError('request_class cannot raise the gateway owner scheduling priority')
    return requested


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


def render_request(body: dict, agent: str, model: str, template: dict, *, summary: bool = False) -> dict:
    """Render a request and identify the reusable starts of a fresh run by exact tokens.

    Prompt construction names the semantic boundaries; the backend remains the authority on
    literal chat-template tokens. Rendering the same conversation with the user message cut at
    each boundary makes each common token prefix safe to share across sequential tasks: of the
    project, of any role, and of the same role.
    """
    prefix_messages = body.get('cache_prefix_messages')
    if prefix_messages is not None and (agent != 'coin' or type(prefix_messages) is not int
                                       or not 1 <= prefix_messages < len(body['messages'])):
        raise ValueError('cache_prefix_messages requires a proper Coin message prefix')
    messages = stable_environment(body["messages"], agent)
    tools = stable_tools(body.get("tools"), agent)
    fallback = None
    if summary:
        if body.get("tools") or not messages or messages[-1].get("role") != "user":
            raise ValueError("structured summary requires a tool-free final user envelope")
        envelope = messages[-1].get("content")
        if not isinstance(envelope, str):
            raise ValueError("structured summary envelope must be text")
        packet = json.loads(envelope)
        if not isinstance(packet, dict) or set(packet) != {"c", "f"} or not all(
                isinstance(packet[key], str) and packet[key] for key in ("c", "f")):
            raise ValueError("invalid structured summary envelope")
        with LOCK:
            owner = L["agents"].get(agent)
            task = L["tasks"].get(owner["task"]) if owner else None
            if task is None:
                raise ValueError("structured summary requires a managed task")
            pinned = L["system_contexts"].get(task.get("tool_context") or "")
        fallback = stable_environment([{"role": "user", "content": packet["f"]}], agent)
        messages = messages[:-1] + [{"role": "user", "content":
                    "Summarize the preceding conversation using these instructions:\n" + packet["c"] +
                    "\n\nWork-state accuracy: Planned checks and measurements belong in Next Move, not Blocked. "
                    "Blocked requires an explicitly established obstacle preventing the next action; otherwise write (none). "
                    "Active contains genuinely unfinished work, not completed verification. "
                    "Do not invent pauses, dependencies or deployment conditions."}]
        tools = json.loads(pinned) if pinned is not None else None
        if tools is None:
            messages = fallback
    conversation = {"messages": messages, "tools": tools, "template": template,
                    "reasoning_budget": CONFIG.get("reasoning", {}).get("budgets", {}).get(
                        template.get("reasoning_effort"))}
    rendered = BACKEND.render(CONFIG, model, conversation)
    if summary:
        reserve = min(int(body.get("max_tokens") or body.get("max_completion_tokens")
                          or CONFIG["scheduler"]["max_thought_tokens"]), CONFIG["scheduler"]["max_thought_tokens"])
        window = CONFIG["models"][model]["ctx_size"] // CONFIG["models"][model]["lanes"]
        if reserve <= 0:
            raise ValueError("structured summary output budget must be positive")
        if tools is not None and len(rendered["tokens"]) + reserve > window:
            rendered = BACKEND.render(CONFIG, model, {**conversation, "messages": fallback, "tools": None})
        rendered["reader"]["allow_tools"] = False  # declarations are for prefix rendering only
        return rendered
    rendered = _prepare_tool_history(agent, model, conversation, rendered)
    if agent == "coin" and messages and messages[0].get("role") == "system":
        # Coin's system prompt and tools never change. A snapshot ending before the user's text
        # lets every turn restore them instead of reading them cold; however short, it is worth
        # keeping, because the user is waiting.
        # Templates may require a user query even when finding the shared boundary.
        start = BACKEND.render(CONFIG, model, {**conversation, "messages":
                               [messages[0], {"role": "user", "content": ""}]})
        alternate = BACKEND.render(CONFIG, model, {**conversation, 'messages': [messages[0],
                                   {'role': 'assistant', 'content': ''}, {'role': 'user', 'content': ''}]})
        # An odd-sized trim can leave either role first. Save only the system
        # prefix common to both, excluding any first-message role header.
        shared = min(lanes.common(rendered['tokens'], start['tokens']),
                     lanes.common(start['tokens'], alternate['tokens']))
        if 0 < shared < len(rendered["tokens"]):
            rendered["shared"] = [shared]
        if prefix_messages is not None and prefix_messages > 1:
            history = BACKEND.render(CONFIG, model, {**conversation, 'messages':
                                     messages[:prefix_messages] + [{'role': 'user', 'content': ''}]})
            boundary = lanes.common(rendered['tokens'], history['tokens'])
            if shared < boundary < len(rendered['tokens']):
                rendered['retained_prefix'] = boundary
        return rendered
    with LOCK:
        owner = L["agents"].get(agent)
        task = L["tasks"].get(owner["task"]) if owner else None
    if task is None or task.get("session") or task.get("review"):
        return rendered
    tiers = prompts.shared_launch_tiers(task)
    user = next((index for index in range(len(messages) - 1, -1, -1)
                 if messages[index].get("role") == "user"), None)
    if user is None or not isinstance(messages[user].get("content"), str) or not messages[user]["content"].startswith(tiers[-1]):
        return rendered
    # One boundary per tier: hybrid-model state cannot be cut back, so a start is reusable by
    # another task only if a snapshot ends exactly there.
    boundaries = set()
    common_tools = [tool for tool in (tools or [])
                    if not tool.get('function', {}).get('name', '').startswith('cointos_')]
    if common_tools and len(common_tools) < len(tools):
        ordinary = BACKEND.render(CONFIG, model, {**conversation, 'tools': common_tools})
        shared = lanes.common(rendered['tokens'], ordinary['tokens'])
        if CONFIG['scheduler']['shared_prefix_tokens'] <= shared < len(rendered['tokens']):
            boundaries.add(shared)
    for prefix in tiers:
        prefix_messages = list(messages)
        prefix_messages[user] = {**messages[user], "content": prefix}
        prefix_rendered = BACKEND.render(CONFIG, model, {**conversation, "messages": prefix_messages})
        shared = lanes.common(rendered["tokens"], prefix_rendered["tokens"])
        if CONFIG["scheduler"]["shared_prefix_tokens"] <= shared < len(rendered["tokens"]):
            boundaries.add(shared)
    if boundaries:
        rendered["shared"] = sorted(boundaries)
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
        compressed = False
        for coding in self.headers.get("Accept-Encoding", "").split(","):
            name, *parameters = coding.strip().lower().split(";")
            if name != "gzip":
                continue
            try:
                quality = next((float(p.strip()[2:]) for p in parameters if p.strip().startswith("q=")), 1)
            except ValueError:
                quality = 0
            if 0 < quality <= 1 and len(body) >= 1024:
                body = gzip.compress(body, compresslevel=1)
                compressed = True
            break
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Vary", "Accept-Encoding")
            if compressed:
                self.send_header("Content-Encoding", "gzip")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass  # the client hung up (a closed dashboard tab); there is no one left to answer

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/v1/models":
            return self.reply(200, {"object": "list", "data": [
                {"id": name, "object": "model", "owned_by": "cointos"} for name in CONFIG["models"]]})
        if path == "/api/ledger":
            with LOCK:
                snapshot = _snapshot({**L, "performance": performance.snapshot(), "coin": coin_view(), "startup": dict(STARTUP), "gateway_coin": startup.coin_digest(keys.OWNERS), "queue": queues.view(),
                                     "project_about": {p["name"]: projects.about(p) for p in L["projects"]}})
            return self.reply(200, snapshot)
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
                    frame = {"agents": L["agents"], "thoughts": L["thoughts"], "coin": coin_view(), "performance": performance.snapshot(),
                             "memory": {**L["memory"], **measured}, "models": L["models"], "model_memory": L["model_memory"],
                             "saved_bytes": sum(s["bytes"] for s in L["snapshots"].values() if s["tier"] == "memory")
                                            + snapshot_cleanup.occupied('memory') * memory.GB}
                    data = json.dumps(frame)
                self.wfile.write(b"data: " + data.encode() + b"\n\n")
                self.wfile.flush()
                time.sleep(1 / CONFIG["dashboard"]["live_hz"])
        except OSError:
            return  # the page went away

    def think(self, body: dict):
        with LOCK:
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
        if keys.ended(key):
            return self.reply(410, {"error": {"message": "this agent run has ended"}})
        agent, klass, conversation = identity(key, body.get("user"))
        klass = request_class(body, klass)
        model = {"work": CONFIG["work_model"]}.get(body.get("model"), body.get("model"))
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
            summary = self.headers.get("X-CointOS-Summary")
            if summary not in (None, "structured-v1"):
                raise ValueError("unsupported summary protocol")
            rendered = render_request(body, agent, model, template, summary=bool(summary))
        except urllib.error.HTTPError as error:
            # A rejected template is not an outage. Retrying the same invalid
            # history only wastes time and hides the model server's diagnosis.
            if 400 <= error.code < 500:
                return self.reply(error.code, {"error": {"message": f"{model} rejected the request: {error.reason}"}})
            return self.reply(503, {"error": {"message": f"{model} is not reachable: {error}"}})
        except OSError as error:
            return self.reply(503, {"error": {"message": f"{model} is not reachable: {error}"}})
        sampling = {name: body[name] for name in SAMPLING if body.get(name) is not None}
        with LOCK:
            thought = lanes.begin(agent, klass, conversation, model, rendered, sampling, max_new)
            L["thoughts"][thought]["reasoning_effort"] = template.get("reasoning_effort")
            lifecycle.engaged(agent)
        try:
            return self.reply_thought(body, agent, model, rendered, thought)
        finally:
            lanes.cancel(thought)  # request ownership ends on every return or handler failure

    def reply_thought(self, body: dict, agent: str, model: str, rendered: dict, thought: str):
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
            return self.reply_model_error(stream, 'the thought failed on the model server; try again', 'model_failure')
        final = BACKEND.read(CONFIG, model, rendered["reader"], generated, True)
        parsed = deepcopy(final)
        if end != 'limit':
            final = pre_stop_check(body, agent, final)
            if not final['content'].strip() and not final['tool_calls']:
                log('incomplete model reply', agent=agent, model=model, generated=len(generated),
                    reasoning_chars=len(final.get('reasoning', '')))
                return self.reply_model_error(stream, 'the model ended without an answer or tool call; '
                                              'the response is incomplete', 'incomplete_response')
        show(agent, final)
        with LOCK:
            if agent in L["agents"]:  # its tools now run, silently, until the next request
                L["agents"][agent]["in_tools"] = bool(final["tool_calls"])
        finish = "tool_calls" if final["tool_calls"] else "length" if end == "limit" else "stop"
        usage = {"prompt_tokens": len(rendered["tokens"]), "completion_tokens": len(generated),
                 "total_tokens": len(rendered["tokens"]) + len(generated)}
        if not stream:
            message = {"role": "assistant", "content": final["content"], "reasoning_content": final["reasoning"]}
            if final["tool_calls"]:
                message["tool_calls"] = final["tool_calls"]
            # Publish the conditional cache before completion reaches the client:
            # its next fast tool/request must not race cache construction. It is
            # usable only if that request echoes this exact assistant response.
            prepared = _remember_tool_history(agent, model, rendered, generated, parsed, final, end)
            try:
                self.reply(200, {"id": reply_id, "object": "chat.completion", "created": int(time.time()),
                                 "model": model, "usage": usage,
                                 "choices": [{"index": 0, "message": message, "finish_reason": finish}]})
            except OSError:
                _discard_tool_history(agent, rendered, prepared)
                raise
        else:
            prepared = None
            try:
                self.send_new(reply_id, model, final, sent)
                delivered = {**final, **{part: sent[part] for part in ('content', 'reasoning')}}
                prepared = _remember_tool_history(agent, model, rendered, generated, parsed, delivered, end)
                for index, call in enumerate(final["tool_calls"]):
                    self.wfile.write(chunk(reply_id, model, {"tool_calls": [{"index": index, **call}]}))
                self.wfile.write(chunk(reply_id, model, {}, finish))
                if (body.get("stream_options") or {}).get("include_usage"):
                    self.wfile.write(b"data: " + json.dumps({"id": reply_id, "object": "chat.completion.chunk",
                                                             "model": model, "choices": [], "usage": usage}).encode() + b"\n\n")
                self.wfile.write(b"data: [DONE]\n\n")
            except OSError:
                _discard_tool_history(agent, rendered, prepared)
                return

    def reply_model_error(self, stream: bool, message: str, code: str):
        """A failed/incomplete model reply is never a successful assistant stop."""
        error = {'error': {'message': message, 'type': 'server_error', 'code': code}}
        if stream:
            self.wfile.write(b'data: ' + json.dumps(error).encode() + b'\n\n')
            self.wfile.flush()
        else:
            self.reply(502, error)

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
        holder = L["agents"].get(agent) or (L["coin"] if agent == "coin" else None)
        if holder is not None:
            live = holder.get("live") or {}
            phase_since = live.get("phase_since") if live.get("phase") == thought["phase"] else now()
            holder["live"] = {"reasoning": thought["reasoning"][-CONFIG["dashboard"]["live_chars"]:],
                              "content": thought["content"][-CONFIG["dashboard"]["live_chars"]:], "phase": thought["phase"],
                              "phase_since": phase_since}


def serve() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", CONFIG["port"]), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True, name="gateway").start()
