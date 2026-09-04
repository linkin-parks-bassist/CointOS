"""Strict JSON object decoding shared by survival-plane boundaries."""

import json


def decode_json_object(payload: str | bytes, name: str) -> dict:
    """Decode one JSON object while rejecting duplicate member names."""
    try:
        value = json.loads(payload, object_pairs_hook=_object_without_duplicate_fields)
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid {name} JSON") from error
    if type(value) is not dict:
        raise ValueError(f"invalid {name} fields")
    return value


def _object_without_duplicate_fields(pairs: list[tuple[str, object]]) -> dict:
    value = {}
    for key, member in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON field {key!r}")
        value[key] = member
    return value
