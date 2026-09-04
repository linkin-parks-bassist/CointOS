"""Live inventory, model-mediated routing, and deterministic safety validation."""
from __future__ import annotations
import glob, json, os, re, subprocess, urllib.request
from pathlib import Path

from ecosystem.inference import chat

BASE = os.environ.get("LEMONADE_BASE_URL", "http://127.0.0.1:13305")
RESOURCE_POLICY_PATH = Path(__file__).resolve().parents[1] / "config/resource-policy.json"

def _get(path: str) -> dict:
    with urllib.request.urlopen(BASE + path, timeout=10) as response:
        return json.load(response)


def _post(path: str, payload: dict, timeout: float) -> dict:
    request = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Bearer lemonade"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
    return json.loads(raw) if raw else {}

def gpu_memory() -> dict:
    result = {"firmware_carveout_gb": None, "gtt_total_gb": None, "gtt_used_gb": None}
    for device in glob.glob("/sys/class/drm/card*/device"):
        uma = Path(device) / "uma"
        try:
            index = (uma / "carveout").read_text(encoding="utf-8").strip()
            options = (uma / "carveout_options").read_text(encoding="utf-8")
            match = re.search(rf"^{re.escape(index)}:.*\((\d+) (MB|GB)\)$", options, re.MULTILINE)
            if match:
                value = float(match.group(1)) / (1024 if match.group(2) == "MB" else 1)
                result["firmware_carveout_gb"] = round(value, 3)
            for name in ("gtt_total", "gtt_used"):
                raw = int((Path(device) / f"mem_info_{name}").read_text(encoding="utf-8"))
                result[f"{name}_gb"] = round(raw / 1024 ** 3, 1)
            return result
        except (FileNotFoundError, PermissionError, ValueError):
            continue
    return result

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
        "recipe": item.get("recipe"),
        "context": item.get("context_length"), "loaded": item["id"] in loaded,
        "loaded_context": loaded.get(item["id"], {}).get("recipe_options", {}).get("ctx_size"),
        "busy": loaded.get(item["id"], {}).get("is_busy", False),
        "pinned": loaded.get(item["id"], {}).get("pinned", False),
    } for item in registry if item.get("downloaded") and "chat" in item.get("labels", [])]
    policy_path = Path(__file__).resolve().parents[1] / "config/model-policy.json"
    machine_path = Path(__file__).resolve().parents[1] / "config/machine-profile.json"
    machine = json.loads(machine_path.read_text(encoding="utf-8"))
    linux_total = round(memory.get("MemTotal", 0) / 1024 / 1024, 1)
    linux_available = round(memory.get("MemAvailable", 0) / 1024 / 1024, 1)
    gpu = gpu_memory()
    return {
        "memory_available_gb": linux_available,
        "memory": {
            "physical_unified_gb": machine["physical_unified_memory_gb"],
            **gpu,
            "linux_total_gb": linux_total,
            "linux_available_gb": linux_available,
            "meaning": machine["memory_note"],
        },
        "load_average": list(os.getloadavg()), "models": models,
        "scheduling_policy": json.loads(policy_path.read_text(encoding="utf-8")),
    }

def ids(inventory: dict) -> list[str]:
    return [item["id"] for item in inventory["models"]]


def admission(model_id: str, inventory: dict) -> tuple[bool, str]:
    """Decide whether loading one more model preserves the machine reserve."""
    settings = json.loads(RESOURCE_POLICY_PATH.read_text(encoding="utf-8"))
    model = next((item for item in inventory.get("models", []) if item["id"] == model_id), None)
    if model is None:
        return False, f"model {model_id!r} is absent from the live local inventory"
    if model.get("loaded"):
        return True, "model is already resident; no load transient required"
    if model.get("recipe") in settings["admission"]["forbidden_recipes"]:
        return False, f"recipe {model.get('recipe')!r} is disabled by resource policy"
    reserve = float(settings["admission"]["desktop_and_control_reserve_gb"])
    transient = float(settings["admission"]["model_load_transient_reserve_gb"])
    size = model.get("size_gb")
    required_model = (float(size) if size is not None
                      else float(settings["admission"]["unknown_model_reserve_gb"]))
    available = float(inventory.get("memory_available_gb") or 0)
    required_available = reserve + transient + required_model
    if available < required_available:
        return False, (f"load needs {required_available:.1f} GiB available including the "
                       f"{reserve:.1f} GiB desktop/control reserve; only {available:.1f} GiB is available")
    memory = inventory.get("memory", {})
    gtt_used = memory.get("gtt_used_gb")
    gtt_limit = float(settings["gpu_boundary"]["gtt_limit_gb"])
    if gtt_used is not None and gtt_limit - float(gtt_used) < required_model + transient:
        return False, (f"load needs {required_model + transient:.1f} GiB GTT headroom; "
                       f"the bounded domain has only {gtt_limit - float(gtt_used):.1f} GiB")
    return True, (f"load admitted with {available - required_model - transient:.1f} GiB "
                  "remaining beyond model and transient demand")


def required_labels(role: str | None) -> set[str]:
    if role in {"coder", "refactorer"}:
        return {"coding", "tool-calling"}
    return {"tool-calling"}


def role_compatible(role: str | None, labels: set[str]) -> bool:
    if role in {"coder", "refactorer"}:
        return {"coding", "tool-calling"}.issubset(labels)
    if role in {"verifier", "auditor", "steward", "sole_survivor"}:
        return "tool-calling" in labels and bool(labels & {"reasoning", "coding"})
    return "tool-calling" in labels


def context_options(model: dict, inventory: dict) -> list[int]:
    """Return generous context choices that remain inside current host/GTT reserves."""
    settings = json.loads(RESOURCE_POLICY_PATH.read_text(encoding="utf-8"))
    dynamic = settings["dynamic_models"]
    supported = int(model.get("context") or dynamic["context_candidates"][1])
    if model.get("loaded"):
        loaded = int(model.get("loaded_context") or supported)
        return [min(supported, loaded)]
    available = float(inventory.get("memory_available_gb") or 0)
    gtt_used = float(inventory.get("memory", {}).get("gtt_used_gb") or 0)
    model_size = float(model.get("size_gb") or settings["admission"]["unknown_model_reserve_gb"])
    desktop = float(settings["admission"]["desktop_and_control_reserve_gb"])
    transient = float(settings["admission"]["model_load_transient_reserve_gb"])
    gtt_target = float(settings["normal"]["maximum_gtt_used_gb"])
    choices = []
    candidates = sorted(set(int(value) for value in dynamic["context_candidates"]
                            if int(value) <= supported))
    if supported not in candidates:
        candidates.append(supported)
    for tokens in sorted(candidates):
        context_gb = tokens * float(dynamic["estimated_kv_bytes_per_token"]) / 1024 ** 3
        if available < desktop + model_size + max(transient, context_gb):
            continue
        if gtt_used + model_size + context_gb > gtt_target:
            continue
        choices.append(tokens)
    return choices


def _json_object(text: str) -> dict:
    """Extract one routing object without accepting prose as a decision."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("router returned no JSON object")
        value = json.loads(stripped[start:end + 1])
    if not isinstance(value, dict):
        raise ValueError("router decision is not a JSON object")
    return value


def _routing_prompt(job: dict, inventory: dict) -> str:
    policy = inventory.get("scheduling_policy", {})
    control_model = policy.get("control_plane", {}).get("model")
    maximum_loaded = json.loads(RESOURCE_POLICY_PATH.read_text(encoding="utf-8"))["normal"]["maximum_loaded_models"]
    models = []
    safe_routes = []
    loaded_count = sum(1 for item in inventory.get("models", []) if item.get("loaded"))
    for item in inventory.get("models", []):
        load_admitted, load_reason = admission(item.get("id", ""), inventory)
        compatible = role_compatible(job.get("role"), set(item.get("labels", [])))
        contexts = context_options(item, inventory)
        models.append({
            "id": item.get("id"),
            "size_gb": item.get("size_gb"),
            "recipe": item.get("recipe"),
            "labels": item.get("labels", []),
            "loaded": bool(item.get("loaded")),
            "busy": bool(item.get("busy")),
            "role_compatible": compatible,
            "load_admitted": load_admitted,
            "load_reason": load_reason,
            "safe_context_tokens": contexts,
        })
        if compatible and item.get("loaded") and contexts:
            safe_routes.append({"action": "use_loaded", "model": item.get("id"),
                                "context_options": contexts})
        elif compatible and load_admitted and contexts and loaded_count < maximum_loaded:
            safe_routes.append({"action": "load", "model": item.get("id"),
                                "context_options": contexts})
    facts = {
        "role": job.get("role"),
        "task": str(job.get("task", ""))[:6000],
        "requested_model_hint": job.get("requested_model"),
        "requested_model_reason": job.get("requested_model_reason", ""),
        "prefer_models_other_than": job.get("prefer_models_other_than", []),
        "router_model": control_model,
        "maximum_loaded_models": maximum_loaded,
        "memory_available_gb": inventory.get("memory_available_gb"),
        "memory": inventory.get("memory", {}),
        "safe_routes": safe_routes,
        "models": models,
    }
    return f"""/no_think
You are the local model-routing control plane. Decide the target model for
one spawned agent from current task requirements and current machine state.

Return exactly one JSON object and no prose:
{{"action":"use_loaded|load|defer","model":"exact id or null","context_tokens":integer_or_null,"reason":"brief factual reason"}}

Policy:
- Keep only the small router/control model pinned. Every work model is unpinned.
- If a loaded work model is compatible and at least as capable as the task needs,
  reuse it as an inference upgrade instead of loading another model.
- Loading is appropriate only when the existing loaded models materially cannot do
  the job and the new model preserves the desktop/control and load-transient reserve.
- A caller's requested model is only a hint, never an instruction.
- Prefer verifier independence when alternatives exist.
- Compatibility is mandatory: coder/refactorer require both coding and tool-calling;
  verifier/auditor/steward require tool-calling plus reasoning or coding; absent,
  unknown, and other advisory roles require tool-calling. Never select a merely
  conversational model.
- Choose defer if evidence is insufficient or no safe compatible route exists.
- Never exceed {maximum_loaded} simultaneous loaded models including the pinned router.
- Select `use_loaded` only with a model whose `loaded` and `role_compatible`
  fields are both true. Select `load` only with a nonloaded model whose
  `role_compatible` and `load_admitted` fields are both true. Otherwise defer.
- The `safe_routes` list is mechanically prevalidated. Choose exactly one listed
  action/model pair and one of its exact context options, or choose defer. Allocate
  context generously according to likely task needs; rollover begins at 75 percent.
  Never reject a listed route merely because
  you speculate that it violates the model-count or memory limits; those checks
  have already been performed.

Current facts:
{json.dumps(facts, sort_keys=True)}"""


def route(job: dict, inventory: dict, infer=chat) -> dict:
    """Ask the pinned control model, then enforce non-negotiable safety constraints."""
    control_model = inventory.get("scheduling_policy", {}).get("control_plane", {}).get("model")
    if not control_model:
        return {"action": "defer", "model": None,
                "reason": "model policy defines no routing model", "valid": False}
    try:
        message = infer(
            model=control_model,
            messages=[{"role": "user", "content": _routing_prompt(job, inventory)}],
            max_tokens=256,
            timeout=45,
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        decision = _json_object(str(message.get("content", "")))
    except Exception as error:
        return {"action": "defer", "model": None,
                "reason": f"routing model unavailable or invalid: {type(error).__name__}: {error}",
                "valid": False}

    action = decision.get("action")
    model_id = decision.get("model")
    selected_context = decision.get("context_tokens")
    reason = str(decision.get("reason", "")).strip()[:1000]
    if action == "defer":
        return {"action": "defer", "model": None,
                "reason": reason or "routing model deferred the task", "valid": True}
    if (action not in {"use_loaded", "load"} or not isinstance(model_id, str)
            or not isinstance(selected_context, int)):
        return {"action": "defer", "model": None,
                "reason": "routing model returned an invalid action or model id", "valid": False}
    candidate = next((item for item in inventory.get("models", []) if item.get("id") == model_id), None)
    if candidate is None:
        return {"action": "defer", "model": None,
                "reason": f"routing model selected unavailable model {model_id!r}", "valid": False}
    if not role_compatible(job.get("role"), set(candidate.get("labels", []))):
        return {"action": "defer", "model": None,
                "reason": f"routing model selected role-incompatible model {model_id!r}", "valid": False}
    if action == "use_loaded" and not candidate.get("loaded"):
        return {"action": "defer", "model": None,
                "reason": f"routing model claimed nonresident model {model_id!r} was loaded", "valid": False}
    admitted, admission_reason = admission(model_id, inventory)
    if not admitted:
        return {"action": "defer", "model": None,
                "reason": f"routing choice rejected by safety validator: {admission_reason}", "valid": False}
    if action == "load":
        loaded = [item for item in inventory.get("models", []) if item.get("loaded")]
        maximum = json.loads(RESOURCE_POLICY_PATH.read_text(encoding="utf-8"))["normal"]["maximum_loaded_models"]
        if not candidate.get("loaded") and len(loaded) >= maximum:
            return {"action": "defer", "model": None,
                    "reason": (f"routing choice would exceed the {maximum}-model residency boundary; "
                               "reuse the loaded work model or wait for a safe eviction boundary"),
                    "valid": False}
    options = context_options(candidate, inventory)
    if selected_context not in options:
        return {"action": "defer", "model": None,
                "reason": (f"routing model selected unvalidated context {selected_context} for "
                           f"{model_id!r}; safe choices are {options}"), "valid": False}
    return {"action": action, "model": model_id, "context_tokens": selected_context,
            "reason": f"{reason or 'model-mediated route'}; {admission_reason}", "valid": True}


def realize(decision: dict, inventory: dict) -> dict:
    """Realize a validated route with bounded, explicitly unpinned model options."""
    if not decision.get("valid") or decision.get("action") == "defer":
        raise ValueError("cannot realize a deferred or invalid model route")
    model_id = decision["model"]
    candidate = next((item for item in inventory.get("models", [])
                      if item.get("id") == model_id), None)
    if candidate is None:
        raise ValueError(f"routed model {model_id!r} disappeared from inventory")
    control_model = inventory.get("scheduling_policy", {}).get("control_plane", {}).get("model")
    if candidate.get("loaded"):
        if model_id != control_model and candidate.get("pinned"):
            subprocess_result = subprocess.run(
                ["/usr/bin/lemonade", "unpin", model_id], check=False,
                text=True, capture_output=True, timeout=10,
            )
            if subprocess_result.returncode != 0:
                raise RuntimeError(f"could not unpin dynamic model {model_id!r}: "
                                   f"{subprocess_result.stderr.strip()}")
        return {"action": "already_loaded", "model": model_id,
                "context_tokens": decision["context_tokens"]}
    admitted, reason = admission(model_id, inventory)
    if not admitted:
        raise RuntimeError(reason)
    settings = json.loads(RESOURCE_POLICY_PATH.read_text(encoding="utf-8"))["dynamic_models"]
    context = int(decision["context_tokens"])
    parallel = int(settings["parallel_requests"])
    batch = int(settings["llamacpp_batch_size"])
    ubatch = int(settings["llamacpp_ubatch_size"])
    payload = {
        "model_name": model_id,
        "pinned": False,
        "ctx_size": context,
        "merge_args": True,
        "llamacpp_args": (f"--parallel {parallel} --batch-size {batch} "
                           f"--ubatch-size {ubatch} --poll 0 --prio -1"),
    }
    response = _post("/v1/load", payload, timeout=180.0)
    return {"action": "loaded", "model": model_id, "context_tokens": context,
            "pinned": False, "admission_reason": reason, "response": response}


def admitted_or_substitute(model_id: str, role: str | None, inventory: dict) -> tuple[str | None, str]:
    admitted, reason = admission(model_id, inventory)
    if admitted:
        return model_id, reason
    desired = next((item for item in inventory.get("models", []) if item["id"] == model_id), {})
    required = required_labels(role)
    desired_labels = set(desired.get("labels", []))
    candidates = []
    for item in inventory.get("models", []):
        labels = set(item.get("labels", []))
        if not item.get("loaded") or not role_compatible(role, labels):
            continue
        overlap = len(labels & desired_labels)
        candidates.append((overlap, float(item.get("size_gb") or 0), item["id"]))
    if not candidates:
        return None, f"{reason}; no resident model satisfies required labels {sorted(required)}"
    _, _, chosen = max(candidates)
    return chosen, (f"{reason}; substituted resident {chosen!r}, which is "
                    f"role-compatible (baseline labels {sorted(required)})")

def fallback(role: str | None, inventory: dict) -> tuple[str, str]:
    available = ids(inventory)
    preferences = (["Qwen3-Coder-30B-A3B-Instruct-GGUF", "Qwen3.8-27B-GGUF", "GLM-4.7-Flash-GGUF"]
                   if role in {"worker", "refactorer"} else
                   ["Qwen3.8-27B-GGUF", "GLM-4.7-Flash-GGUF", "Qwen3-Coder-30B-A3B-Instruct-GGUF"])
    chosen = next((model for model in preferences if model in available), available[0])
    return chosen, "Deterministic fallback based on role capability; live router choice unavailable."
