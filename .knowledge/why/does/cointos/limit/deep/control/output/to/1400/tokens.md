---
status: "unverified"
created_at: "2026-09-16T04:48:55+10:00"
scope: "local"
source: "current control-agent source, installed service configuration, and focused qualification through 2026-09-16"
updated_at: "2026-09-17T09:55:56+10:00"
---

CointOS no longer limits deep control output to 1400 tokens. The failed first attempt to raise the allowance exposed the real issue: deep work was still bound to exact-model Qwen3.5, whose context could not fit the prepared request plus a 32000-token output reserve. The final repair separates the lanes: Qwen3.5 remains the low-prefill first-contact model, while the deep/action service selects Qwen3.8 and requests the canonical 32000-token allowance.

Deep/action inference also has no arbitrary 180-second elapsed deadline. It passes `timeout=None` through managed admission to `urllib.request.urlopen(timeout=None)`. Explicit caller cancellation and higher-priority preemption still interrupt the request through the qualified proxy socket-shutdown path; ordinary managed-inference callers retain the compatibility timeout default.

Focused control and managed-inference checks pass, installed assets contain the change, and the live control worker runs the installed Qwen3.8 configuration. The remaining Cointelprofessional concern is answer verification quality for demanding work, not output or elapsed-time starvation.