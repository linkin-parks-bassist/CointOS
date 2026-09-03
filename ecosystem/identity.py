"""Validation and fallback for model-generated agent names."""
from __future__ import annotations
import json, os, re, urllib.request
from ecosystem import cli

def active_names() -> set[str]:
    active = set()
    for path in (cli.ROOT / "state/jobs").glob("*.json"):
        job = json.loads(path.read_text(encoding="utf-8"))
        if job.get("state") in {"queued", "ready", "running"} and job.get("agent_name"):
            active.add(job["agent_name"])
    return active

def validate(name: str) -> str:
    path = cli.ROOT / "config/naming-policy.json"
    policy = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"maximum_characters":40,"fallback":"Nameless Dave"}
    cleaned = " ".join(name.strip().split())
    if len(cleaned) > policy["maximum_characters"] or not re.fullmatch(r"[A-Za-z][A-Za-z0-9 '\-]{1,39}", cleaned) or cleaned in active_names():
        return policy["fallback"]
    return cleaned

def generate(role: str, task: str) -> str:
    path = cli.ROOT / "config/naming-policy.json"
    if not path.exists(): return "Nameless Dave"
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
        return validate(json.loads(match.group(0))["name"] if match else policy["fallback"])
    except Exception as error:
        cli.audit("identity.generation_failed",role=role,error=f"{type(error).__name__}: {error}")
        return policy["fallback"]
