"""Knowledge-tree tools for the control agent through the standard kt MCP server.

The control agent is not an MCP host, so this is a minimal stdio MCP client: it
starts the same `kt-mcp` server OpenCode agents use, exposes its tools as
function-calling schemas, and forwards calls. Tool semantics stay owned by kt.

A session is plain data: the server process, the next request id, the server
instructions, the function schemas, and the set of tool names.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

SERVER = Path(os.environ.get("COINTOS_KT_MCP", str(Path.home() / ".knowledge/.tools/kt-mcp")))
PROTOCOL = "2025-06-18"


def _send(session: dict, message: dict) -> None:
    session["process"].stdin.write(json.dumps(message) + "\n")
    session["process"].stdin.flush()


def _request(session: dict, method: str, params: dict) -> dict:
    session["next_id"] += 1
    identifier = session["next_id"]
    _send(session, {"jsonrpc": "2.0", "id": identifier, "method": method, "params": params})
    while True:
        line = session["process"].stdout.readline()
        if not line:
            raise RuntimeError(f"kt-mcp exited during {method}")
        message = json.loads(line)
        if message.get("id") != identifier or "method" in message:
            continue
        if "error" in message:
            raise RuntimeError(message["error"].get("message", "kt-mcp error"))
        return message.get("result") or {}


def open_session(project: Path) -> dict:
    """Start kt-mcp rooted at `project` and describe its tools."""
    process = subprocess.Popen(
        ["python3", str(SERVER)], cwd=project, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, text=True, env={**os.environ, "KT_MCP_PROJECT_DIR": str(project)},
    )
    session = {"process": process, "next_id": 0}
    try:
        initialized = _request(session, "initialize", {
            "protocolVersion": PROTOCOL, "capabilities": {},
            "clientInfo": {"name": "cointos-control", "version": "1"},
        })
        _send(session, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        listed = _request(session, "tools/list", {}).get("tools", [])
    except (OSError, RuntimeError, ValueError):
        close(session)
        raise
    session["instructions"] = initialized.get("instructions", "")
    session["tools"] = [
        {"type": "function", "function": {
            "name": tool["name"], "description": tool.get("description", ""),
            "parameters": tool.get("inputSchema") or {"type": "object", "properties": {}},
        }}
        for tool in listed
    ]
    session["names"] = {tool["function"]["name"] for tool in session["tools"]}
    return session


def call(session: dict, name: str, arguments: dict) -> dict:
    result = _request(session, "tools/call", {"name": name, "arguments": arguments})
    text = "\n".join(item.get("text", "") for item in result.get("content", []) if item.get("type") == "text")
    ok = not result.get("isError", False)
    from ecosystem import cli
    cli.audit("control.kt_tool", tool=name, ok=ok,
              target=arguments.get("address") or arguments.get("question"))
    return {"ok": ok, "output": text}


def close(session: dict) -> None:
    process = session["process"]
    if process.poll() is None:
        process.stdin.close()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


def open_tools(project: Path) -> dict | None:
    """Start the kt tools, or return None so Coin stays available without them."""
    try:
        return open_session(project) if SERVER.is_file() else None
    except (OSError, RuntimeError, ValueError):
        return None
