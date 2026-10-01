"""The vocabulary of tasks: their kinds, construction stages, reasoning efforts and run budgets.

Every fact about what a kind of task *is* lives in KINDS, and every consumer (the spawner,
places, prompts, receipts, the queue projection) reads it here rather than branching on the
kind's name. Pure data and validation.
"""
from __future__ import annotations

import math

# role: its prompt file (roles/<role>.md) and its GPU/admission identity.
# rank: where new work of this kind starts among other new work; lower first.
# scope: where it works: a project, a knowledge tree, the system (the installed runtime), or
#   either system or a project (an operator, chosen when requested).
# record: whether it carries a daemon queue record, whose state projects its settlement.
# receipts: the dispositions its run may submit with `cointos finish`. An integrator completes
#   only through a verified landing or incorporation and returns work with `cointos return`.
# lands: how its branch reaches main: "review" (an integrator reviews and lands it), "gate" (it
#   lands reviewed work through the daemon's landing gate) or "merge" (`cointos merge`).
#   System-scope tasks have no branch and land nothing.
KINDS = {
    "item": {"role": "worker", "rank": 4, "scope": "project", "record": True,
             "receipts": ("complete", "blocked"), "lands": "review"},
    "integrate": {"role": "integrator", "rank": 2, "scope": "project", "record": False,
                  "receipts": ("blocked",), "lands": "gate"},
    "decompose": {"role": "manager", "rank": 3, "scope": "project", "record": True,
                  "receipts": ("complete", "blocked"), "lands": "merge"},
    "breakdown": {"role": "manager", "rank": 5, "scope": "project", "record": True,
                  "receipts": ("complete", "blocked"), "lands": "merge"},
    "garden": {"role": "gardener", "rank": None, "scope": "tree", "record": False,
               "receipts": ("complete", "blocked"), "lands": "merge"},
    "tree-audit": {"role": "tree-auditor", "rank": 7, "scope": "tree", "record": False,
                   "receipts": ("complete", "blocked"), "lands": "merge"},
    "steward": {"role": "steward", "rank": 6, "scope": "system", "record": False,
                "receipts": ("complete", "blocked"), "lands": None},
    "test-audit": {"role": "test-auditor", "rank": 6, "scope": "system", "record": False,
                   "receipts": ("complete", "blocked"), "lands": None},
    "operator": {"role": "operator", "rank": 1, "scope": "either", "record": False,
                 "receipts": ("complete", "blocked"), "lands": "merge"},
}

# The queue kinds agents and the user submit, and the task kind that carries each.
QUEUE_KINDS = {"queued": "item", "urgent": "item", "command": "breakdown"}

STAGES = ("skeleton", "test-contract", "implementation", "integration")
EFFORTS = ("low", "medium", "xhigh")
ABILITIES = ("standard", "control", "network")
BUDGET_KEYS = ("generation_seconds", "generation_tokens")


def stage(value) -> str:
    if value not in STAGES:
        raise ValueError(f"stage must be one of {', '.join(STAGES)}")
    return value


def effort(value) -> str | None:
    if value is not None and value not in EFFORTS:
        raise ValueError(f"reasoning effort must be one of {', '.join(EFFORTS)}")
    return value


def default_effort(config: dict, task: dict) -> str:
    """One global baseline; test-contract workers, then a role with its own entry, deliberate
    differently. A task's own daemon-owned override always wins."""
    key = ("test-contract" if task["kind"] == "item" and task["stage"] == "test-contract"
           else KINDS[task["kind"]]["role"])
    return task.get("reasoning_effort") or config["reasoning"].get(key, config["reasoning"]["default"])


def budget(config: dict, overrides=None) -> dict:
    """A run budget: configured defaults with validated overrides."""
    if overrides is not None and (not isinstance(overrides, dict) or set(overrides) - set(BUDGET_KEYS)):
        raise ValueError("budget must contain generation_seconds and/or generation_tokens")
    result = {key: config["recovery"][key] for key in BUDGET_KEYS}
    result.update(overrides or {})
    for key, value in result.items():
        whole = key == "generation_tokens"
        if (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
                or value <= 0 or (whole and not isinstance(value, int))):
            raise ValueError(f"{key} must be a positive finite {'integer' if whole else 'number'}")
    return result


def abilities(value) -> list[str]:
    chosen = list(dict.fromkeys(value or ["standard"]))
    if not chosen or any(ability not in ABILITIES for ability in chosen):
        raise ValueError("abilities must be standard, control and/or network")
    return chosen
