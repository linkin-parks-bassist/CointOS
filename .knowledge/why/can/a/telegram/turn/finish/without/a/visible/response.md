---
status: "unverified"
created_at: "2026-09-16T10:47:51+10:00"
scope: "project local"
source: "live telegram-999135383 record, inference/proxy state and repaired control_agent.py/inference_proxy.py 2026-09-16"
---

A live 2026-09-16 turn had no visible response because the fast Qwen3.5 request failed during stale installed cleanup-policy handling, while the retained Qwen3.8 deep turn later selected finish_silently on the assumption that an initial response existed. A separate interrupted qualification request had also left a claimed-but-unidentified proxy request holding an idle Qwen3.8 sequence; exact-incarnation idle reconciliation released it and allowed the retained deep turn to run.\n\nThe deep controller now records whether a nonempty initial response was actually supplied. When none was delivered, finish_silently is rejected inside the same model loop and the controller is instructed to use publish_followup with visible text. Proxy reconciliation also closes a dead claimed request with no request identity when fresh observation of the exact backend incarnation proves every slot idle. Fast first contact remains Qwen3.5 for latency; deep/action remains Qwen3.8.\n\nIf silence recurs, inspect the durable control turn's front_state and deep_state, then the newest native inference records and capacity/proxy leases. Do not infer delivery from model completion alone.
