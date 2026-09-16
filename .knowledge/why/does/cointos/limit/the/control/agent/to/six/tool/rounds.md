---
status: "unverified"
created_at: "2026-09-16T04:32:14+10:00"
scope: "local"
source: "ecosystem/control_agent.py and current priority policy inspected 2026-09-16"
updated_at: "2026-09-16T04:48:41+10:00"
---

`ecosystem/control_agent.py` currently sets `MAX_TOOL_ROUNDS = 6`, iterates the Cointelprofessional deep control turn with `for _ in range(MAX_TOOL_ROUNDS)`, and raises `RuntimeError("deep control agent exceeded its bounded tool loop")` when the model has not selected exactly one terminal tool within six inference rounds. This can terminate a legitimate user/control session even though resources remain available and the exact conversation/tool results are still present in memory.

There is no measured backend or protocol reason for six in the source or project policy. The loop already instructs the model after missing bare-prose, multiple-terminal, and empty-message outcomes, and each ordinary tool result becomes part of the next message. The current priority policy requires the control session to keep progressing or wait for resources rather than fail at an arbitrary count.

Next implementation: remove `MAX_TOOL_ROUNDS`, use an open control loop, preserve every existing terminal/tool/error branch, and rely on explicit cancellation, authorization, panic, or resource waiting as the stopping boundaries. Separately review the fixed 1400 output-token and 180-second request arguments; removing the round limit does not qualify those values.

The six-round terminal barrier is removed in source. `respond` now uses an open control loop; all inference, corrective-message, tool execution, terminal-tool and exception branches are unchanged, and the unreachable terminal RuntimeError was deleted. The observable Qwen worker exited 0. Twenty-seven existing optional-role/managed-inference checks pass, and a direct injected sequence completed through `finish_silently` on inference round eight, which the old code could not reach. The first focused unittest command guessed nonexistent `tests.test_control_agent`; actual owners are recorded in `where/are/the/control/agent/tests.md`. Installation and the separate 1400-token/180-second argument review remain next.
