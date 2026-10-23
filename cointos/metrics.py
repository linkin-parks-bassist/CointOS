"""Pipeline effectiveness over a recent window, read from the bounded event journal.

`cointos metrics` reads the two journal files directly (no daemon needed), so it covers at most
what they still hold. It reports what the construction pipeline produced and what it spent on
recovery, including the brief check and packet test failures.
"""
from __future__ import annotations

from collections import Counter
import json
import time

from cointos import queues
from cointos.config import STATE



def events(since: float) -> list[dict]:
    found = []
    for name in ("events.jsonl.1", "events.jsonl"):
        try:
            lines = (STATE / name).read_text(errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if entry.get("at", 0) >= since:
                found.append(entry)
    return found


def kind(task: str) -> str:
    """A task's pipeline role from its id: worker item, or the scheduler task kind."""
    name = task.partition(":")[2]
    for prefix in queues.RESERVED_PREFIXES:
        if name.startswith(prefix):
            return prefix.rstrip("-")
    return name if name in ("garden", "tree-audit", "steward") or not name else "item"


def summary(entries: list[dict], hours: float) -> str:
    landed = Counter(e.get("stage", "?") for e in entries if e["event"] == "verified landing")
    rejected = Counter(e.get("stage", "?") for e in entries if e["event"] == "landing gate rejected")
    infeasible = [e for e in entries if e["event"] == "brief infeasible"]
    created = Counter(e.get('kind') or kind(e.get("task", "")) for e in entries if e["event"] == "task created")
    repairs = sum(bool(e.get('repair_origin') or ':operator-repair-' in e.get('task', ''))
                  for e in entries if e['event'] == 'task created')
    receipts = Counter((kind(e.get("task", "")), e.get("disposition")) for e in entries if e["event"] == "receipt")
    packet_failures = sum(1 for e in entries if e["event"] == "packet tests failed")
    total = sum(landed.values())
    first = min((e["at"] for e in entries), default=None)
    covered = (time.time() - first) / 3600 if first else 0.0
    lines = [f"Pipeline metrics, last {hours:g} h (journal covers {covered:.1f} h)", ""]
    lines.append("Landed by stage:      " + (", ".join(f"{s} {n}" for s, n in sorted(landed.items())) or "none"))
    lines.append("Gate returns:         " + (", ".join(f"{s} {n}" for s, n in sorted(rejected.items())) or "none"))
    lines.append(f"Infeasible briefs:    {len(infeasible)} caught at dispatch before any worker ran")
    lines.append(f"Worker items started: {created['item']}")
    lines.append(f"Recovery controllers: {repairs}")
    lines.append(f"Legacy manager passes: {created['decompose']}")
    lines.append(f"Planning assignments: {created['breakdown']}")
    lines.append(f"Integrations:         {created['integrate']}")
    blocked = sum(n for (k, d), n in receipts.items() if k == "item" and d == "blocked")
    complete = sum(n for (k, d), n in receipts.items() if k == "item" and d == "complete")
    lines.append(f"Worker receipts:      {complete} complete, {blocked} blocked")
    lines.append(f"Packet test failures: {packet_failures} sent straight back to their implementers")
    lines.append("")
    lines.append(f"Recoveries per landing: {(created['decompose'] + repairs) / total:.2f}" if total else
                 "Recoveries per landing: n/a (nothing landed)")
    lines.append(f"Implementation share of landings: {landed['implementation'] / total:.0%}" if total else
                 "Implementation share of landings: n/a")
    measured = [e for e in entries if e['event'] == 'agent ended' and 'generation_seconds' in e]
    if measured:
        for role in sorted({e['role'] for e in measured}):
            runs = [e for e in measured if e['role'] == role]
            lines.append(f"Recorded {role} generation: {sum(e['generation_seconds'] for e in runs):.0f}s / "
                         f"{sum(e['generation_tokens'] for e in runs)} tokens ({len(runs)} runs)")
    for e in infeasible[-5:]:
        lines.append(f"  infeasible {e.get('task')}: {', '.join(e.get('missing', []))}")
    return "\n".join(lines)


def report(hours: float) -> str:
    return summary(events(time.time() - hours * 3600), hours)
