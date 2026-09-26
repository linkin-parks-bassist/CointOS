"""A minimal stdio MCP client for the kt server, so Coin can use the same kt_* tools agents use.

A session is plain data: the server process, the next request id, the server
instructions, the function schemas and the set of tool names.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from cointos.config import load as load_config

SERVER = Path.home() / ".knowledge/.tools/kt-mcp"
CLOSE_SECONDS = load_config()["timeouts"]["mcp_close_seconds"]
PROTOCOL = "2025-06-18"
# Knowledge-root access changes are David's decision at a terminal, not Coin's.
EXCLUDED = {"kt_access_request", "kt_access_confirm", "kt_access_revoke"}


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


def open_session(project: Path) -> dict | None:
    """Start kt-mcp rooted at `project`, or return None so Coin stays available without it."""
    if not SERVER.is_file():
        return None
    process = subprocess.Popen(
        ["python3", str(SERVER)], cwd=project, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, text=True, env={**os.environ, "KT_MCP_PROJECT_DIR": str(project)})
    session = {"process": process, "next_id": 0}
    try:
        initialized = _request(session, "initialize", {
            "protocolVersion": PROTOCOL, "capabilities": {},
            "clientInfo": {"name": "cointos-coin", "version": "1"}})
        _send(session, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        listed = _request(session, "tools/list", {}).get("tools", [])
    except (OSError, RuntimeError, ValueError):
        close(session)
        return None
    session["instructions"] = initialized.get("instructions", "")
    session["tools"] = [
        {"type": "function", "function": {
            "name": tool["name"], "description": tool.get("description", ""),
            "parameters": tool.get("inputSchema") or {"type": "object", "properties": {}}}}
        for tool in listed if tool["name"] not in EXCLUDED]
    session["names"] = {tool["function"]["name"] for tool in session["tools"]}
    return session


def call(session: dict, name: str, arguments: dict) -> dict:
    result = _request(session, "tools/call", {"name": name, "arguments": arguments})
    text = "\n".join(item.get("text", "") for item in result.get("content", []) if item.get("type") == "text")
    return {"ok": not result.get("isError", False), "output": text}


def close(session: dict) -> None:
    process = session["process"]
    if process.poll() is None:
        process.stdin.close()
        try:
            process.wait(timeout=CLOSE_SECONDS)
        except subprocess.TimeoutExpired:
            process.kill()
