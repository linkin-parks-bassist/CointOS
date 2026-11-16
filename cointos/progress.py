"""Live progress at a glance: what each agent is reading/generating, how the lane is switching,
and whether the backend is speculating.

This is the runtime pulse behind a slow-looking factory: one snapshot of the ledger's thoughts,
the recent lane-switch mix from the event journal, and the model server's own counters. It reads
only; it never touches scheduling or the model.
"""
from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

from cointos import config as configuration


def _get(url: str, timeout: float) -> str | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.read().decode("utf-8", "replace")
    except Exception:
        return None


def backend_stats(config: dict, model: str, timeout: float = 1.5) -> dict | None:
    """The model server's speculation/prefill counters, or None when it cannot be reached."""
    lemonade = config.get("lemonade")
    if not lemonade:
        return None
    health = _get(lemonade.rstrip("/") + "/v1/health", timeout)
    if health is None:
        return None
    try:
        entry = next(e for e in json.loads(health).get("all_models_loaded", [])
                     if e.get("model_name") == model)
    except (ValueError, StopIteration):
        return None
    url = (entry.get("backend_url") or "").rstrip("/")
    base = url[:-3] if url.endswith("/v1") else url
    metrics = _get(base + "/metrics", timeout)
    if metrics is None:
        return None
    found = {}
    for line in metrics.splitlines():
        if line.startswith("llamacpp:"):
            name, _, value = line[len("llamacpp:"):].partition(" ")
            try:
                found[name] = float(value)
            except ValueError:
                pass
    draft = int(found.get("spec_decode_num_draft_tokens_total", 0))
    accepted = int(found.get("spec_decode_num_accepted_tokens_total", 0))
    return {"model": model,
            "draft_tokens": draft,
            "accepted_tokens": accepted,
            "acceptance": (accepted / draft) if draft else None,
            "prefill_tps": found.get("prompt_tokens_seconds"),
            "predicted_tokens": int(found.get("tokens_predicted_total", 0))}


def switch_summary(events_path: Path, minutes: float, now: float | None = None) -> dict:
    """Lane switches in the window, split into resident (no copy), snapshot restore, and cold."""
    now = time.time() if now is None else now
    since = now - max(0.0, minutes) * 60
    counts = {"total": 0, "resident": 0, "snapshot": 0, "cold": 0}
    try:
        lines = Path(events_path).read_text(errors="replace").splitlines()
    except OSError:
        return counts
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("event") != "switch" or event.get("at", 0) < since:
            continue
        counts["total"] += 1
        if event.get("mode") == "resident":
            counts["resident"] += 1
        elif event.get("restored"):
            counts["snapshot"] += 1
        else:
            counts["cold"] += 1
    return counts


def _agents(state: dict) -> list[dict]:
    thoughts = {t.get("agent"): t for t in (state.get("thoughts") or {}).values()}
    rows = []
    for agent in (state.get("agents") or {}).values():
        thought = thoughts.get(agent.get("id")) or {}
        prompt, read = thought.get("prompt") or 0, thought.get("read") or 0
        rows.append({
            "agent": agent.get("id"),
            "role": agent.get("role"),
            "state": "reading" if thought.get("reading") else agent.get("state"),
            "read": read,
            "prompt": prompt,
            "read_fraction": (read / prompt) if prompt else None,
            "generated": thought.get("generated") or 0,
            "rate": thought.get("rate"),
            "thoughts": agent.get("thoughts"),
        })
    return rows


def report(state: dict, config: dict, minutes: float = 5.0, as_json: bool = False,
           events_path: Path | None = None) -> str | dict:
    """A compact progress report; `as_json` returns the underlying data instead of text."""
    model = config.get("work_model") or ""
    memory = state.get("memory") or {}
    switches = switch_summary(events_path or (configuration.STATE / "events.jsonl"), minutes)
    backend = backend_stats(config, model) if model else None
    rows = _agents(state)
    data = {"minutes": minutes, "model": model, "switches": switches,
            "backend": backend, "memory": memory, "agents": rows}
    if as_json:
        return data

    lines = [f"CointOS progress · last {minutes:g}m"]
    if switches["total"]:
        lines.append(f"switches   {switches['total']}  (resident {switches['resident']} · "
                     f"snapshot {switches['snapshot']} · cold {switches['cold']})")
    else:
        lines.append("switches   0")
    if backend:
        if backend["draft_tokens"]:
            accept = f"{backend['acceptance'] * 100:.0f}%" if backend["acceptance"] is not None else "—"
            spec = f"spec {backend['accepted_tokens']}/{backend['draft_tokens']} ({accept})"
        else:
            spec = "spec none yet (still reading or unspeculated)"
        prefill = f"  prefill {backend['prefill_tps']:.0f} tok/s" if backend.get("prefill_tps") else ""
        lines.append(f"backend    {model}  {spec}{prefill}")
    if memory:
        lines.append(f"memory     headroom {memory.get('headroom_gb')} GB · available {memory.get('available_gb')} GB"
                     f" · psi {memory.get('psi')} · swap {memory.get('swap_gb')} GB")
    if not rows:
        lines.append("agents     none live")
        return "\n".join(lines)
    lines.append("")
    lines.append(f"{'AGENT':22} {'ROLE':15} {'STATE':9} {'READ':22} {'GEN':>6} {'RATE':>7}")
    for row in rows:
        read = f"{row['read']}/{row['prompt']}"
        if row["read_fraction"] is not None:
            read += f" ({row['read_fraction'] * 100:.0f}%)"
        rate = f"{row['rate']:.1f}" if isinstance(row["rate"], (int, float)) else "—"
        lines.append(f"{str(row['agent'])[:22]:22} {str(row['role'])[:15]:15} {str(row['state'])[:9]:9} "
                     f"{read:22} {row['generated']:>6} {rate:>7}")
    return "\n".join(lines)
