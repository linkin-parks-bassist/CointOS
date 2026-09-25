---
status: green
revised_at: "2026-09-26T01:19:30+10:00"
verifiable: "true"
---

For a two-sequence resident model, demand for nine workers and ample estimated KV headroom cannot make the generic profile planner request more than a qualified ceiling of two sequences.

Proof:

```bash
python3 -B -c 'from ecosystem.backend_profiles import plan_parallel_profile as plan; p={"model_id":"Example-GGUF","parallel_sequences":2,"context_tokens_per_sequence":131072}; assert plan(p, 9, 8, 2, 1<<50, 131072)["target_parallel_sequences"] == 2'
```
