---
status: green
revised_at: "2026-09-15T05:13:51+10:00"
---

ecosystem/workload_control.py release_worker validates and persists one replay-consistent outcome and moves the lease to release_requested unless already observed_stopped. An acquired worker whose process is None can become quiescent through observe_workers with an attested stopped observation after release; registered workers require matching process and backend/inference absence evidence. Do not assume release_worker alone removes occupancy. Automatic native launch setup must retain acquired worker identity before spawning and close it if setup fails.

_apply_observations classifies never_spawned or presence of reaped_spawn as an attested stop reserved for a lease with process=None. If that attestation is supplied to a registered lease, it sets dead_unreconciled even when top-level PID/start ticks match. Registered cleanup must instead supply matching pid/process_start_ticks and explicit process_group_alive=False, backend_request_active=False and inference_lease_active=False (plus checkpoint_observed=True if required); then a release_outcome permits quiescent. Observation validation accepts reaped_spawn payloads but does not make them valid for registered leases. Source: ecosystem/workload_control.py _apply_observations/_attested_stop and observation validation.

Worker leases are entries in the leases map of root/state/workload-control.json, protected by root/state/workload-control.lock. They are not individual files under state/worker-leases; an empty glob there is not evidence of no leases. _locked_state loads and atomically rewrites this shared state only when dirty. Inspect the current worker lease by its durable worker_lease_id in that map. Evidence: ecosystem/workload_control.py _locked_state and _read_state.
