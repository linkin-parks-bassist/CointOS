---
status: green
revised_at: "2026-09-16T02:57:18+10:00"
---

CointOS requires every model record to carry a positive `supported_context_quantum`, rejects routes without it, and rounds the selected per-sequence context down to a multiple. This field is not supplied by Lemonade's unloaded-model registry, so it prevents otherwise size/context/capability-qualified downloaded models from reaching the existing load producer.

The requirement was introduced by commit `33ab8191ce9c63bbb700766c28796fa94d1a1a96` on 2026-09-05 in a refactor titled `validate model and arbitrary context routes`. The commit created synthetic values such as 1024 and 3072 and tests for rounding, but its message and diff contain no observed llama.cpp/Lemonade constraint or source for a per-model quantum. Later resident-layout work obtains exact allocated context and per-sequence context directly from the live backend; it does not establish a registry-time quantum for unloaded models.

Under the current availability policy, an absent invented quantum must not cause terminal or indefinite false unavailability. For fixed unloaded routes, use the positive context bounded by the registry advertisement and fresh resource envelope directly; the backend load/postcondition remains the authority and failure retains the request for retry. For live shared pools, preserve strict observed allocation coherence and use the observed per-sequence capacity directly. Keep `supported_context_quantum` as optional descriptive legacy metadata if present, but do not make it an admission requirement or allocation-change field.

Next check: implement this narrow removal in `ecosystem/models.py`, run existing model-admission checks and a direct missing-quantum route check, then proceed to the independent `parallel_sequences` source decision.

Implementation attempt 2026-09-16: an observable Qwen3.8 worker received the combined metadata, routing-arithmetic, direct-check and two-leaf-update slice. After 45 minutes and multiple successful same-session compactions it had repeatedly read the 1125-line module, 1267-line test module and long KT owners but produced no source edit. The coordinator stopped the unit cleanly with session `ses_f5a55e6d8ffeVZ7noN01yTL52Q` retained. This is evidence that the combined slice exceeded the current local worker's practical task size, not evidence against the policy decision.

Revised next check: first dispatch only the two mechanical gate removals in `_verified_model_record` and `_model_route`; coordinator verifies. Then dispatch the context-arithmetic removal separately; coordinator owns checks and KT reconciliation.

Source implementation completed in two mechanically bounded observable worker slices on 2026-09-16. `metadata_verified` and route exclusion no longer require quantum; fixed and shared context allocation use the already-bounded exact `upper` without modulo rounding or `context:backend_quantum`. The legacy field remains descriptive when valid. Both workers exited 0 after `py_compile`; coordinator diff inspection confirmed scope.

The existing 50-case model-admission suite then produced exactly two failures: `test_non_candidate_context_quantum_is_allowed` expected 70,000 to round down to 67,584 using a synthetic 3,072 quantum, and `test_context_smaller_than_one_backend_quantum_defers` expected an otherwise available 65,536 context to be denied by a synthetic 131,072 quantum. These assertions encode the removed policy and are obsolete, not production regressions. Next check: delete those two old policy tests, rerun the existing suite, then qualify a missing-quantum unloaded route directly.

Final qualification: the two obsolete tests that exclusively enforced synthetic quantum rounding/denial were deleted without replacement. The remaining 48 existing model-admission tests pass. A coordinator direct check built a fresh unloaded fixed route with `supported_context_quantum: None` and a 70,000-token resource envelope; it was admitted at exactly 70,000 per-sequence/backend tokens, carried neither quantum exclusion, and passed fresh `validate_route`. The quantum barrier is resolved.

Next independent barrier: select `parallel_sequences` for an unloaded load request from explicit CointOS scheduling intent rather than requiring a nonexistent registry field.
