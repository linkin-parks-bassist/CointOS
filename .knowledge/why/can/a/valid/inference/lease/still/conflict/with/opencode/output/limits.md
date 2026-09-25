---
status: green
revised_at: "2026-09-14T22:38:56+10:00"
---

A lease fitting the backend's larger cap does not mean OpenCode may request that larger cap. The previous validate_launch_capacity returned the live record unchanged even if the lease allowed less output; opencode_environment encoded the record's larger output, whereas _validate_request_binding requires body.max_tokens to equal the lease max_output_tokens. A 128-token lease versus a 2048-token record can therefore produce incompatible requests. This is a source-level integration defect, not a reproduced cause of David's live session deaths.

constrain_launch_capacity now validates that the lease fits the measured record, checks admitted prompt plus output fits admitted context, and returns a copied record whose opencode_context_tokens and opencode_output_tokens are the admitted lease terms. Observed effective_context_tokens/effective_output_tokens and incarnation evidence are preserved. The executor uses this constrained record. The observable wrapper revalidates inherited proxy-config allowances against fresh live facts and preserves smaller admitted terms instead of expanding them. Ordinary direct launches use the fresh policy-limited live allowance. Pure validation still returns its input record unchanged; configuration constraint is a separate operation.
