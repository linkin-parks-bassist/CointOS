"""Live Lemonade model and host-resource inventory for scheduling decisions."""
from __future__ import annotations
import json, os, urllib.request
from pathlib import Path

BASE = os.environ.get("LEMONADE_BASE_URL", "http://127.0.0.1:13305")

def _get(path: str) -> dict:
    with urllib.request.urlopen(BASE + path, timeout=10) as response:
        return json.load(response)

def snapshot() -> dict:
    registry = _get("/v1/models").get("data", [])
    try:
        health = _get("/api/v1/health").get("all_models_loaded", [])
    except Exception:
        health = []
    loaded = {item["model_name"]: item for item in health}
    memory = {}
    with open("/proc/meminfo", encoding="utf-8") as stream:
        for line in stream:
            key, value = line.split(":", 1)
            memory[key] = int(value.strip().split()[0])
    models = [{
        "id": item["id"], "size_gb": item.get("size"), "labels": item.get("labels", []),
        "context": item.get("context_length"), "loaded": item["id"] in loaded,
        "busy": loaded.get(item["id"], {}).get("is_busy", False),
    } for item in registry if item.get("downloaded") and "chat" in item.get("labels", [])]
    policy_path = Path(__file__).resolve().parents[1] / "config/model-policy.json"
    machine_path = Path(__file__).resolve().parents[1] / "config/machine-profile.json"
    machine = json.loads(machine_path.read_text(encoding="utf-8"))
    linux_total = round(memory.get("MemTotal", 0) / 1024 / 1024, 1)
    linux_available = round(memory.get("MemAvailable", 0) / 1024 / 1024, 1)
    return {
        "memory_available_gb": linux_available,
        "memory": {
            "physical_unified_gb": machine["physical_unified_memory_gb"],
            "firmware_gpu_reservation_gb": machine["firmware_gpu_reservation_gb"],
            "linux_total_gb": linux_total,
            "linux_available_gb": linux_available,
            "meaning": machine["memory_note"],
        },
        "load_average": list(os.getloadavg()), "models": models,
        "scheduling_policy": json.loads(policy_path.read_text(encoding="utf-8")),
    }

def ids(inventory: dict) -> list[str]:
    return [item["id"] for item in inventory["models"]]

def fallback(role: str, inventory: dict) -> tuple[str, str]:
    available = ids(inventory)
    preferences = (["Qwen3-Coder-30B-A3B-Instruct-GGUF", "Qwen3.8-27B-GGUF", "GLM-4.7-Flash-GGUF", "Qwen3.5-4B-GGUF"]
                   if role in {"worker", "refactorer"} else
                   ["Qwen3.8-27B-GGUF", "GLM-4.7-Flash-GGUF", "Qwen3-Coder-30B-A3B-Instruct-GGUF", "Qwen3.5-4B-GGUF"])
    chosen = next((model for model in preferences if model in available), available[0])
    return chosen, "Deterministic fallback based on role capability; live router choice unavailable."
