---
status: green
revised_at: "2026-09-26T04:10:49+10:00"
---

The installed `workload-control.json` currently has 2,253 quiescent worker leases and no active ones in a 2.86 MB document. A read-only `jq` parse took about 0.02 seconds on this host; that does not measure atomic rewrite latency or prove retention is a present throughput bottleneck. `ecosystem/workload_control.py` reads the whole document under its lock and rewrites it on a dirty save.

Quiescent entries remain part of exact replay semantics: `acquire_worker` searches prior request IDs to return an idempotent result, and late `release_worker` or observation calls resolve the exact lease ID. Every non-quiescent state must also remain available to safety checks. Monotonic timestamps in old records are not a cross-boot age order, and the JSON writer sorts lease keys, so neither timestamp nor document order is a safe pruning rule. The existing records do not carry a boot identity with those timestamps, and there is no established maximum delay for legitimate replay.

Do not prune the live file by age or newest-tail count. First measure real write/lock cost and replay age from authorized, minimally scoped evidence. If retention is material, design an archive or index that preserves exact request-ID and lease-ID replay and crash consistency while keeping non-quiescent leases in the hot ledger. A new cross-boot ordering key could help future policy, but it cannot retroactively date ambiguous historical records.
