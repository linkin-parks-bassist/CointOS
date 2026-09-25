---
status: green
revised_at: "2026-09-16T03:37:45+10:00"
---

`ecosystem.models._model_route` requires `request["requirements"]` to be a dictionary containing both `required_capabilities` and `minimum_context_tokens`. `required_capabilities` must be a list of strings; every item must occur in the model's capabilities. `minimum_context_tokens` must be a non-boolean integer at least zero. Missing or invalid fields defer with `requirements:required_capabilities` or `requirements:minimum_context_tokens`.

The request's `prompt_tokens`, `tool_tokens`, `max_output_tokens`, and `handoff_tokens` are read separately as context reserves. Their values must be non-boolean integers at least zero after configured defaults supply absent claims.

A 2026-09-16 live-reclamation smoke probe incorrectly used `requirements.capabilities`; route selection deferred before any backend mutation. Use the exact schema above for the retry.
