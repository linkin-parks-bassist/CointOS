---
status: green
revised_at: "2026-09-16T04:48:03+10:00"
---

Control-agent behavior checks are in `tests/test_optional_roles.py`, with managed inference fallback coverage in `tests/test_managed_inference.py`. There is no `tests/test_control_agent.py` module; attempting to invoke `tests.test_control_agent` produces only a unittest import error and does not indicate a production failure.
