---
status: green
revised_at: "2026-10-19T17:04:25+11:00"
---

Peers share one physical Qwen lane, so input preparation, generation and snapshot transfers compete for service. Large displayed prompt counts do not establish cold reads. Inspect the restored prefix and unread suffix: a live worker restored 90,956 of 91,950 tokens, while an auditor restored 56,101 of 62,692. The latter needs a 6,591-token extension; the count alone cannot distinguish new data from rewritten tails.

workflow-observation-20261019/phase-summary.json records 120.80 seconds under live 60-second/96-token settings: 727 completed native generation tokens in 62.259 generation seconds, against 115.033 charged lane seconds. That is approximately 11.7 native and 6.0 wall tokens/s. The difference includes preparation, snapshots and transfers; in-flight edge work is not fully attributed. All four agent identities survived, autonomy remained on, minimum available memory was 32 GB and PSI stayed zero. This observation is not a matched context-size or scheduler comparison.

New tool output can require substantial reading. A recovery Operator's prompt grew from 26,796 to 55,831 tokens after broad directory/task inspection returned 51,187 and 20,970 characters; restoring 27,351 was genuine reuse. Query named tasks/branches instead of enumerating unrelated directories. Native assistant/tool whitespace normalization can also invalidate a tail; the rendering owner retains the reproduction, installed exact-history repair and its validation limits.

Installed task inspection presents the canonical queue brief and full checked receipt once, keeping duplicate execution metadata behind history. An existing task view shrank from 19,829 to 11,545 characters with its receipt preserved; focused source/installed checks and live inspection verify that projection. This reduces avoidable input, not genuinely new evidence.

Checkpoint-aware read sharing is installed. A 113,938-token manager read resumed from 23k and monopolized the lane for over 15 minutes; tests preserve partial reads across peers and protect successful reads when saves fail. The lottery can still produce long waits despite correct average shares. Accounting prototypes reduce sampled tails but increase switching and remain uninstalled. The scheduler owner governs policy and limits.

Zero completed thoughts does not prove an idle run: inspect active prompt/read/generated counters and charged work before diagnosing deadlock. Sustained latency, transfer costs and useful-throughput acceptance remain open.
