---
status: green
revised_at: "2026-09-16T03:39:21+10:00"
---

`ecosystem.models.realize(decision, inventory)` consumes the public decision envelope produced by `ecosystem.models.route`, not the internal record returned directly by `choose_route`.

The decision must have `valid` true and an action other than `defer`. It identifies the selected model through `model`, supplies the per-sequence allocation through positive integer `context_tokens`, and carries positive `backend_context_tokens` and `parallel_sequences` satisfying `backend_context_tokens == context_tokens * parallel_sequences`. Other selected-route fields may accompany these values.

For a controlled exact-model qualification that calls `choose_route` over a focused inventory, construct the same public envelope before calling `realize`: retain the selected fields and add `action: "load"`, `model` equal to the selected model ID, `context_tokens` equal to `context_tokens_per_sequence`, `valid: true`, and a truthful reason. Passing the internal selected record directly fails before mutation with `ValueError: cannot realize a deferred or invalid model route`.
