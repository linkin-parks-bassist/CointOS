"""Live inventory, model-mediated routing, and deterministic safety validation."""
from __future__ import annotations
import glob, json, os, re, subprocess, urllib.request
from pathlib import Path

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


def _positive_integer(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _request_reserves(request: dict, policy: dict) -> dict:
    defaults = _policy_value(policy, "context_reserves", {})
    reserves = {}
    for name in ("prompt_tokens", "tool_tokens", "max_output_tokens", "handoff_tokens"):
        requested = request.get(name, defaults.get(name))
        configured = defaults.get(name) if isinstance(defaults, dict) else None
        reserves[name] = (max(requested, configured)
                          if isinstance(requested, int) and not isinstance(requested, bool)
                          and isinstance(configured, int) and not isinstance(configured, bool)
                          else requested)
    return reserves


def _policy_value(policy: dict, name: str, default=0):
    if name in policy:
        return policy[name]
    for section in ("physical_capacity", "dynamic_models"):
        nested = policy.get(section, {})
        if isinstance(nested, dict) and name in nested:
            return nested[name]
    return default


def _inventory_reasons(inventory: dict) -> list[str]:
    reasons = []
    if inventory.get("verified") is not True:
        reasons.append("inventory:unverified")
    if inventory.get("fresh") is not True or inventory.get("stale") is True:
        reasons.append("inventory:stale")
    if not isinstance(inventory.get("provenance"), str) or not inventory["provenance"]:
        reasons.append("inventory:provenance")
    envelope = inventory.get("resource_envelope")
    if not isinstance(envelope, dict):
        reasons.append("resource_envelope:missing")
    else:
        if envelope.get("verified") is not True:
            reasons.append("resource_envelope:unverified")
        if envelope.get("fresh") is not True or envelope.get("stale") is True:
            reasons.append("resource_envelope:stale")
        if envelope.get("safe") is not True:
            reasons.append("resource_envelope:unsafe")
        if not isinstance(envelope.get("provenance"), str) or not envelope["provenance"]:
            reasons.append("resource_envelope:provenance")
    return reasons


def _model_route(model: dict, inventory: dict, policy: dict, request: dict) -> dict:
    reasons = _inventory_reasons(inventory)
    model_id = model.get("id")
    parameter_count = model.get("parameter_count")
    model_bytes = model.get("size_bytes", model.get("model_bytes"))
    advertised = model.get("context", model.get("advertised_context_tokens"))
    quantum = model.get("supported_context_quantum")
    parallel = model.get("parallel_sequences", _policy_value(policy, "parallel_sequences", 1))
    capabilities = model.get("capabilities")
    requirements = request.get("requirements", {})
    if not isinstance(requirements, dict):
        requirements = {}
    required = requirements.get("required_capabilities", [])
    minimum = requirements.get("minimum_context_tokens", 0)
    reserves = _request_reserves(request, policy)

    if not isinstance(model_id, str) or not model_id:
        reasons.append("model_id")
    if model.get("metadata_verified") is not True:
        reasons.append("metadata:unverified")
    if model.get("fresh") is not True or model.get("stale") is True:
        reasons.append("metadata:stale")
    if not isinstance(model.get("provenance"), str) or not model["provenance"]:
        reasons.append("metadata:provenance")
    if not _positive_integer(parameter_count):
        reasons.append("parameter_count")
    if not _positive_integer(model_bytes):
        reasons.append("model_bytes")
    if not _positive_integer(advertised):
        reasons.append("advertised_context_tokens")
    if not _positive_integer(quantum):
        reasons.append("supported_context_quantum")
    if not _positive_integer(parallel):
        reasons.append("parallel_sequences")
    if not isinstance(capabilities, list) or any(not isinstance(item, str) for item in capabilities):
        reasons.append("capabilities")
        capabilities = []
    if "required_capabilities" not in requirements:
        reasons.append("requirements:required_capabilities")
    elif not isinstance(required, list) or any(not isinstance(item, str) for item in required):
        reasons.append("requirements:required_capabilities")
        required = []
    missing = sorted(set(required) - set(capabilities))
    reasons.extend(f"capability:{item}" for item in missing)
    if "minimum_context_tokens" not in requirements:
        reasons.append("requirements:minimum_context_tokens")
    elif not isinstance(minimum, int) or isinstance(minimum, bool) or minimum < 0:
        reasons.append("requirements:minimum_context_tokens")
        minimum = 0
    if any(not isinstance(value, int) or isinstance(value, bool) or value < 0
           for value in reserves.values()):
        reasons.append("context_reserve")

    envelope = inventory.get("resource_envelope", {})
    maximum_model_bytes = envelope.get("maximum_model_bytes")
    maximum_backend_context = envelope.get("maximum_context_tokens")
    if not _positive_integer(maximum_model_bytes) or (
            _positive_integer(model_bytes) and model_bytes > maximum_model_bytes):
        reasons.append("model_bytes")
    if not _positive_integer(maximum_backend_context):
        reasons.append("resource_envelope:maximum_context_tokens")
    for field in ("available_host_bytes", "gtt_limit_bytes", "maximum_kv_bytes"):
        if not _positive_integer(envelope.get(field)):
            reasons.append(f"resource_envelope:{field}")
    gtt_used_evidence = envelope.get("gtt_used_bytes")
    if (not isinstance(gtt_used_evidence, int) or isinstance(gtt_used_evidence, bool)
            or gtt_used_evidence < 0):
        reasons.append("resource_envelope:gtt_used_bytes")

    per_sequence = 0
    backend_context = 0
    context_exclusion_reasons = []
    if (_positive_integer(advertised) and _positive_integer(quantum)
            and _positive_integer(parallel) and _positive_integer(maximum_backend_context)):
        envelope_per_sequence = maximum_backend_context // parallel
        upper = min(advertised, envelope_per_sequence)
        if envelope_per_sequence < advertised:
            context_exclusion_reasons.append("context:resource_envelope")
        if model.get("loaded"):
            loaded_total = model.get("loaded_context", model.get("backend_context_tokens"))
            if loaded_total is not None:
                if not _positive_integer(loaded_total):
                    reasons.append("loaded_context")
                else:
                    if loaded_total // parallel < upper:
                        context_exclusion_reasons.append("context:loaded_allocation")
                    upper = min(upper, loaded_total // parallel)
        per_sequence = upper - upper % quantum
        if per_sequence != upper:
            context_exclusion_reasons.append("context:backend_quantum")
        if per_sequence == 0:
            reasons.append("context:unsupported")
        backend_context = per_sequence * parallel
        reserve_total = minimum + sum(value for value in reserves.values()
                                      if isinstance(value, int) and not isinstance(value, bool))
        if per_sequence < reserve_total:
            reasons.append("context_reserve")

    kv_bytes_per_token = _policy_value(policy, "estimated_kv_bytes_per_token", 0)
    if not _positive_integer(kv_bytes_per_token):
        reasons.append("estimated_kv_bytes_per_token")
        kv_bytes_per_token = 0
    kv_estimate = backend_context * kv_bytes_per_token
    maximum_kv_bytes = envelope.get("maximum_kv_bytes")
    if maximum_kv_bytes is not None and (
            not _positive_integer(maximum_kv_bytes) or kv_estimate > maximum_kv_bytes):
        reasons.append("kv_estimate_bytes")

    protected_host = _policy_value(policy, "protected_host_bytes", 0)
    coin_reserved = _policy_value(policy, "coin_reserved_bytes", 0)
    load_transient = _policy_value(policy, "load_transient_bytes", 0)
    policy_gtt_limit = _policy_value(policy, "gtt_limit_bytes", 0)
    physical_values = (protected_host, coin_reserved, load_transient, policy_gtt_limit)
    configured_reserves = _policy_value(policy, "context_reserves", {})
    if (any(not _positive_integer(value) for value in physical_values)
            or not isinstance(configured_reserves, dict)
            or any(not _positive_integer(configured_reserves.get(name)) for name in (
                "prompt_tokens", "tool_tokens", "max_output_tokens", "handoff_tokens"))):
        reasons.append("physical_policy")
    elif _positive_integer(model_bytes):
        load_demand = 0 if model.get("loaded") else model_bytes + load_transient
        host_available = envelope.get("available_host_bytes")
        if host_available is not None and (
                not _positive_integer(host_available)
                or protected_host + coin_reserved + load_demand + kv_estimate > host_available):
            reasons.append("host_capacity")
        gtt_used = envelope.get("gtt_used_bytes")
        envelope_gtt_limit = envelope.get("gtt_limit_bytes")
        gtt_limit = min(envelope_gtt_limit, policy_gtt_limit) \
            if _positive_integer(envelope_gtt_limit) and _positive_integer(policy_gtt_limit) else None
        if gtt_used is not None or gtt_limit is not None:
            if (not isinstance(gtt_used, int) or isinstance(gtt_used, bool) or gtt_used < 0
                    or not _positive_integer(gtt_limit)
                    or gtt_used + load_demand + kv_estimate > gtt_limit):
                reasons.append("gtt_capacity")

    return {
        "state": "admitted" if not reasons else "deferred",
        "model_id": model_id,
        "parameter_count": parameter_count,
        "model_bytes": model_bytes,
        "advertised_context_tokens": advertised,
        "backend_context_tokens": backend_context,
        "parallel_sequences": parallel,
        "context_tokens_per_sequence": per_sequence,
        "context_exclusion_reasons": context_exclusion_reasons,
        **reserves,
        "kv_estimate_bytes": kv_estimate,
        "load_transient_bytes": load_transient,
        "protected_host_bytes": protected_host,
        "coin_reserved_bytes": coin_reserved,
        "gtt_limit_bytes": envelope.get("gtt_limit_bytes"),
        "loaded": bool(model.get("loaded")),
        "provenance": model.get("provenance", inventory.get("provenance")),
        "exclusion_reasons": list(dict.fromkeys(reasons)),
    }


def safe_routes(inventory: dict, policy: dict, request: dict) -> list[dict]:
    """Interpret verified model facts into admitted or explicitly excluded routes."""
    if not isinstance(inventory, dict) or not isinstance(policy, dict) or not isinstance(request, dict):
        raise TypeError("inventory, policy, and request must be dictionaries")
    models = inventory.get("models", [])
    if not isinstance(models, list):
        return [{"state": "deferred", "model_id": None,
                 "exclusion_reasons": ["inventory:models"]}]
    return [_model_route(item, inventory, policy, request) if isinstance(item, dict)
            else {"state": "deferred", "model_id": None,
                  "exclusion_reasons": ["inventory:model_record"]}
            for item in models]


def choose_route(routes: list[dict], request: dict) -> dict:
    """Choose the largest verified qualified model, with preference only as a tie break."""
    admitted = [route for route in routes if route.get("state") == "admitted"]
    requirements = request.get("requirements", {})
    requirements = requirements if isinstance(requirements, dict) else {}
    preferences = requirements.get("preferred_model_ids", [])
    preference_rank = {model_id: len(preferences) - index
                       for index, model_id in enumerate(preferences)
                       if isinstance(model_id, str)} if isinstance(preferences, list) else {}
    if admitted:
        selected = max(admitted, key=lambda route: (
            route["parameter_count"],
            route["context_tokens_per_sequence"],
            preference_rank.get(route["model_id"], 0),
            route["model_id"],
        ))
        excluded = [{"model_id": route.get("model_id"),
                     "exclusion_reasons": route.get("exclusion_reasons", [])}
                    for route in routes if route.get("state") != "admitted"]
        return {**selected, "excluded_routes": excluded}
    reasons = [reason for route in routes for reason in route.get("exclusion_reasons", [])]
    return {"state": "deferred", "model_id": None,
            "exclusion_reasons": list(dict.fromkeys(reasons or ["no_models"]))}


def validate_route(route: dict, fresh_inventory: dict, policy: dict, request: dict) -> dict:
    """Recompute a route from fresh facts and reject any changed physical allocation."""
    routes = safe_routes(fresh_inventory, policy, request)
    fresh = next((item for item in routes if item.get("model_id") == route.get("model_id")), None)
    if fresh is None:
        return {"state": "deferred", "model_id": route.get("model_id"),
                "exclusion_reasons": ["model:disappeared"]}
    if fresh.get("state") != "admitted":
        return fresh
    allocation_fields = ("parameter_count", "model_bytes", "backend_context_tokens",
                         "parallel_sequences", "context_tokens_per_sequence")
    changed = [field for field in allocation_fields if fresh.get(field) != route.get(field)]
    if changed:
        return {**fresh, "state": "deferred",
                "exclusion_reasons": [f"route_changed:{field}" for field in changed]}
    return fresh


def route(job: dict, inventory: dict, infer=None) -> dict:
    """Compatibility entry point for consumers awaiting the R4 lease migration."""
    resource_policy = json.loads(RESOURCE_POLICY_PATH.read_text(encoding="utf-8"))
    selected = choose_route(safe_routes(inventory, resource_policy, job), job)
    if selected.get("state") != "admitted":
        reasons = selected.get("exclusion_reasons", ["no_safe_route"])
        return {"action": "defer", "model": None, "context_tokens": None,
                "reason": "; ".join(reasons), "valid": False,
                "exclusion_reasons": reasons}
    return {**selected,
            "action": "use_loaded" if selected["loaded"] else "load",
            "model": selected["model_id"],
            "context_tokens": selected["context_tokens_per_sequence"],
            "reason": "largest verified task-qualified route", "valid": True}


def realize(decision: dict, inventory: dict) -> dict:
    """Realize a validated route with bounded, explicitly unpinned model options."""
    if not decision.get("valid") or decision.get("action") == "defer":
        raise ValueError("cannot realize a deferred or invalid model route")
    model_id = decision["model"]
    candidate = next((item for item in inventory.get("models", [])
                      if item.get("id") == model_id), None)
    if candidate is None:
        raise ValueError(f"routed model {model_id!r} disappeared from inventory")
    context = decision.get("context_tokens_per_sequence")
    backend_context = decision.get("backend_context_tokens")
    parallel = decision.get("parallel_sequences")
    if (not _positive_integer(context) or not _positive_integer(backend_context)
            or not _positive_integer(parallel) or backend_context != context * parallel):
        raise ValueError("route has inconsistent per-sequence and backend context allocation")
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
                "context_tokens": context,
                "backend_context_tokens": backend_context,
                "parallel_sequences": parallel}
    admitted, reason = admission(model_id, inventory)
    if not admitted:
        raise RuntimeError(reason)
    settings = json.loads(RESOURCE_POLICY_PATH.read_text(encoding="utf-8"))["dynamic_models"]
    batch = int(settings["llamacpp_batch_size"])
    ubatch = int(settings["llamacpp_ubatch_size"])
    payload = {
        "model_name": model_id,
        "pinned": False,
        "ctx_size": backend_context,
        "merge_args": True,
        "llamacpp_args": (f"--parallel {parallel} --batch-size {batch} "
                           f"--ubatch-size {ubatch} --poll 0 --prio -1"),
    }
    response = _post("/v1/load", payload, timeout=180.0)
    return {"action": "loaded", "model": model_id, "context_tokens": context,
            "backend_context_tokens": backend_context,
            "parallel_sequences": parallel,
            "pinned": False, "admission_reason": reason, "response": response}
