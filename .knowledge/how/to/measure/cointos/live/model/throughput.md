---
status: green
revised_at: "2026-10-23T21:01:21+11:00"
---

Distinguish native phase speed, the dashboard's smoothed phase rates, and wall-time utilisation. Bind comparisons to the same model, lane, PID, task, session, sampling and template identity; a speed result without those controls is not a backend comparison.

Agent-card rates describe the last completed decode step. Llama uses predicted_n*1000/predicted_ms; Gufo uses generated tokens/generation_seconds, including pending-token consumption. These step rates require sixteen tokens and can remain visible while reading/waiting.

The dashboard top strip uses independent one-pole EMAs: alpha = 1 - exp(-phase_seconds / 10). Generation and prefill advance only during their own completed active work and hold during other phases or idle. MTP divides smoothed accepted/proposed draft-token rates during speculative generation. No proposals means undefined acceptance. performance.py owns this calculation; it is not a sixty-second wall-time window.

For a run-wide native generation rate, divide generation_tokens deltas by matching generation_seconds deltas. Output divided by observation wall time is a different utilisation diagnostic, including waits and prefill; never substitute it for generation speed. Use client capture timestamps and disclose HTTP-duration uncertainty rather than assuming ledger.updated_at is the capture time.

gpu_seconds includes preparation. Add active gpu_since at actual observation endpoints for occupied time. Its difference from generation_seconds includes prefill, cache save/restore, adapter work and boundary skew; it is not a pure prefill timer. thought.read is a high-water mark, not a counter of newly processed input; use direct phase instrumentation and reading/held state.

Switch events separate save_seconds, transfer_seconds and restore_seconds. Transfer includes readiness/admission and disk-to-RAM copying; native restore is separate. Transfer/restore totals include every attempted compatible candidate. restore_tier names the last attempted tier, or null. A refused bring_back has no native restore; failed native restores retain their time and broken_snapshot before shorter candidates are tried. Overall seconds extends through ledger update, excluding later final event-file publication. Following prefill/generation and asynchronous spills are separate. Save admission can include required RAM reclamation; do not attribute all remaining preparation to prefill or infer a decode speedup from an I/O-lock repair.

Gufo thought.decode and agent/Coin speculation totals retain matching generation and draft denominators. Use deltas for weighted acceptance or tokens/round; include correction/frontier tokens when explaining tokens/round. A Python footer-hash read does not isolate native serializer/checksum cost. Storage and backend measurement owners retain qualification evidence.

Requested Coin reports require installed identity and checked assistant history/transport acceptance, not a wake acknowledgement. Source imports use source state. Isolate diagnostic messages and model probes from real user work; preserve clients, sessions, spend and authority. Group comparisons to limit interruption and verify resumed useful generation. Restoration alone is not useful-throughput acceptance.
