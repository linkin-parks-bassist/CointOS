"""Semantic client for the admitted local inference proxy."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

from ecosystem.inference_proxy import cancel as cancel_proxy, validate_loopback_base


def request(request: dict, root: Path, clock) -> dict:
    if type(request) is not dict:
        raise ValueError("inference request must be a dictionary")
    lease = request.get("lease")
    credential = request.get("credential")
    if type(lease) is not dict or type(credential) is not bytes or len(credential) != 32:
        raise ValueError("an admitted lease and 32-byte credential are required")
    policy = json.loads((Path(root) / "config/model-policy.json").read_text(encoding="utf-8"))
    base = policy.get("inference_proxy", {}).get("proxy_base", "http://127.0.0.1:13306/v1")
    validate_loopback_base(base)
    body = {
        "model": lease["model_id"],
        "messages": request.get("messages", []),
        "max_tokens": lease["max_output_tokens"],
        "context_tokens": lease["context_tokens"],
        "stream": bool(request.get("stream", False)),
        "temperature": request.get("temperature", 0.35),
        "chat_template_kwargs": {"enable_thinking": False},
    }
    for field in ("tools", "tool_choice", "response_format"):
        if field in request:
            body[field] = request[field]
    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer " + credential.hex(),
        "X-Inference-Lease-Id": lease["lease_id"],
        "X-Inference-Owner-Identity": lease["request"]["owner_identity"],
    }
    raw_request = urllib.request.Request(
        base + "/chat/completions", data=json.dumps(body).encode("utf-8"), headers=headers)
    try:
        response = urllib.request.urlopen(
            raw_request, timeout=float(request.get("timeout", 180)))
        if body["stream"]:
            return {"stream": response, "lease_id": lease["lease_id"]}
        with response:
            decoded = json.load(response)
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:2000]
        raise RuntimeError(f"inference proxy HTTP {error.code}: {detail}") from error
    try:
        return decoded["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as error:
        raise RuntimeError("inference proxy returned an invalid completion") from error


def cancel(root: Path, lease_id: str, clock) -> dict:
    return cancel_proxy(Path(root), lease_id, clock)


def chat(model: str, messages: list[dict], max_tokens: int, timeout: int,
         temperature: float = 0.35, tools: list[dict] | None = None,
         response_format: dict | None = None, *, root: Path | None = None,
         inference_lease: dict | None = None, credential: bytes | None = None,
         clock=None) -> dict:
    """Compatibility semantic adapter; admission remains mandatory."""
    if root is None or inference_lease is None or credential is None:
        raise RuntimeError("direct chat is disabled; an admitted inference lease is required")
    if model != inference_lease.get("model_id") or max_tokens != inference_lease.get(
            "max_output_tokens"):
        raise ValueError("chat request does not match inference lease")
    semantic = {
        "lease": inference_lease, "credential": credential, "messages": messages,
        "temperature": temperature, "timeout": timeout,
    }
    if tools is not None:
        semantic.update(tools=tools, tool_choice="auto")
    if response_format is not None:
        semantic["response_format"] = response_format
    return request(semantic, root, clock or __import__("time").monotonic)
