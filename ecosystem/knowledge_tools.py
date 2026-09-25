"""Knowledge-tree tools for the control agent through the standard kt MCP server.

The control agent is not an MCP host, so this is a minimal stdio MCP client: it
starts the same `kt-mcp` server OpenCode agents use, exposes its tools as
function-calling schemas, and forwards calls. Tool semantics stay owned by kt.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

SERVER = Path(os.environ.get("COINTOS_KT_MCP", str(Path.home() / ".knowledge/.tools/kt-mcp")))
PROTOCOL = "2025-06-18"


class KnowledgeTools:
    def __init__(self, project: Path):
        self._process = subprocess.Popen(
            ["python3", str(SERVER)], cwd=project, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, env={**os.environ, "KT_MCP_PROJECT_DIR": str(project)},
        )
        self._next_id = 0
        initialized = self._request("initialize", {
            "protocolVersion": PROTOCOL, "capabilities": {},
            "clientInfo": {"name": "cointos-control", "version": "1"},
        })
        self.instructions = initialized.get("instructions", "")
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self.tools = [
            {"type": "function", "function": {
                "name": tool["name"], "description": tool.get("description", ""),
                "parameters": tool.get("inputSchema") or {"type": "object", "properties": {}},
            }}
            for tool in self._request("tools/list", {}).get("tools", [])
        ]
        self.names = {tool["function"]["name"] for tool in self.tools}

    def _send(self, message: dict) -> None:
        self._process.stdin.write(json.dumps(message) + "\n")
        self._process.stdin.flush()

    def _request(self, method: str, params: dict) -> dict:
        self._next_id += 1
        identifier = self._next_id
        self._send({"jsonrpc": "2.0", "id": identifier, "method": method, "params": params})
        while True:
            line = self._process.stdout.readline()
            if not line:
                raise RuntimeError(f"kt-mcp exited during {method}")
            message = json.loads(line)
            if message.get("id") != identifier or "method" in message:
                continue
            if "error" in message:
                raise RuntimeError(message["error"].get("message", "kt-mcp error"))
            return message.get("result") or {}

    def call(self, name: str, arguments: dict) -> dict:
        result = self._request("tools/call", {"name": name, "arguments": arguments})
        text = "\n".join(item.get("text", "") for item in result.get("content", []) if item.get("type") == "text")
        return {"ok": not result.get("isError", False), "output": text}

    def close(self) -> None:
        if self._process.poll() is None:
            self._process.stdin.close()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()

    def __enter__(self) -> "KnowledgeTools":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


def open_tools(project: Path) -> KnowledgeTools | None:
    """Start the kt tools, or return None so Coin stays available without them."""
    try:
        return KnowledgeTools(project) if SERVER.is_file() else None
    except (OSError, RuntimeError, ValueError):
        return None
