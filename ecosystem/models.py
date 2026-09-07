"""Live inventory, model-mediated routing, and deterministic safety validation."""
from __future__ import annotations
import glob, http.client, ipaddress, json, os, re, shlex, subprocess, time, urllib.request
from pathlib import Path

BASE = os.environ.get("LEMONADE_BASE_URL", "http://127.0.0.1:13305")
RESOURCE_POLICY_PATH = Path(__file__).resolve().parents[1] / "config/resource-policy.json"

def _get(path: str) -> dict:
    with urllib.request.urlopen(BASE + path, timeout=10) as response:
        return json.load(response)


_BACKEND_MAX_BYTES = 1_048_576
_BACKEND_PATHS = ("/v1/models", "/props")


def _get_backend(backend_base: str, path: str) -> dict:
    if path not in _BACKEND_PATHS:
        raise ValueError("backend path must be /v1/models or /props")
    parsed = urllib.parse.urlsplit(backend_base)
    if parsed.scheme != "http":
        raise ValueError("backend base must be an http URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("backend base must not contain credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("backend base must not contain a query or fragment")
    if parsed.path != "/v1":
        raise ValueError("backend base path must be /v1")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("backend base must have a valid explicit port") from exc
    if port is None or not 1 <= port <= 65535:
        raise ValueError("backend base must have an explicit valid port")
    host = parsed.hostname
    if not host:
        raise ValueError("backend base must have a host")
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise ValueError("backend base host must be a numeric loopback address") from exc
    if not address.is_loopback:
        raise ValueError("backend base host must be a loopback address")
    conn = http.client.HTTPConnection(host, port, timeout=1)
    try:
        conn.request("GET", path)
        response = conn.getresponse()
        if response.status != 200:
            raise ValueError("backend returned HTTP %d" % response.status)
        body = response.read(_BACKEND_MAX_BYTES + 1)
        if len(body) > _BACKEND_MAX_BYTES:
            raise ValueError("backend response exceeds %d bytes" % _BACKEND_MAX_BYTES)
        return json.loads(body)
    finally:
        conn.close()


def gpu_memory() -> dict:
    result = {
        "firmware_carveout_bytes": None,
        "gtt_total_bytes": None,
        "gtt_used_bytes": None,
        "provenance": "amdgpu:sysfs",
        "fresh": False,
    }
    for device in sorted(glob.glob("/sys/class/drm/card*/device")):
        uma = Path(device) / "uma"
        try:
            index = (uma / "carveout").read_text(encoding="utf-8").strip()
            options = (uma / "carveout_options").read_text(encoding="utf-8")
            match = re.search(rf"^{re.escape(index)}:.*\((\d+) (MB|GB)\)$", options, re.MULTILINE)
            if match:
                scale = 1024 ** (2 if match.group(2) == "MB" else 3)
                result["firmware_carveout_bytes"] = int(match.group(1)) * scale
            for name in ("gtt_total", "gtt_used"):
                raw = int((Path(device) / f"mem_info_{name}").read_text(encoding="utf-8"))
                result[f"{name}_bytes"] = raw
            result["fresh"] = (
                _positive_integer(result["gtt_total_bytes"])
                and isinstance(result["gtt_used_bytes"], int)
                and not isinstance(result["gtt_used_bytes"], bool)
                and result["gtt_used_bytes"] >= 0
            )
            return result
        except (FileNotFoundError, PermissionError, ValueError):
            continue
    return result


def _host_memory() -> dict:
    memory = {}
    with open("/proc/meminfo", encoding="utf-8") as stream:
        for line in stream:
            key, value = line.split(":", 1)
            memory[key] = int(value.strip().split()[0]) * 1024
    total = memory.get("MemTotal")
    available = memory.get("MemAvailable")
    return {
        "total_bytes": total,
        "available_bytes": available,
        "provenance": "linux:/proc/meminfo",
        "fresh": (
            _positive_integer(total)
            and isinstance(available, int)
            and not isinstance(available, bool)
            and available >= 0
        ),
    }


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, PermissionError, json.JSONDecodeError):
        return None


def _nonnegative_integer(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _positive_integer_value(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _health_parallel_sequences(resident: dict):
    explicit = _positive_integer_value(resident.get("parallel_sequences"))
    if explicit is not None:
        return explicit
    options = resident.get("recipe_options")
    arguments = options.get("llamacpp_args") if isinstance(options, dict) else None
    if not isinstance(arguments, str):
        return None
    try:
        tokens = shlex.split(arguments)
    except ValueError:
        return None
    values = []
    for index, token in enumerate(tokens):
        if token == "--parallel" and index + 1 < len(tokens):
            values.append(tokens[index + 1])
        elif token.startswith("--parallel="):
            values.append(token.partition("=")[2])
    if len(values) != 1:
        return None
    try:
        return _positive_integer_value(int(values[0]))
    except ValueError:
        return None


def _verified_model_record(
    item: dict, resident: dict | None, health_fresh: bool, observed_at: float,
) -> dict:
    model_id = item.get("id")
    parameter_count = item.get("parameter_count")
    size_bytes = item.get("size_bytes")
    capabilities = item.get("capabilities")
    advertised = item.get("context_length")
    quantum = item.get("supported_context_quantum")
    registry_parallel = item.get("parallel_sequences")
    metadata_verified = (
        isinstance(model_id, str) and bool(model_id)
        and _positive_integer(parameter_count)
        and _positive_integer(size_bytes)
        and isinstance(capabilities, list)
        and all(isinstance(value, str) and value for value in capabilities)
        and _positive_integer(advertised)
        and _positive_integer(quantum)
        and _positive_integer(registry_parallel)
    )
    loaded = resident is not None if health_fresh else None
    loaded_context = None
    parallel = registry_parallel
    residency_verified = health_fresh
    if resident is not None:
        options = resident.get("recipe_options")
        loaded_context = options.get("ctx_size") if isinstance(options, dict) else None
        parallel = _health_parallel_sequences(resident)
        residency_verified = (
            _positive_integer(loaded_context)
            and _positive_integer(parallel)
            and loaded_context % parallel == 0
        )
    return {
        "id": model_id,
        "parameter_count": parameter_count if _positive_integer(parameter_count) else None,
        "size_bytes": size_bytes if _positive_integer(size_bytes) else None,
        "size_gb": size_bytes / 1024 ** 3 if _positive_integer(size_bytes) else None,
        "capabilities": capabilities if isinstance(capabilities, list) else None,
        "context": advertised if _positive_integer(advertised) else None,
        "supported_context_quantum": quantum if _positive_integer(quantum) else None,
        "parallel_sequences": parallel if _positive_integer(parallel) else None,
        "loaded": loaded,
        "loaded_context": loaded_context if _positive_integer(loaded_context) else None,
        "busy": resident.get("is_busy") if resident is not None else False,
        "pinned": resident.get("pinned") if resident is not None else False,
        "recipe": item.get("recipe"),
        "metadata_verified": bool(metadata_verified),
        "residency_verified": bool(residency_verified),
        "fresh": bool(health_fresh and residency_verified),
        "stale": not bool(health_fresh and residency_verified),
        "observed_at": observed_at,
        "provenance": "lemonade:/v1/models;lemonade:/api/v1/health",
    }


def _observed_model_record(item, resident, backend_document, props, observed_at):
    """Normalize one observed resident allocation into a verified registry record.

    Pure function: returns a copied record built from measured backend facts,
    or None when any mandatory fact is missing, malformed, or contradictory.
    Only parameter_count and size_bytes must agree between registry and
    backend; a present registry context_length is retained verbatim as
    result["registry_context_length"] without interpretation, because it
    records the allocated context, not the measured training maximum.
    """
    if not all(isinstance(value, dict) for value in (item, resident, backend_document, props)):
        return None
    model_id = item.get("id")
    if not isinstance(model_id, str) or not model_id or resident.get("model_name") != model_id:
        return None
    if resident.get("loaded") is not True or resident.get("backend_alive") is not True:
        return None
    if not _positive_integer(resident.get("pid")):
        return None
    backend_url = resident.get("backend_url")
    if not isinstance(backend_url, str) or not backend_url:
        return None
    model_path = props.get("model_path")
    if not isinstance(model_path, str) or not model_path:
        return None
    launch_command = resident.get("launch_command")
    if (not isinstance(launch_command, list)
            or not all(isinstance(argument, str) for argument in launch_command)
            or model_path not in launch_command):
        return None
    data = backend_document.get("data")
    if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
        return None
    if data[0].get("id") != model_path:
        return None
    meta = data[0].get("meta")
    if not isinstance(meta, dict):
        return None
    n_params = meta.get("n_params")
    size = meta.get("size")
    n_ctx_train = meta.get("n_ctx_train")
    if not all(_positive_integer(value) for value in (n_params, size, n_ctx_train)):
        return None
    total_slots = props.get("total_slots")
    if not _positive_integer(total_slots):
        return None
    options = resident.get("recipe_options")
    if not isinstance(options, dict):
        return None
    ctx_size = options.get("ctx_size")
    if not _positive_integer(ctx_size) or ctx_size % total_slots != 0:
        return None
    if ctx_size // total_slots > n_ctx_train:
        return None
    health_parallel = _health_parallel_sequences(resident)
    if health_parallel is not None and health_parallel != total_slots:
        return None
    caps = props.get("chat_template_caps")
    if not isinstance(caps, dict) or not isinstance(caps.get("supports_tools"), bool):
        return None
    supports_tools = caps.get("supports_tools")
    registry_capabilities = item.get("capabilities")
    if registry_capabilities is None:
        capabilities = ["tool-calling"] if supports_tools else []
    elif isinstance(registry_capabilities, list):
        if not all(isinstance(value, str) and value for value in registry_capabilities):
            return None
        capabilities = list(registry_capabilities)
        if ("tool-calling" in capabilities) != supports_tools:
            return None
    else:
        return None
    for field, measured in (("parameter_count", n_params),
                            ("size_bytes", size)):
        declared = item.get(field)
        if declared is not None and not (
                _positive_integer(declared) and declared == measured):
            return None
    record = dict(item)
    record["parameter_count"] = n_params
    record["size_bytes"] = size
    record["context_length"] = n_ctx_train
    record["capabilities"] = capabilities
    record["parallel_sequences"] = total_slots
    record["supported_context_quantum"] = ctx_size // total_slots
    observed_resident = dict(resident)
    observed_resident["parallel_sequences"] = total_slots
    result = _verified_model_record(record, observed_resident, True, observed_at)
    if result.get("metadata_verified") is not True or result.get("residency_verified") is not True:
        return None
    root = backend_url.removesuffix("/v1").rstrip("/")
    result["provenance"] = (
        f"{root}/v1/models;{root}/props;"
        "lemonade:/api/v1/health;observed-allocation-only"
    )
    # Explicit fixed-partition llama.cpp allocation is already in host/GTT usage.
    # Shared/dynamic pools need their own accounting contract, not this credit.
    fixed = record.get("recipe") == "llamacpp" and meta.get("n_ctx") == ctx_size // total_slots
    for flag, expected in (("--parallel", total_slots), ("--ctx-size", ctx_size)):
        fixed = fixed and launch_command.count(flag) == 1
        if fixed:
            index = launch_command.index(flag) + 1
            fixed = index < len(launch_command) and launch_command[index] == str(expected)
    if fixed and not any(argument in ("--kv-unified", "-kvu", "--kv-unified-per-slot")
                         for argument in launch_command):
        result["preallocated_context_tokens"] = ctx_size
    registry_context = item.get("context_length")
    if registry_context is not None:
        result["registry_context_length"] = registry_context
    return result


def _observed_resident_record(item, resident, now):
    """Read a resident's bounded backend facts, re-check gateway health once,
    and normalize the allocation.

    Returns (record, None) when the resident is fully observed, or
    (None, reason) with 'unavailable', 'inconsistent', or 'backend_changed'.
    """
    backend_url = resident.get("backend_url")
    if not isinstance(backend_url, str) or not backend_url:
        return None, "unavailable"
    try:
        backend_document = _get_backend(backend_url, "/v1/models")
        props = _get_backend(backend_url, "/props")
    except Exception:
        return None, "unavailable"
    try:
        health_document = _get("/api/v1/health")
    except Exception:
        return None, "unavailable"
    entries = health_document.get("all_models_loaded") \
        if isinstance(health_document, dict) else None
    if not isinstance(entries, list) \
            or not all(isinstance(entry, dict) for entry in entries):
        return None, "unavailable"
    matches = [entry for entry in entries
               if isinstance(entry.get("model_name"), str)
               and entry.get("model_name") == item.get("id")]
    if not matches:
        return None, "unavailable"
    if len(matches) != 1:
        return None, "backend_changed"
    fresh = matches[0]
    stable_fields = ("model_name", "backend_url", "pid", "loaded",
                     "backend_alive", "recipe_options", "launch_command")
    if any(fresh.get(field) != resident.get(field) for field in stable_fields):
        return None, "backend_changed"
    record = _observed_model_record(item, fresh, backend_document, props, now)
    if record is None:
        return None, "inconsistent"
    return record, None


def snapshot(root: Path | None = None, clock=None) -> dict:
    """Sample literal registry, residency, host and accepted scheduling facts."""
    root = Path(root) if root is not None else Path(__file__).resolve().parents[1]
    now = (clock or time.time)()
    registry_document = _get("/v1/models")
    registry = registry_document.get("data") if isinstance(registry_document, dict) else None
    registry_fresh = isinstance(registry, list) and all(isinstance(item, dict) for item in registry)
    registry = registry if registry_fresh else []
    try:
        health_document = _get("/api/v1/health")
        health = health_document.get("all_models_loaded") \
            if isinstance(health_document, dict) else None
        health_fresh = isinstance(health, list) and all(isinstance(item, dict) for item in health)
    except Exception:
        health = []
        health_fresh = False
    health = health if health_fresh else []
    loaded = {
        item["model_name"]: item for item in health
        if isinstance(item.get("model_name"), str) and item["model_name"]
    }
    downloaded = [item for item in registry if item.get("downloaded") is True]
    models = []
    for item in downloaded:
        resident = loaded.get(item.get("id"))
        record = _verified_model_record(item, resident, health_fresh, now)
        if resident is not None and "backend_url" in resident:
            observed, reason = _observed_resident_record(item, resident, now)
            if observed is not None:
                observed["metadata_error"] = None
                record = observed
            else:
                record["metadata_verified"] = False
                record["residency_verified"] = False
                record["fresh"] = False
                record["stale"] = True
                record["metadata_error"] = reason
        else:
            record["metadata_error"] = None if record["metadata_verified"] \
                else "missing_metadata"
        models.append(record)

    host_memory = _host_memory()
    gpu = gpu_memory()
    host_fresh = host_memory.get("fresh") is True and gpu.get("fresh") is True
    host_provenance = f"{host_memory.get('provenance')};{gpu.get('provenance')}"
    available = _nonnegative_integer(host_memory.get("available_bytes"))
    total = _positive_integer_value(host_memory.get("total_bytes"))
    gtt_used = _nonnegative_integer(gpu.get("gtt_used_bytes"))
    measured_gtt_total = _positive_integer_value(gpu.get("gtt_total_bytes"))
    host = {
        "available_host_bytes": available,
        "total_host_bytes": total,
        "gtt_used_bytes": gtt_used,
        "gtt_total_bytes": measured_gtt_total,
        "gtt_total_fresh": bool(gpu.get("fresh") is True and measured_gtt_total),
        "fresh": bool(host_fresh),
        "stale": not bool(host_fresh),
        "observed_at": now,
        "provenance": host_provenance,
    }

    policy_document = _read_json(root / "config" / "resource-policy.json")
    model_policy = _read_json(root / "config" / "model-policy.json")
    control_plane = model_policy.get("control_plane", {}) \
        if isinstance(model_policy, dict) else {}
    control_model = control_plane.get("model") \
        if isinstance(control_plane, dict) else None
    physical = policy_document.get("physical_capacity", {}) \
        if isinstance(policy_document, dict) else {}
    dynamic = policy_document.get("dynamic_models", {}) \
        if isinstance(policy_document, dict) else {}
    protected = _nonnegative_integer(physical.get("protected_host_bytes"))
    coin_reserved = _nonnegative_integer(physical.get("coin_reserved_bytes"))
    transient = _nonnegative_integer(physical.get("load_transient_bytes"))
    configured_gtt_limit = _positive_integer_value(physical.get("gtt_limit_bytes"))
    gtt_limit = min(measured_gtt_total, configured_gtt_limit) \
        if measured_gtt_total and configured_gtt_limit else None
    host_model_headroom = available - protected - coin_reserved - transient \
        if None not in (available, protected, coin_reserved, transient) else None
    gtt_model_headroom = gtt_limit - gtt_used - transient \
        if None not in (gtt_limit, gtt_used, transient) else None
    maximum_model_bytes = min(host_model_headroom, gtt_model_headroom) \
        if None not in (host_model_headroom, gtt_model_headroom) else None
    host_kv_headroom = available - protected - coin_reserved \
        if None not in (available, protected, coin_reserved) else None
    gtt_kv_headroom = gtt_limit - gtt_used \
        if None not in (gtt_limit, gtt_used) else None
    maximum_kv_bytes = min(host_kv_headroom, gtt_kv_headroom) \
        if None not in (host_kv_headroom, gtt_kv_headroom) else None
    contexts = [item["context"] for item in models if _positive_integer(item.get("context"))]
    envelope_safe = (
        host_fresh and registry_fresh
        and _positive_integer(maximum_model_bytes)
        and _positive_integer(maximum_kv_bytes)
        and bool(contexts)
    )
    resource_envelope = {
        "verified": bool(envelope_safe),
        "fresh": bool(host_fresh and registry_fresh),
        "stale": not bool(host_fresh and registry_fresh),
        "safe": bool(envelope_safe),
        "observed_at": now,
        "provenance": f"{host_provenance};policy:config/resource-policy.json",
        "maximum_model_bytes": max(0, maximum_model_bytes) \
            if isinstance(maximum_model_bytes, int) else None,
        "maximum_context_tokens": max(contexts) if contexts else None,
        "available_host_bytes": available,
        "gtt_used_bytes": gtt_used,
        "gtt_limit_bytes": gtt_limit,
        "maximum_kv_bytes": max(0, maximum_kv_bytes) \
            if isinstance(maximum_kv_bytes, int) else None,
        "protected_host_bytes": protected,
        "coin_reserved_bytes": coin_reserved,
        "load_transient_bytes": transient,
        "estimated_kv_bytes_per_token": dynamic.get("estimated_kv_bytes_per_token"),
    }
    resident_models = []
    model_by_id = {item.get("id"): item for item in models}
    resident_facts_complete = True
    for model_id, resident in loaded.items():
        model = model_by_id.get(model_id)
        total_context = model.get("loaded_context") if isinstance(model, dict) else None
        parallel = model.get("parallel_sequences") if isinstance(model, dict) else None
        work_model = resident.get("work_model")
        if not isinstance(work_model, bool) and isinstance(control_model, str) and control_model:
            work_model = model_id != control_model
        complete = (
            isinstance(model, dict)
            and model.get("metadata_verified") is True
            and model.get("residency_verified") is True
            and model.get("fresh") is True
            and _positive_integer(model.get("size_bytes"))
            and _positive_integer(total_context) and _positive_integer(parallel)
            and total_context % parallel == 0 and isinstance(work_model, bool)
        )
        if not complete:
            resident_facts_complete = False
            continue
        if isinstance(model.get("provenance"), str) \
                and model["provenance"].endswith("observed-allocation-only"):
            provenance = f"{model['provenance']};policy:config/model-policy.json"
        else:
            provenance = "lemonade:/api/v1/health;policy:config/model-policy.json"
        resident_models.append({
            "model_id": model_id,
            "model_bytes": model["size_bytes"],
            "work_model": work_model,
            "backend_context_tokens": total_context,
            "parallel_sequences": parallel,
            "context_tokens_per_sequence": total_context // parallel,
            "fresh": True,
            "observed_at": now,
            "provenance": provenance,
        })
    scheduling = _read_json(root / "state" / "scheduling-policy.json")
    verified = (
        registry_fresh and health_fresh and host_fresh and resident_facts_complete
        and resource_envelope["verified"] is True and isinstance(scheduling, dict)
    )
    return {
        "verified": bool(verified),
        "fresh": bool(verified),
        "stale": not bool(verified),
        "observed_at": now,
        "provenance": "lemonade:/v1/models;/api/v1/health;linux:/proc/meminfo;amdgpu:sysfs",
        "memory_available_gb": available / 1024 ** 3 if available is not None else None,
        "memory": {
            "gtt_total_gb": measured_gtt_total / 1024 ** 3 if measured_gtt_total else None,
            "gtt_used_gb": gtt_used / 1024 ** 3 if gtt_used is not None else None,
            "linux_total_gb": total / 1024 ** 3 if total else None,
            "linux_available_gb": available / 1024 ** 3 if available is not None else None,
        },
        "load_average": list(os.getloadavg()),
        "models": models,
        "host": host,
        "resident_models": resident_models,
        "resource_envelope": resource_envelope,
        "scheduling_policy": scheduling,
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
    resident_verified = (model.get("loaded") is True
                         and model.get("residency_verified") is True)
    if not _positive_integer(maximum_model_bytes) or (
            not resident_verified and _positive_integer(model_bytes)
            and model_bytes > maximum_model_bytes):
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
    preallocated = model.get("preallocated_context_tokens")
    pool_resident = (resident_verified and _positive_integer(preallocated)
                     and preallocated == model.get("loaded_context")
                     and 0 < backend_context <= preallocated)
    incremental_kv = 0 if pool_resident else kv_estimate
    maximum_kv_bytes = envelope.get("maximum_kv_bytes")
    if maximum_kv_bytes is not None and (
            not _positive_integer(maximum_kv_bytes) or incremental_kv > maximum_kv_bytes):
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
                or protected_host + coin_reserved + load_demand + incremental_kv > host_available):
            reasons.append("host_capacity")
        gtt_used = envelope.get("gtt_used_bytes")
        envelope_gtt_limit = envelope.get("gtt_limit_bytes")
        gtt_limit = min(envelope_gtt_limit, policy_gtt_limit) \
            if _positive_integer(envelope_gtt_limit) and _positive_integer(policy_gtt_limit) else None
        if gtt_used is not None or gtt_limit is not None:
            if (not isinstance(gtt_used, int) or isinstance(gtt_used, bool) or gtt_used < 0
                    or not _positive_integer(gtt_limit)
                    or gtt_used + load_demand + incremental_kv > gtt_limit):
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
        "incremental_kv_bytes": incremental_kv,
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
    raise RuntimeError(
        f"model {model_id!r} requires privileged resource-control loading: {reason}"
    )
