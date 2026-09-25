---
status: green
revised_at: "2026-09-26T04:46:34+10:00"
---

The dedicated fast suite is `tests/test_backend_profile_scheduler.py`. It calls `ecosystem.backend_profile_scheduler.assess_profiles` with inert resident observations and mocked policy/allocation inputs; it never calls Lemonade, changes a backend profile, or writes runtime state. It covers a shrink-dwell-delayed first model, a failed-target-cooldown-delayed first model, preservation of the first deferred reason when no model can change, eligible growth preceding an alphabetically earlier shrink, and shrink selection when no growth is needed. The companion `tests/test_backend_profile_policy.py` has three pure demand-count tests for stale ready-model hints, active physical binding, and invalid pending routes. The broader `tests/test_inference_capacity.py` and `tests/test_model_admission.py` cover neighboring allocation and routing contracts, but none substitute for live multi-model qualification.

The five scheduler candidate-scan tests pass.

Proof:

```bash
python3 -B -m unittest tests.test_backend_profile_scheduler -q
```
