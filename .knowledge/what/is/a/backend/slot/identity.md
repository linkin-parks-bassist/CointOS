---
status: "unverified"
created_at: "2026-09-15T00:21:22+10:00"
scope: "local"
source: "inference_proxy.py backend_snapshot identity constructor; actual credential identity fields 2026-09-15"
---

ecosystem/inference_proxy.py backend_snapshot records identity fields gateway_base, backend_base, model_id, pid, process_start_ticks, boot_id, model_path and total_slots. It validates loopback residency, brackets backend props with kernel process identity checks, and requires positive total_slots and a model path. backend_base is the resident gateway-reported backend_url and may include /v1; it is not the backend_url key used in the separate OpenCode capacity record. Backend idle/slot observers reuse this exact identity for incarnation checks. An attempted progress lookup using backend_url returned no URL because it used the wrong record schema. Use the stored identity contract, not interchangeable field guesses.
