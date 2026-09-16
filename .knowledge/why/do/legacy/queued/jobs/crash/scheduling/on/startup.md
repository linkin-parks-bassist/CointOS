---
status: "unverified"
created_at: "2026-09-14T23:56:23+10:00"
scope: "local"
source: "ecosystem/scheduler.py priority; activation journal; runtime job metadata"
---

scheduler.priority passed missing or null authority_profile as an empty string to effective_priority, which rejects it. Two runtime agent-task jobs created 2026-09-04 retain null profiles and crashed the ecosystem executor on 2026-09-14 activation. Missing legacy authority must resolve to ordinary scheduling priority, never Coin/survivor authority. Explicit supplied profiles retain current validation; worker admission remains authoritative. Historical ready local records without kind are not modern agent-task dispatch candidates. Preserve these records rather than deleting old work.
