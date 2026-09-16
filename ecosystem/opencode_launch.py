"""Fresh limits and server read-back for observable local OpenCode launches.

This supplies capacity facts, not scheduler admission or tool authority.
"""
import copy
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.request

from ecosystem import models
from ecosystem.executor import _observe_worker_capacity, _load_capacity_policy
from ecosystem.inference_proxy import apply_opencode_capacity, validate_loopback_base
from ecosystem.inference_capacity import constrain_launch_capacity
from ecosystem.opencode_capacity import effective_inference_capacity
from ecosystem.opencode_client import load_capability_catalogue, qualified_opencode_capability


def derive_capacity(binary, model_id, root, clock=time.time):
    observation = _observe_worker_capacity(root, model_id, refresh_inventory=True, clock=clock)
    if observation is None:
        raise ValueError("fresh, consistent backend per-request capacity is unavailable")
    version = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=15)
    if version.returncode:
        raise ValueError("OpenCode version probe failed")
    capability = qualified_opencode_capability(
        version.stdout, load_capability_catalogue(Path(root) / "config/opencode-capabilities.json"))
    return effective_inference_capacity(observation, capability, _load_capacity_policy(root), clock())


def _merge(target, source):
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _merge(target[key], value)
        else:
            target[key] = copy.deepcopy(value)


def prepare_environment(command, environment, root):
    """Override inherited size claims without modifying user configuration."""
    env = dict(environment)
    config = {}
    if env.get("OPENCODE_CONFIG"):
        config = json.loads(Path(env["OPENCODE_CONFIG"]).read_text())
    if env.get("OPENCODE_CONFIG_CONTENT"):
        _merge(config, json.loads(env["OPENCODE_CONFIG_CONTENT"]))
    if not isinstance(config, dict):
        raise ValueError("OpenCode configuration must be an object")
    model_flags = [i for i, item in enumerate(command) if item in ("--model", "-m")]
    if not model_flags:
        if config.get("enabled_providers") == []:
            return env, None, None  # Explicitly inert viewer/process tests.
        raise ValueError("observable inference launch requires an explicit --model")
    if len(model_flags) != 1 or model_flags[0] + 1 >= len(command):
        raise ValueError("exactly one explicit --model is required")
    selected = command[model_flags[0] + 1]
    provider, _separator, model_id = selected.partition("/")
    if provider.casefold() != "lemonade":
        return env, None, None  # Hosted providers do not use this local backend.
    if not model_id:
        raise ValueError("local Lemonade selection requires a nonempty model ID")
    record = derive_capacity(command[0], model_id, root)
    provider = config.setdefault("provider", {}).setdefault("Lemonade", {})
    provider.setdefault("npm", "@ai-sdk/openai-compatible")
    provider.setdefault("name", "Lemonade (live capacity)")
    options = provider.setdefault("options", {})
    policy = json.loads((Path(root) / "config/model-policy.json").read_text())
    proxy_base = policy["inference_proxy"]["proxy_base"]
    # Keep a gated executor credential's transport; ordinary launches use Lemonade.
    if options.get("baseURL") != proxy_base:
        options["baseURL"] = models.BASE.rstrip("/") + "/v1"
    else:
        # A gated parent's configuration carries the smaller admitted allowance.
        # Revalidate it against fresh backend facts rather than expanding it.
        limits = provider.get("models", {}).get(model_id, {}).get("limit", {})
        record = constrain_launch_capacity({
            "model_id": model_id,
            "context_tokens_per_sequence": limits.get("context"),
            "max_output_tokens": limits.get("output"),
        }, record)
    validate_loopback_base(options["baseURL"])
    apply_opencode_capacity(config, record)
    # The inline layer wins over project/global size claims. It contains no secrets.
    overlay = {}
    apply_opencode_capacity(overlay, record)
    env["OPENCODE_CONFIG_CONTENT"] = json.dumps(overlay)
    env["OPENCODE_DISABLE_PROJECT_CONFIG"] = "true"
    fd = os.memfd_create("opencode-live-capacity", os.MFD_CLOEXEC)
    try:
        payload = json.dumps(config).encode()
        with os.fdopen(os.dup(fd), "wb") as stream:
            stream.write(payload)
        os.lseek(fd, 0, os.SEEK_SET)
        env["OPENCODE_CONFIG"] = f"/proc/self/fd/{fd}"
        return env, fd, record
    except BaseException:
        os.close(fd)
        raise


def verify_server_capacity(url, directory, record, expected_base, *, binary, root):
    """Check OpenCode's resolved model, then reobserve the backend incarnation."""
    import urllib.parse
    query = "?" + urllib.parse.urlencode({"directory": str(directory)})
    def get(path):
        with urllib.request.urlopen(url + path + query, timeout=10) as response:
            return json.load(response)
    config = get("/config")
    selected = "Lemonade/" + record["model_id"]
    if (config.get("compaction", {}).get("auto") is not True
            or config.get("small_model") != selected
            or config.get("agent", {}).get("compaction", {}).get("model") != selected
            or config.get("agent", {}).get("compaction", {}).get("disable") is True
            or config.get("provider", {}).get("Lemonade", {}).get("options", {}).get("baseURL") != expected_base):
        raise ValueError("OpenCode loaded conflicting compaction or backend configuration")
    providers = get("/provider").get("all", [])
    matches = [entry for entry in providers if entry.get("id") == "Lemonade"]
    if len(matches) != 1:
        raise ValueError("OpenCode did not load exactly one Lemonade provider")
    model = matches[0].get("models", {}).get(record["model_id"], {})
    expected = {"context": record["opencode_context_tokens"],
                "input": record["opencode_context_tokens"] - record["opencode_output_tokens"],
                "output": record["opencode_output_tokens"]}
    if any(model.get("limit", {}).get(key) != value for key, value in expected.items()):
        raise ValueError("OpenCode resolved model limits disagree with fresh per-request capacity")
    fresh = derive_capacity(binary, record["model_id"], root)
    if any(fresh[key] != record[key] for key in (
            "backend_incarnation", "effective_context_tokens", "effective_output_tokens", "opencode_version")):
        raise ValueError("backend capacity or client version changed during OpenCode startup")
