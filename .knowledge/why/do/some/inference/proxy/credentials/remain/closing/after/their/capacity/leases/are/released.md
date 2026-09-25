---
status: green
revised_at: "2026-09-26T03:53:51+10:00"
---

The 12 older proxy credentials remained in `closing` after R3 had already accepted and persisted release of their matching inference-capacity leases. The exact historical interruption point is not known. The proxy finalization path required its own `last_backend_termination` and `released_sequence`, so it could not finish bookkeeping from an already released capacity lease. This was not evidence of occupied GPU capacity.

`reconcile_released_proxy_credentials` in `ecosystem/inference_proxy.py` now adopts only an existing authoritative R3 release. Under the workload/capacity/proxy lock order it requires a `closing` or `releasing` credential, no in-flight requests, an ended exact bound process, the same lease ID and release binding in the credential, capacity lease, and accepted observation, plus the accepted observer identity/evidence. It then revokes the bearer and stores the released sequence without issuing another capacity release or claiming a new physical termination. Unmatched or live records remain untouched. `reconcile_available_capacity` invokes this bounded bookkeeping step before its normal dead-owner scan.

The installed runtime's 12 legacy matches were reconciled with this dedicated function; `cointos-health --json` then showed 468 revoked proxy credentials, 468 released inference leases, 2253 quiescent worker leases, and the emergency gate still draining. This is an operational snapshot, not a promise about future state.

A separate focused integration test checks no second capacity release, but is not run by the startup proof because it writes a temporary fixture.

The side-effect-free exact-match test passes; it rejects active capacity, live owners, in-flight requests, and mismatched bindings.

Proof:

```bash
python3 -B -c 'from tests.test_inference_enforcement import test_released_sequence_adoption_requires_exact_dead_binding; test_released_sequence_adoption_requires_exact_dead_binding()'
```
