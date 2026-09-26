"""Physical measurements of the machine and how they compare with the configured limits."""
from __future__ import annotations

from cointos.models import gpu_memory_gb


def _meminfo() -> dict[str, int]:
    values = {}
    with open("/proc/meminfo", encoding="ascii") as stream:
        for line in stream:
            name, rest = line.split(":", 1)
            values[name] = int(rest.split()[0]) * 1024
    return values


def _psi_full_avg10() -> float:
    with open("/proc/pressure/memory", encoding="ascii") as stream:
        for line in stream:
            if line.startswith("full"):
                return float(line.split()[1].split("=")[1])
    return 0.0


def sample() -> dict:
    memory = _meminfo()
    return {
        "mem_available_gb": round(memory["MemAvailable"] / 1e9, 1),
        "swap_used_gb": round((memory["SwapTotal"] - memory["SwapFree"]) / 1e9, 2),
        "psi_full_avg10": _psi_full_avg10(),
        "gpu_used_gb": gpu_memory_gb(),
    }


def breaches(limits: dict, measured: dict) -> list[str]:
    """The limits `measured` crosses (empty when the machine is healthy)."""
    found = []
    if measured["mem_available_gb"] < limits["min_mem_available_gb"]:
        found.append(f"available memory {measured['mem_available_gb']} GB < {limits['min_mem_available_gb']} GB")
    if measured["psi_full_avg10"] > limits["max_psi_full_avg10"]:
        found.append(f"memory pressure {measured['psi_full_avg10']} > {limits['max_psi_full_avg10']}")
    if measured["swap_used_gb"] > limits["max_swap_used_gb"]:
        found.append(f"swap {measured['swap_used_gb']} GB > {limits['max_swap_used_gb']} GB")
    return found
