"""The daemon's loopback API as the CLI, Coin and agents' commands reach it."""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from cointos import config as configuration

CONFIG = configuration.load()


class Unreachable(Exception):
    """The daemon is not answering (halted, restarting or not started)."""


def call(action: str, body: dict | None = None, timeout: float = CONFIG["timeouts"]["api_seconds"]) -> dict:
    """POST one control action. The daemon's refusal raises ValueError with its reason."""
    return _request(f"/api/{action}", json.dumps(body or {}).encode(), timeout)


def ledger() -> dict:
    return _request("/api/ledger", None, CONFIG["timeouts"]["api_seconds"])


def _request(path: str, data: bytes | None, timeout: float) -> dict:
    request = urllib.request.Request(configuration.api_url(CONFIG) + path, data=data,
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise ValueError(json.loads(error.read() or b"{}").get("error", str(error))) from None
    except (urllib.error.URLError, OSError) as error:
        raise Unreachable(f"cointosd is not reachable ({error}); start it with: cointos up") from None
