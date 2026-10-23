---
status: green
revised_at: "2026-10-19T23:20:51+11:00"
---

The workstation's unified RAM is one pool. `memory.py` derives headroom from `MemAvailable`, configured workstation reserve and the inference-slice allowance. Admission estimates model, agent and snapshot cost; agent and landing units also have hard memory caps.

Snapshots give way first. Retired RAM files remain charged until actual deletion. Reclamation credits allocated bytes once, capped by fresh physical headroom less unpublished saves/unspills; guards can already have measured a release. Independent RAM/disk cleanup keeps filesystem disposal outside the state lock. Snapshot storage owns pins, reservations, retry and admission details; severe-pressure live resilience remains unproved.

Sustained PSI distress stops background agents uncharged. The model unloads only if headroom remains negative after shedding. Recovery waits for configured calm time. Swap use is diagnostic.
