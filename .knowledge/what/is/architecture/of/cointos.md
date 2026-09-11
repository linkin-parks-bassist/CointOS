---
verified_at: '2026-09-11T18:43:14+10:00'
verified_by: codex /root
scope: project local
source: git show fe92546:docs/system-map.md; current source tree
verification: Reconciled the former system map with current module and service entry points; live state is explicitly excluded.
review_when: Recheck when component ownership or durable flow changes.
---

CointOS represents work as versioned filesystem records and append-only events.
Intake and contact produce durable turns or jobs; preparation combines the task,
role, policy, and bounded context; routing and resource owners choose an executable
model allocation; OpenCode performs tool work; independent evidence determines
acceptance; dependent outbox records carry results back to contact surfaces.

Keep domain policy separate from adapters. Telegram owns transport, Lemonade owns
model serving, OpenCode owns the tool-running client, systemd owns process
supervision, and filesystem modules own persistence. None of those adapters defines
agent identity, semantic completion, authority, or context capacity. Source/runtime
locations and concrete entry points are in `where/is/code/for/cointos.md`; establish
live state through `where/is/runtime_truth.md`.
