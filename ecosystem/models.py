"""Live Lemonade model and host-resource inventory for scheduling decisions."""
from __future__ import annotations
import json, os, urllib.request

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
    return {
        "memory_available_gb": round(memory.get("MemAvailable", 0) / 1024 / 1024, 1),
        "load_average": list(os.getloadavg()), "models": models,
    }

def ids(inventory: dict) -> list[str]:
    return [item["id"] for item in inventory["models"]]

def fallback(role: str, inventory: dict) -> tuple[str, str]:
    available = ids(inventory)
    preferences = (["Qwen3-Coder-30B-A3B-Instruct-GGUF", "GLM-4.7-Flash-GGUF", "Qwen3.5-4B-GGUF"]
                   if role in {"worker", "steward"} else
                   ["Qwen3.5-4B-GGUF", "GLM-4.7-Flash-GGUF"])
    chosen = next((model for model in preferences if model in available), available[0])
    return chosen, "Deterministic fallback based on role capability; live router choice unavailable."

