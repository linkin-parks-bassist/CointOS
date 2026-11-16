---
status: green
revised_at: "2026-11-16T16:12:55+11:00"
---

Check CointOS status and Lemonade health first. A healthy Lemonade daemon with no loaded model, guard rung 3/killed=true and an explicit unload in its journal indicates deliberate memory shedding; check memory.events separately before claiming a kernel OOM or server crash.

Recovery requires the configured calm interval and enough headroom for the work model's memory_gb estimate. Headroom is the tighter host reserve and server-cgroup allowance. Large host MemAvailable alone does not satisfy that test: orphan tmpfs KV files can remain charged to inference.slice after their producing process/cgroup disappears.

Inspect the configured snapshot root and any known retired cache namespace by metadata. Compare names against live ledger/reservation references and verify no process uses the retired files. Retire only verified untracked, unused disposable cache files; do not read their payloads or move unknown private KV onto disk. Never clear active snapshots or weaken memory controls merely to force a load.

The retired /dev/shm/cointos-mtp-q8-3 namespace held four untracked, unused files occupying 9,818,193,920 allocated bytes. Reclaiming them let the existing guard leave killed state and reload Flash automatically. The configured cache root remains /dev/shm/cointos-contexts. Cross-namespace orphan inventory is not automatic; migration cleanup remains in the plan.

Watch guard transitions, loading progress, actual inference and post-load headroom. Restore cointos up/go if repair stopped or paused services. Verify the shared server still has one 131,072-token slot and one CointOS lane. A successful reload alone does not establish stability under long-prompt/checkpoint load. The memory, snapshot-storage and server-build owners hold the governing contracts.
