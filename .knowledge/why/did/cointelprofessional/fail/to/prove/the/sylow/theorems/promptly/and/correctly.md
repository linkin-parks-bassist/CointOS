---
status: "unresolved"
created_at: "2026-09-16T15:14:30+10:00"
updated_at: "2026-09-16T15:24:55+10:00"
scope: "project local"
source: "source repair and installed qualification 2026-09-16"
checked_at: "2026-09-16T15:24:36+10:00"
blocker: "The front truncation is repaired. Deep cancellation still does not reliably interrupt the proxy thread's blocking upstream read, and one model answer is insufficient to choose a general mathematical verification policy."
next_check: "Make inference-proxy cancellation actively interrupt the upstream socket before close, qualify the installed timeout path, then decide whether demanding proof requests need a verifier/reviewer stage or a stronger routed model."
---

For Telegram turn telegram-999135390 on 2026-09-16, the fast Qwen3.5 routing tool call was truncated under the 96-token output ceiling and rejected with an unterminated JSON string. No fast response was delivered. Deep Qwen3.8 inspected status, its first attempt later timed out and requeued, the five-minute disaster fallback fired, and the second attempt delivered after roughly 17 minutes. The delivered proof was not reliable: the existence argument omitted the free-action fact that makes the subset stabilizer order divide p^a and invoked induction without establishing the needed claim; the conjugacy argument inferred containment from normalization; and the count argument claimed a unique fixed Sylow subgroup without proving that two mutually normalized Sylow p-subgroups generate a p-subgroup. Recovery prevented message loss, but latency and mathematical correctness failed.

The front-path repair is now implemented and installed. `FAST_OUTPUT_TOKENS = 512` replaces both hardcoded 96-token requests. If `route_front_turn` arguments contain invalid JSON, `generate_front_decision` remembers the parse error and still evaluates assistant content; sanitized visible content becomes an immediate response with conservative `deep_required: true`. With no usable decision or content it raises the original invalid-tool error. Direct injected checks covered the 512-token forwarding, visible-content fallback, and preserved-error branch; `py_compile` and `git diff --check` pass. The Telegram service was restarted active from the installed payload.

Native run correlation isolated the deep delay. The first attempt entered several model/tool rounds; the final backend inference remained active for about 792 seconds even though managed inference has a 180-second timeout. `managed_inference.request` called proxy cancellation after its grace boundary, but `inference_proxy.cancel` only closed the `HTTPConnection` while its worker thread was blocked in `getresponse()` on a socket whose timeout had explicitly been set to `None`. That cross-thread close did not promptly interrupt the blocking read. The next repair is a bounded proxy change that shuts down the active upstream socket before closing it. Mathematical verification policy remains unresolved.