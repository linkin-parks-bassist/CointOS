---
status: green
revised_at: "2026-09-17T14:26:31+10:00"
---

There is currently no importable `tests.test_opencode_observable` module and no dedicated test file for `scripts/opencode_observable.py`. Existing indirect coverage exercises it through managed/executor launch paths. For a narrow wrapper-only change during MVP bringup, run `python3 -m py_compile scripts/opencode_observable.py`, the relevant existing managed/executor suites, and a bounded direct check of the changed pure stream-classification behavior. Do not invent a regression-test module solely to satisfy the probe.

A direct import from the repository root fails because the script imports sibling module `worker_monitors` as a top-level module. Add the repository `scripts` directory to `sys.path` before loading `scripts/opencode_observable.py` with `importlib`, matching how direct script execution places its directory on the import path.