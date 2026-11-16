---
status: green
revised_at: "2026-11-06T11:29:54+11:00"
---

Legacy llama.cpp target-only snapshots lack draft history; a paired-MTP patch cannot reconstruct omitted history. A previously qualified paired bundle is absent on halomit. Current packaged b11393 still saves target-only state; the state-preservation and server-build owners distinguish current behavior from historical qualification. Do not infer semantic corruption or a rumination cause merely from missing draft state.

Gufo DFlash2 is the baseline and has a separate snapshot ABI/directory; it cannot reuse either llama format or Gufo AR snapshots. The authorised original-steer retry currently uses llama and fresh RAM/disk cache namespaces, preserving conversation history while avoiding old target states. The steering owner holds active configuration and rollback.
