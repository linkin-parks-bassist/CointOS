---
status: green
revised_at: "2026-09-26T03:18:07+10:00"
---

`tests/test_opencode_compaction.py::_execute_context_case` drives `ecosystem.executor.execute_next` in a temporary CointOS root. Its fake `realize` must return the selected model as well as `state`: the executor compares a fresh post-realization route with `realization["model"]` before launch. A fresh session (no retained `opencode_session`) also needs a valid `task_contract`, because launch takes the working directory from its scope. Use `task_contracts.default_task_contract` for this ordinary-work fixture. A missing model in the fake realization causes a route-convergence defer; a missing contract causes `KeyError` only in the fresh-session case. The fixture now supplies both. Evidence: `python3 -m unittest tests.test_opencode_compaction -q` passes all five cases, and the combined compaction/executor/evidence run passes 62 cases. This does not qualify live OpenCode compaction.
