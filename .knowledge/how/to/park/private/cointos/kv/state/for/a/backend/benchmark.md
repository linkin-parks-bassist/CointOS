---
status: green
revised_at: "2026-11-16T22:04:26+11:00"
---

Private KV must remain in tmpfs. Preserve its RAM files through a benchmark when headroom permits, or let normal optional-cache eviction cause a later prompt reread. Never copy private-owned KV to an SSD qualification directory. Detect ownership by owner.startswith('private/'), not an optional private Boolean field.

The unmodified patches/gufo/qualify.py Run.park offloads every memory-tier snapshot and physical slot to disk, so it is unsuitable when private states may be present. Use a private-aware wrapper or defer the trial. Retain private RAM files, park only ordinary snapshots on SSD, and avoid a physical-slot disk backup if private ownership is possible. A live private client can replay from its retained RAM prefix or reread; do not claim exact physical/RNG continuation for a skipped slot. Abort rather than silently weakening an active agent's continuation contract.

The Halogen host trial's PrivateAwareRun is an external wrapper, not a change to the generic helper. It normally retains private RAM snapshots, discards its private/ambiguous physical-slot save within tmpfs, and refuses this path with active agents. Its explicit --release-private-cache mode evicts only optional private-owned RAM caches after draining and stopping the daemon, then removes their ledger metadata so clients reread from authoritative histories. No private bytes are parked on SSD. Synthetic checks establish that private cache bytes never reach the wrapper's SSD backup while ordinary backups retain byte equality. Loaded-model trials and actual private gateway recovery passed; global:how/to/run/halogen/flash-next/on/halomit.md owns evidence. Recovery accepts a changed localhost port only after verifying every other launch argument and recipe field. The general backend benchmark owner governs leases, drain, identity/authority preservation, restoration and inference verification.
