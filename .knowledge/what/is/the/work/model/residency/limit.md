---
status: green
revised_at: "2026-09-26T04:15:15+10:00"
---

`config/resource-policy.json` currently sets `inference_capacity.maximum_work_models` to 1. `ecosystem/inference_capacity.resource_envelope` enforces that as a count of distinct resident models marked for work plus proposed nonresident model IDs in active leases. It does not cap the number of parallel inference sequences within one work model and does not name Qwen; those limits come from fresh backend allocation and a qualified profile. The two Lemonade LLM residency positions are a separate backend limit, with one currently occupied by the pinned small control model. Thus the current policy can run multiple Qwen work lanes on one work model, but does not qualify simultaneous distinct work-model residency. Raising this cardinality should follow measured memory headroom and live multi-model admission/rollback qualification, not a hardcoded assumption that two LLM positions always mean two work models.

The pure model-cardinality test passes: two sequences for one work model remain safe while two distinct work models exceed the configured limit.

Proof:

```bash
python3 -B -c 'from tests.test_inference_capacity import test_work_model_limit_counts_models_not_parallel_sequences; test_work_model_limit_counts_models_not_parallel_sequences()'
```
