# Exercise heartbeats and handshakes

Trace a small sample across component boundaries: timer to service, queued job to
prepared context, executor run to verifier, verifier to root state, root state to
outbox, and outbox to conversation memory. Check both sides agree on identity,
state, timestamps, and responsibility. Look for orphaned work, premature success,
duplicate observers, silent failures, stale leases, and acknowledgements without
follow-through. Repair only bounded known faults; otherwise leave an evidence-rich
Auditor assignment.
