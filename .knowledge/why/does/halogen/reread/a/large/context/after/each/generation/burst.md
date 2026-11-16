---
status: green
revised_at: "2026-11-17T07:35:18+11:00"
---

The experimental adapter's strict cache-loss guard treated a missing generation tail as loss of the entire prefix. Observed counters showed a 44,620-token prompt generating 64-token bursts, then `lost: engine retained 44620 of 44684 prefix tokens` and a switch restored from zero. The UI could remain at the original prompt's full read count while generated-tail recovery restarted reading. This is cache-state churn, not a collapse in raw decode speed.

Named KEEP states are limited to half the native KV pool. A 131072-position pool rejected long retained states once several contexts competed. Simply omitting KEEP avoids those pin refusals but a synthetic 40k/36k interleave still reread its 64-token generated tail, so automatic prompt caching alone does not establish complete tail retention.

The repair preserves/replays only a bounded missing tail up to scheduler.read_chunk_tokens, rather than declaring the whole context lost, and retains the completed generation tail with replaceable pins. Retire an old pin only after the next request has acquired its active region, then commit the replacement. The deployed 262144-position shared pool and 8192-token prefill workspace preserve the 131072-token per-request context and 24 GB reserve. Interleaved 40k/36k synthetic contexts returned to their retained tails with one pending input token per 64 generated tokens, at approximately 63, 74 and 92 tok/s. More than an hour of subsequent mixed live traffic showed no recorded lane-state-loss resets or refused-pin warnings. This checks the repaired burst loop, not unlimited simultaneous context capacity.

Occasional full reads remain. Compaction changes the incoming prefix; how/to/monitor/halogen/cache/stability/in/cointos.md owns its diagnosis. Even a small near-tail edit can fail to find an earlier reusable native state: numeric telemetry showed held 73381, next 74135, common 73240, then restored zero. Generation recovered around 73 tok/s without a lane-state-loss event. near-tail-divergence.json records this counterexample. Reusable-prefix fallback for such edits still needs investigation; do not describe all long reads as compaction or claim complete cache reuse.

Evidence is under ~/.local/state/halogen-trial/: cache-spawn-fix.log records the failed automatic-only alternative; cache-spawn-fix-v2.log and long-cache-retention-v2.json record the passing replacement check. stability-watch.jsonl holds numeric live evidence. Production probes use the CointOS gateway. Direct native lane tests require the daemon stopped and must restore it in finally. Actual session prompts must not be copied into diagnostic evidence.
