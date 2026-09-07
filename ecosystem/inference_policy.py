"""Fixed or shared context allocation policy for the local Qwen backend.

Reads a candidate INI slot policy describing how work request slots consume
backend context. ``context_mode = fixed`` reserves one full context per work
slot, so ``backend_context_tokens`` must equal
``work_slots * context_tokens_per_slot``. ``context_mode = shared`` lets
every work slot draw from one shared pool, so ``backend_context_tokens``
must be at least ``context_tokens_per_slot`` and is not tied to the slot
count. This helper does not implement shared KV caching or model residency,
and it is not wired to any caller until separately integrated and activated.
"""

from __future__ import annotations

import configparser
from pathlib import Path

CANONICAL_KEYS = (
    "work_slots",
    "front_slots",
    "context_tokens_per_slot",
    "backend_context_tokens",
    "context_mode",
)
OVERRIDABLE_KEYS = (
    "work_slots",
    "context_tokens_per_slot",
    "backend_context_tokens",
    "context_mode",
)
CONTEXT_MODES = ("fixed", "shared")
MODEL_SECTION_PREFIX = "model:"


def _positive_int(value: str, where: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise ValueError(f"{where}: {value!r} is not an integer") from None
    if number <= 0:
        raise ValueError(f"{where}: {value!r} is not a positive integer")
    return number


def _context_mode(value: str, where: str) -> str:
    if value not in CONTEXT_MODES:
        raise ValueError(
            f"{where}: {value!r} is not one of {', '.join(CONTEXT_MODES)}"
        )
    return value


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


def _section_values(parser: configparser.ConfigParser, section: str) -> dict:
    values = {}
    for key in parser.options(section):
        raw = parser.get(section, key)
        where = f"{section} {key}"
        if key == "context_mode":
            values[key] = _context_mode(raw, where)
        else:
            values[key] = _positive_int(raw, where)
    return values


def _check_consistency(values: dict, where: str) -> None:
    per_slot = values["context_tokens_per_slot"]
    pool = values["backend_context_tokens"]
    if values["context_mode"] == "fixed":
        expected = values["work_slots"] * per_slot
        if pool != expected:
            raise ValueError(
                f"{where}: fixed backend_context_tokens {pool} does not "
                f"equal work_slots * context_tokens_per_slot ({expected})"
            )
    elif pool < per_slot:
        raise ValueError(
            f"{where}: shared backend_context_tokens {pool} is smaller "
            f"than context_tokens_per_slot {per_slot}"
        )


def _validate(parser: configparser.ConfigParser) -> None:
    if parser.defaults():
        raise ValueError("inference policy must not use [DEFAULT] values")
    if not parser.has_section("inference"):
        raise ValueError("inference policy requires an [inference] section")
    keys = set(parser.options("inference"))
    missing = set(CANONICAL_KEYS) - keys
    unknown = keys - set(CANONICAL_KEYS)
    if missing:
        raise ValueError(
            f"inference policy [inference] is missing {sorted(missing)}"
        )
    if unknown:
        raise ValueError(
            f"inference policy [inference] has unknown keys {sorted(unknown)}"
        )
    values = _section_values(parser, "inference")
    _check_consistency(values, "[inference]")
    for section in parser.sections():
        if section == "inference":
            continue
        if not section.startswith(MODEL_SECTION_PREFIX):
            raise ValueError(
                f"inference policy has unknown section {section!r}"
            )
        name = section[len(MODEL_SECTION_PREFIX):]
        if not name:
            raise ValueError(
                f"inference policy {section!r} has an empty model name"
            )
        keys = set(parser.options(section))
        if not keys:
            raise ValueError(f"inference policy override {section!r} is empty")
        unknown = keys - set(OVERRIDABLE_KEYS)
        if unknown:
            raise ValueError(
                f"inference policy {section!r} has unknown keys {sorted(unknown)}"
            )
        merged = dict(values)
        merged.update(_section_values(parser, section))
        _check_consistency(merged, section)


def load_inference_policy(path: Path, model_id: str | None = None) -> dict:
    """Load the context allocation policy for one model selection.

    ``model_id`` selects an optional ``[model:NAME]`` override of any
    canonical key except ``front_slots``; a missing selection or override
    falls back to the global ``[inference]`` values. Every section is
    validated, and every override is validated merged over the globals,
    regardless of the selection. The result contains exactly the five
    canonical keys.
    """
    parser = _parse(path)
    _validate(parser)
    policy = _section_values(parser, "inference")
    if model_id is not None:
        section = f"{MODEL_SECTION_PREFIX}{model_id}"
        if parser.has_section(section):
            policy.update(_section_values(parser, section))
    return {key: policy[key] for key in CANONICAL_KEYS}
