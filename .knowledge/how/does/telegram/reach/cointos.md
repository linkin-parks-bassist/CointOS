---
status: green
revised_at: "2026-11-25T09:18:40+11:00"
---

Coin is the independent Telegram service in cointos/coin.py. Credentials remain outside source. The daemon owns task lifecycle/inbox delivery; Coin owns conversational intake, replies and dispatch coordination.

## Five separate outcomes

1. Received: coin_input atomically/fsyncs allowed text/captions, user-attributed Telegram events, media descriptors and cursor before advancing polling. Invalid authority refuses unchanged. Original dates, IDs and reply references survive history rollover; removed recipients cannot execute.
2. Replied: fresh admitted input requires accepted text or media delivery to this chat before silent done; tools may run before replying. New mid-turn input reopens that obligation. Ordinary model output is internal. After acknowledgement, tool-free output in a direct turn asks for explicit send or done rather than silently returning. This closes answer loss through implicit return, not semantic abandonment through explicit done. Failed/empty sends do not count; wording and timely response remain model-dependent.
3. Dispatched: dispatch starts scoped work; queue_item routes product goals through planning. Both carry selected ordered originals, IDs, timestamps and reply references. Multiple inputs require input_ids; unknown IDs refuse and unrelated originals stay out. Retained per-user/chat follow-up owners support update_work without kill/revise/restart.
4. Consumed: durable inbox acceptance establishes delivery to the owner, not understanding or file changes. Inspect a settled owner's result before new work. Coin does not duplicate daemon lifecycle.
5. Verified: service observation follows declared handoffs/replacements before result verification. Managers/Operators own detailed supervision; Coin inspects exact returned evidence. report_result needs model-visible evidence_call_id from a successful current-turn fs_read/run_command. Refusals list available IDs. Durable user/chat/location/milestone records suppress repeats. Successful inspection identity does not prove relevance or fulfilment.

## Operation

Polling is independent of model work, wakes, attachment filesystem work and progress observation. Foreground tools still delay fresh-input admission. Plain text takes precedence; initial conversational admission is half history_messages and genuinely new arrivals may extend to history_messages. History batches twenty down by seven to thirteen; the archive survives. All accepted outgoing parts, including partial sends and notices, enter one locked archive with chat-scoped IDs. Mid-turn outgoing deliveries join the next prompt. Acceptance logs use hashes/IDs rather than text or credentials.

Captionless attachments save/route without model turns or history slots. Standing attachment_route rules have no expected-total quota; collisions preserve existing files and receipts prevent resurrection of organised files. Focused attachment/history owners define replay contracts.

Explicit send/report_result and Telegram message tools deliver content; output and done remain internal. how/do/coins/use/telegram/api/tools.md owns catalog discovery, uploads, downloads and events. Completion wakes/done-task watches suppress ordinary send, Telegram tools and continuation wakes until fresh user input. Ordinary reminders still use send. Failed turns/sends retry after error_pause_seconds; persistence failures reach native restart. Gateway SSE keepalives preserve scheduled waits; incomplete streams retain work. Actions/ambiguous acceptance may repeat. Permanent thread exit restarts the service. Startup connection failures retain retryable input; unit ordering alone does not establish API readiness.

coin_notifications queues explanations without canned notices. Current status and reply references ground interpretation; explanation handoff is not user delivery. Ownerless unheld blockage escalates after blocked_notify_seconds; paused/held work, recovery and runnable continuations suppress it. Routine mistakes stay local; requested results and direct questions still need answers. Retained follow-up descriptions can include failed historical owners without current lifecycle labels; native routing reliability remains unproved.

Coin uses work_model unless explicitly configured otherwise. Current clocks and source-time timelines accompany each round; echoed headers are removed without rewriting archives. General filesystem/Bash/knowledge/control tools remain available. Observational filesystem calls execute afresh; other identical effects reuse results. Dispatch identity includes current input. max_tool_rounds plus finishing_rounds bounds responses; exhaustion keeps input retryable. Reasoning effort only maps to a numerical cap when the configured budget map supplies one. Role/settings changes require a Coin-only refresh preserving durable state. See installation, filesystem, request-retention and reliability owners for qualification limits.
