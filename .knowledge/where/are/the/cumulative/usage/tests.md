---
status: green
revised_at: "2026-09-25T22:01:08+10:00"
---

Cumulative execution-budget behavior is tested in `tests/test_cumulative_usage.py`. It covers accumulation across rounds, run-slice reset, near-limit checkpointing, final output accounting during preemption, and persistence before reconciliation. Run it deliberately with `python3 -m unittest tests.test_cumulative_usage -q`; behavioral proof leaves should select the smallest individual test that proves their claim so routine knowledge-tree proof checks stay fast.
