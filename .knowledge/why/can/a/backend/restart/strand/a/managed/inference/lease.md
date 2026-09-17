---
status: "unverified"
created_at: "2026-09-17T13:06:43+10:00"
scope: "project local"
source: "inference_proxy.py repair; installed time-slice/restart recovery with exact PID evidence 2026-09-17"
---

`completed_run_termination()` previously proved closure only when the same recorded backend identity could be observed idle, or when prior request-completion evidence already existed. If Lemonade restarted that backend between cancellation and reconciliation, `backend_snapshot()` exposed a new PID/start-tick identity on the same endpoint. Same-identity slot probes correctly refused to attribute the new backend's idle state to the old request, but there was no path accepting the stronger fact that the exact old backend process had ended. The credential remained `closing`, inference stayed allocated, and the retained worker stayed `reconciliation_required` indefinitely.

The recovery path now checks the recorded backend identity with `_bound_process_ended()` before same-instance slot probing. Absent PID, zombie state, reused PID with different kernel start ticks, or the other existing exact-process end conditions prove that backend instance ended. It writes a `reconciled_absent` backend-observation record containing the old identity and process evidence, then uses the existing verified termination, credential revocation, sequence release, worker quiescence, and exact-session continuation path. It does not infer termination from a changed URL, model name, timeout, or the new backend being idle.

Installed qualification occurred when `ReservePolicyDeduplicator` was preempted after its scheduler slice. Its credential recorded Qwen3.8 backend PID `2407199`; Lemonade later exposed the replacement as PID `2409199`. Before repair, repeated reconciliation could not close. After installation, the exact old PID/start-tick check produced durable `reconciled_absent` evidence, recovery released the old allocation, and generation 2 resumed the same OpenCode session. Source compilation and 92 existing inference-enforcement/operator-inference/executor checks pass. Recheck after changing backend identity, process evidence, proxy termination records, or Lemonade restart behavior.
