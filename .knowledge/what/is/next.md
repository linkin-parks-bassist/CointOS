---
scope: project local
status: "unverified"
source: "2026-09-17 reconciliation of current implementation, live services, defect owners, and David's active priorities"
review_when: Recheck after each completed item or priority change.
updated_at: "2026-09-17T12:53:53+10:00"
---

1. Audit the remaining 32 GiB protected-host, 8 GiB control, and 12 GiB load-transient byte reserves against live host pressure and actual load behavior. Determine whether `physical_capacity` and `inference_capacity` need separate copies or one canonical owner.
2. Measure serialized admitted prompts/tool schemas, streaming tails, completion JSON, and backend model/health documents against the proxy's fixed byte ceilings. Retain bounded parsing, but increase or derive any ceiling that can truncate legitimate maximum-context work.
3. Decide the Cointelprofessional verification path for demanding factual or mathematical work using evidence from real requests. Keep ordinary conversation cheap; invoke stronger review only when the front/deep decision or task type warrants it.
4. Reconcile Lemonade's live 1.48 GiB report for `gpt-oss-120b-mxfp-GGUF` with the installed 63.4 GiB registry record before routing or loading that model.
5. Continue the role redesign and chunking/dissolution pipeline after the allocator and remote control boundaries above are dependable.

The 64 GiB sysfs-domain observation no longer caps the qualified 100 GiB hardware allocation boundary, and the dead legacy 108 GiB admission gate is removed. Installed live saturation, restart recovery, and exact-session continuation pass. Use one observable Qwen3.8 worker at a time for concrete closed slices; keep source, installation, and these spine leaves synchronized.
