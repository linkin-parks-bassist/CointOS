"""Validation and fallback for model-generated agent names."""
from __future__ import annotations
import json, re, secrets
from ecosystem import cli
from ecosystem.inference import request as inference_request


def _policy() -> dict:
    path = cli.ROOT / "config/naming-policy.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"maximum_characters": 40, "fallback_prefix": "agent"}

def active_names() -> set[str]:
    active = set()
    for path in (cli.ROOT / "state/jobs").glob("*.json"):
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if job.get("state") in {"queued", "ready", "claimed", "runner_starting", "running"} and job.get("agent_name"):
            active.add(job["agent_name"])
    return active


def emergency_name(role: str = "agent") -> str:
    prefix = re.sub(r"[^a-z0-9]+", "-", role.lower()).strip("-") or "agent"
    prefix = prefix[:24]
    active = active_names()
    while True:
        candidate = f"{prefix}-{secrets.token_hex(3)}"
        if candidate not in active:
            return candidate

def validate(name: str) -> str:
    policy = _policy()
    cleaned = " ".join(name.strip().split())
    if len(cleaned) > policy["maximum_characters"] or not re.fullmatch(r"[A-Za-z][A-Za-z0-9 '\-]{1,39}", cleaned) or cleaned in active_names():
        return emergency_name(policy.get("fallback_prefix", "agent"))
    return cleaned

def generate(role: str, task: str, inference_context: dict | None = None) -> str:
    path = cli.ROOT / "config/naming-policy.json"
    if not path.exists():
        return emergency_name(role)
    policy = json.loads(path.read_text(encoding="utf-8"))
    prompt = f"""Invent one understated agent name for this assignment.
Role: {role}
Task: {task[:1000]}
Active names to avoid: {', '.join(sorted(active_names())) or 'none'}
Policy: {policy['style']}
Odd-name probability: {policy['odd_name_probability']}; alien-name probability:
{policy.get('alien_name_probability', 0.0)}; clever-pun probability:
{policy.get('clever_pun_probability', 0.0)}. Treat these as rare style hints, not
quotas, and do not force a joke that is not genuinely good.
Return JSON only: {{"name":"..."}}"""
    try:
        if not inference_context:
            raise RuntimeError("no admitted inference context")
        content = inference_request({
            **inference_context,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.8,
            "timeout": 30,
        }, cli.ROOT, __import__("time").monotonic)["content"]
        match=re.search(r"\{.*\}",content,re.DOTALL)
        if not match:
            raise ValueError("naming model returned no JSON object")
        generated = json.loads(match.group(0))["name"]
        cleaned = " ".join(generated.strip().split())
        if (len(cleaned) > policy["maximum_characters"]
                or not re.fullmatch(r"[A-Za-z][A-Za-z0-9 '\-]{1,39}", cleaned)
                or cleaned in active_names()):
            raise ValueError("naming model returned an invalid or active name")
        return cleaned
    except Exception as error:
        cli.audit("identity.generation_failed",role=role,error=f"{type(error).__name__}: {error}")
        return emergency_name(role)
