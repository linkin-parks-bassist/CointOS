"""Viewers: terminal windows on the user's desktop, each showing one live agent.

A viewer is a window running `cointos view N`, which attaches OpenCode's live view to
whichever agent holds slot N in the ledger's `viewers`, and shows "idle" between agents.
The daemon gives each agent that has started a viewer: an idle open window if there is one
(so idle monitors are captured by new agents), else, while the user has asked for viewers
(`cointos view --all`), a new window, up to `max_viewers`. A window the user closes frees its slot.
"""
from __future__ import annotations

import subprocess

from cointos import opencode, wakeups
from cointos.config import ROOT
from cointos.state import CONFIG, L, log, now


def open_windows() -> set[int]:
    """The slots whose viewer window is running, from the processes carrying COINTOS_VIEWER."""
    return {int(slot) for slot in opencode.processes_by("COINTOS_VIEWER")}


def open_window(slot: int) -> None:
    command = [*CONFIG["viewers"]["terminal"], "env", f"COINTOS_VIEWER={slot}", str(ROOT / "bin/cointos"), "view", str(slot)]
    subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


def coin_active() -> bool:
    """Coin is working and its reported worker process still owns that report."""
    coin = L.get("coin") or {}
    identity = coin.get("process")
    if not coin.get("busy") or not isinstance(identity, dict):
        return False
    try:
        current = wakeups.process(identity.get("pid"))
        return bool(current is not None and current["state"] != "Z"
                    and current["start_ticks"] == identity.get("start_ticks")
                    and identity.get("boot_id") == wakeups.boot_id())
    except Exception:
        return False


def look_after(windows: set[int]) -> None:
    """Keep slots matched to live agents and open windows. Caller holds LOCK."""
    limit = CONFIG["viewers"]["max_viewers"]
    viewers, opening = L["viewers"], L["viewers_opening"]
    for slot, since in list(opening.items()):
        if int(slot) in windows or now() - since > CONFIG["viewers"]["opening_seconds"]:
            del opening[slot]
    for slot, agent in list(viewers.items()):
        if agent == "coin":
            if not coin_active() or (int(slot) not in windows and slot not in opening):
                del viewers[slot]
            continue
        if agent not in L["agents"] or (int(slot) not in windows and slot not in opening):
            del viewers[slot]  # its agent ended, or the user closed its window
    shown = set(viewers.values())
    if coin_active() and "coin" not in shown:
        idle = sorted(s for s in windows if str(s) not in viewers)
        slot = idle[0] if idle else None
        if slot is None and L["viewers_showing"] and len(windows | {int(s) for s in opening}) < limit:
            slot = min(set(range(limit)) - windows - {int(s) for s in opening} - {int(s) for s in viewers})
            opening[str(slot)] = now()
            try:
                open_window(slot)
            except OSError as error:
                log("viewer failed", slot=slot, error=str(error))
                del opening[str(slot)]
                slot = None
        if slot is not None:
            viewers[str(slot)] = "coin"
            log("viewer", slot=slot, agent="coin")
    shown = set(viewers.values())
    for agent_id, agent in L["agents"].items():
        if agent_id in shown or not agent.get("url") or not agent.get("session"):
            continue
        idle = sorted(s for s in windows if str(s) not in viewers)
        if idle:
            slot = idle[0]
        elif L["viewers_showing"] and len(windows | {int(s) for s in opening}) < limit:
            slot = min(set(range(limit)) - windows - {int(s) for s in opening} - {int(s) for s in viewers})
            opening[str(slot)] = now()
            try:
                open_window(slot)
            except OSError as error:
                log("viewer failed", slot=slot, error=str(error))
                del opening[str(slot)]
                continue
        else:
            continue
        viewers[str(slot)] = agent_id
        log("viewer", slot=slot, agent=agent_id)
