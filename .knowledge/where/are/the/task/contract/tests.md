---
status: "unverified"
created_at: "2026-09-16T04:14:41+10:00"
scope: "local"
source: "bounded rg of tests and unittest import failure on 2026-09-16"
---

Task-contract validation checks are in `tests/test_mvp_task_contracts.py`; the importable unittest module is `tests.test_mvp_task_contracts`. Budget accounting checks are separately in `tests/test_execution_budget.py` as `tests.test_execution_budget`.

There is no `tests/test_task_contracts.py` module. A 2026-09-16 focused command that guessed `tests.test_task_contracts` produced only a unittest import error; it did not indicate a production or assertion failure.
