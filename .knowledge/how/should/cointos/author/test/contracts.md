---
status: green
revised_at: "2026-10-18T02:15:42+11:00"
---

Test writers challenge plausible shortcuts, boundaries, invalid inputs and state transitions against the specification, asserting only the contract. Build witnesses through owner APIs; malformed inputs require a promised rejection. Verify construction reaches the tested API; an unimplemented adapter is not a permanent error contract. Capture rollback state before the failing call. Unconstructible valid failure witnesses are contract mismatches, not permission to invent constructors or weaken assertions.

Positive witnesses must obey the tested API's preconditions and other owning laws claimed by the packet, even when their validators are not implemented yet. Distinguish phase-local success from valid whole-pipeline behavior. A permissive partial builder cannot justify a positive witness the claimed final contract forbids. For each named property, vary an input that exercises it and observe its consequence. Supplying a hand-normalized fixture does not test normalization/deduplication; existing owner coverage must be identified rather than inferred from a label or unrelated build failure.

Register packet commands in test_policy.manifest (normally tests/contracts.json): entries have exactly covers (nonempty repository-relative targets) and command (nonempty argv running only that packet). The full suite runs every registered command. Build/execute artifacts in fresh invocation-owned directories with cleanup; fixed host /tmp or /var/tmp executables allow external builds to create false passes despite CointOS's advisory lock. Protected harness correction uses ordinary test-contract review. tests/test_external_validation.py demonstrates collision and checkout-owned repair. Semantic quality remains a model-review obligation; these rules are not a proof that a packet covers every law.
