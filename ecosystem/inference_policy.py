"""Fixed-partition inference slot policy for the local Qwen backend.

Reads a candidate INI slot policy and selects fixed request-slot partitions
plus a fixed backend context partition (work_slots * context_tokens_per_slot).
This helper does not implement shared KV caching or model residency, and it
is not wired to any caller until separately integrated and activated.
"""

from __future__ import annotations

import configparser
from pathlib import Path

from ecosystem import cli

CONFIG_PATH = cli.ROOT / "config/inference.cfg"

REQUIRED_KEYS = ("work_slots", "front_slots", "context_tokens_per_slot")
OVERRIDABLE_KEYS = ("work_slots", "context_tokens_per_slot")
MODEL_SECTION_PREFIX = "model:"


def _positive_int(value: str, where: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise ValueError(f"{where}: {value!r} is not an integer") from None
    if number <= 0:
        raise ValueError(f"{where}: {value!r} is not a positive integer")
    return number


def _parse(path: Path) -> configparser.ConfigParser:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"cannot read inference policy {path}: {exc}") from exc
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    try:
        parser.read_string(text, source=str(path))
    except configparser.Error as exc:
        raise ValueError(f"invalid inference policy {path}: {exc}") from exc
    return parser


def _validate(parser: configparser.ConfigParser) -> None:
    if parser.defaults():
        raise ValueError("inference policy must not use [DEFAULT] values")
    if not parser.has_section("inference"):
        raise ValueError("inference policy requires an [inference] section")
    keys = set(parser.options("inference"))
    missing = set(REQUIRED_KEYS) - keys
    unknown = keys - set(REQUIRED_KEYS)
    if missing:
        raise ValueError(
            f"inference policy [inference] is missing {sorted(missing)}"
        )
    if unknown:
        raise ValueError(
            f"inference policy [inference] has unknown keys {sorted(unknown)}"
        )
    for key in REQUIRED_KEYS:
        _positive_int(parser.get("inference", key), f"[inference] {key}")
    for section in parser.sections():
        if section == "inference":
            continue
        if not section.startswith(MODEL_SECTION_PREFIX):
            raise ValueError(f"inference policy has unknown section {section!r}")
        name = section[len(MODEL_SECTION_PREFIX):]
        if not name:
            raise ValueError(f"inference policy {section!r} has an empty model name")
        keys = set(parser.options(section))
        if not keys:
            raise ValueError(f"inference policy override {section!r} is empty")
        unknown = keys - set(OVERRIDABLE_KEYS)
        if unknown:
            raise ValueError(
                f"inference policy {section!r} has unknown keys {sorted(unknown)}"
            )
        for key in keys:
            _positive_int(parser.get(section, key), f"{section} {key}")


def load_inference_policy(path: Path, model_id: str | None = None) -> dict:
    """Load the fixed-partition slot policy for one model selection.

    ``model_id`` selects an optional ``[model:NAME]`` override of
    ``work_slots`` and/or ``context_tokens_per_slot``; a missing selection or
    override falls back to the global ``[inference]`` defaults. Every section
    and value is validated regardless of the selection.
    """
    parser = _parse(path)
    _validate(parser)
    policy = {
        key: _positive_int(parser.get("inference", key), f"[inference] {key}")
        for key in REQUIRED_KEYS
    }
    if model_id is not None:
        section = f"{MODEL_SECTION_PREFIX}{model_id}"
        if parser.has_section(section):
            for key in OVERRIDABLE_KEYS:
                if parser.has_option(section, key):
                    policy[key] = _positive_int(
                        parser.get(section, key), f"{section} {key}"
                    )
    policy["backend_context_tokens"] = (
        policy["work_slots"] * policy["context_tokens_per_slot"]
    )
    return policy
