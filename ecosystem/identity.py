"""Validation and fallback for model-generated agent names."""
from __future__ import annotations
import json, re, secrets, urllib.request
from ecosystem import cli


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
        if job.get("state") in {"queued", "ready", "running"} and job.get("agent_name"):
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

def generate(role: str, task: str) -> str:
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
    body = json.dumps({"model":policy["generator_model"],"messages":[{"role":"user","content":prompt}],"temperature":0.8,"max_tokens":80,"chat_template_kwargs":{"enable_thinking":False}}).encode()
    request = urllib.request.Request("http://127.0.0.1:13305/v1/chat/completions",data=body,headers={"Content-Type":"application/json","Authorization":"Bearer lemonade"})
    try:
        with urllib.request.urlopen(request,timeout=30) as response:
            content=json.load(response)["choices"][0]["message"]["content"]
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
