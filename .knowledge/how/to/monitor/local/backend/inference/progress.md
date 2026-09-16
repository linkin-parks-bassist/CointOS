---
status: "unverified"
created_at: "2026-09-15T00:21:51+10:00"
scope: "local"
source: "actual owned backend /slots snapshots; inference_proxy.py _backend_json and backend identity; local model b10723 2026-09-15"
---

For an owned active CointOS run, read its inference lease credential backend_identity and call inference_proxy._backend_json(identity.backend_base, /slots), preserving incarnation/loopback scope and origin-path addressing. On installed llama-server b10723, slots expose is_processing, n_prompt_tokens, n_prompt_tokens_processed, n_prompt_tokens_cache and next_token[].n_decoded/n_remain/has_next_token. Compare read-only snapshots to distinguish prefix ingestion from active decode. In the 2026-09-15 local worker observation, a 76222-token request reused 70831 cached prompt tokens, processed 5386 and had decoded5 with4091 remaining. These counters establish activity/prefix reuse for that round, not completed work or durable state-switch qualification. Verify tool states/artifacts and actual completion separately. Review field names on backend-version changes.
