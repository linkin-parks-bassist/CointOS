---
status: green
revised_at: "2026-09-26T01:48:45+10:00"
---

A parked proxy credential retains the OpenCode session while releasing its physical sequence. A physical llama.cpp `--parallel` change alters `parallel_sequences` and total `backend_context_tokens`; the original strict route comparison would return `route_changed:*` and leave the request in a 425 reacquisition loop. The installed `models.rebind_parked_route()` path now permits those physical pool fields to change only for a previously released or ready-for-revalidation lease, and only when exact model identity/size facts, context mode, per-sequence context and output promise remain unchanged. `inference_capacity.reserve_sequence()` uses this narrow rebind and defers all acquisition while the durable profile transition is fenced. Ordinary model realization cannot race the fence.

The installed fenced reload passed an idle manual 2→1→2 Lemonade round-trip, but no parked worker has yet been live-qualified across it. A transition that changes a logical promise still defers the worker; a backend reload can drop KV and cause re-prefill even when the logical OpenCode session survives. Automatic resizing therefore remains disabled pending a bounded parked-worker handoff check. See `how/does/cointos/reconfigure/physical/backend/parallel/profiles.md`.
