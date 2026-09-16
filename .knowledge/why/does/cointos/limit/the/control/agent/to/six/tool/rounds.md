---
status: "unverified"
created_at: "2026-09-16T04:32:14+10:00"
scope: "local"
source: "current ecosystem/control_agent.py and focused qualification through 2026-09-16"
updated_at: "2026-09-17T09:56:37+10:00"
---

CointOS no longer limits Cointelprofessional to six tool rounds. `control_agent.respond` uses an open loop and continues until the model selects exactly one valid terminal tool. Bare prose, invalid or multiple terminal calls, ordinary tool results, and empty terminal payloads receive corrective context and another inference round.

Stopping boundaries are explicit cancellation, authorization or panic handling, priority/resource suspension, transport failure with durable retry, or a valid `publish_followup`/`finish_silently` decision. A direct injected sequence completed on inference round eight, which the former `MAX_TOOL_ROUNDS = 6` path would have killed. Existing optional-role and managed-inference checks pass, and installed deep control also has a 32000-token output allowance with no arbitrary elapsed deadline.