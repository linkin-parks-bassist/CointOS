---
status: green
revised_at: "2026-11-16T22:04:26+11:00"
---

After restoring the original model identity, native lanes and shared clients, request a short synthetic reply through /v1/private/chat/completions on the configured gateway port. Use a newly generated independent bearer key, model default, temperature zero, a small max_tokens value and chat_template_kwargs.enable_thinking=false. Do not reuse an agent/Coin credential or an ordinary conversation. Require actual generated tokens and a valid reply, then run cointos check. That CLI reads ledger health; it does not itself generate a completion.

Source contracts: gateway.identity treats unissued keys as the user; the private route derives an independent conversation from the key's SHA-256, bypasses retained message/history diagnostics and requires a resident-state backend. The backend facade reports the selected model's state support. Verify the live recipe supports it before probing. Use synthetic content only and retain the response without the key as evidence. This checks native generation recovery and routing, not broad answer quality, tool use or sustained reliability. The Halogen host trial completed this recovery probe. The deployed Halogen default also returned HALOGEN IS LIVE through the private gateway; how/to/integrate/halogen/with/cointos.md owns that evidence.
