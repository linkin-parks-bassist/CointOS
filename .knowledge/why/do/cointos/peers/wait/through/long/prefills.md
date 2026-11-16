---
status: green
revised_at: "2026-11-10T06:23:38+11:00"
---

Peers share one physical Qwen lane. The ledger has one logical lane; server slots are resident contexts, not concurrent streams. On one logical lane aggregate generation cannot exceed single-stream decode, because prefill and preparation own the rest of the wall. A 31-second sample processed 6,144 prompt tokens at ~194 tok/s and generated 6, so the lane was entirely prefill; all thoughts were reading (a 95,996-token worker, a 22,987 manager and 19,022-token Coin) and Coin's weight 1000 preempts ordinary agents. In a generation window the switch log showed a peer gaining +1024 read tokens per cycle while the generator gained +64, and the dashboard's ~10-second Generation EMA could ramp toward ~50 while the peer was between lane uses. A generating agent's rate also varies with content: speculative acceptance was ~38% in one sample and dipped below 30% on reflective prose.

Two logical lanes made live throughput worse: the generator's bounded step is batched with the peer's prefill, acceptance fell to ~14% and decode to ~1 tok/s. Serving three owners on two server slots also produced snapshot and cold switches (evictions and rereads); giving slots >= owners removed them. Restarting with a fresh KV namespace discards prefill progress and forces cold reads again. Large displayed prompt counts do not establish cold reads.

New tool output can require substantial reading. A recovery Operator's prompt grew from 26,796 to 55,831 tokens after broad directory/task inspection returned 51,187 and 20,970 characters; restoring 27,351 was genuine reuse. Query named tasks/branches instead of enumerating unrelated directories. Native assistant/tool whitespace normalization can also invalidate a tail; the rendering owner retains the reproduction, installed exact-history repair and its validation limits.

Checkpointed/resident reads share the local priority-weighted lottery after their slice expires. Coin takes precedence at completed backend steps; other peers retain unsaved-read protection. Completing an opening read earns a generation slice, while short tool follow-ups earn no extra slice. No accumulated service account participates in allocation. A wholly protected 113,938-token read previously occupied the lane for over 15 minutes; Coin must bypass that protection. The scheduler and preemption owners govern current policy/evidence.

Zero completed thoughts does not prove an idle run: inspect active prompt/read/generated counters and charged work before diagnosing deadlock. Sustained latency, transfer costs and useful-throughput acceptance remain open.
