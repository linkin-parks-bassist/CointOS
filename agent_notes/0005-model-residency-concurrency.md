# HIGH PRIORITY: Model Residency Concurrency Upgrade

**Author**: Wren

## Problem
Single-slot model residency causes 400 failures when a job is routed to a non-resident model. We have seen this repeatedly (Merrill, Kaelen, Elias, Elara, Jules all failed on Coder-30B routing).

## Interim Fix
Routing rule now sends workers to resident models instead of failing. This is working but is a band-aid.

## End State
David wants upgrade to concurrency mechanisms:

- Multi-model residency with time-sharing, context switching, and hot-swapping
- Either modify Lemonade to support this, or replace it with a server that has sophisticated time-share / context-switching / hot-swapping architecture
- The 128 GB physical RAM is split by firmware: ~64 GB to GPU, ~62 GB to Linux. So Linux-visible memory is the real ceiling for model residency
- Current slots: 2. Control plane (Qwen3.8-27B, 17.2 GB) is pinned. Qwen3.5-4B (3.3 GB) was the second resident but David has said to drop it - it was not performing well
- With the 4B dropped, there is room to load Coder-30B (17.3 GB) alongside the control plane: 17.2 + 17.3 = 34.5 GB, well within the ~54 GB available
- Consider raising resident_llm_slots from 2 to 3 so the scheduler can keep control plane + Coder + a small utility model simultaneously

## New Agent Roles
David wants two new agent roles created:

1. **Innovator**: an ideas role. Reads the system, proposes concrete structural improvements (context windows, model routing, agent handoffs, reducing redundant work). Does NOT implement. Proposes only.

2. **Speculator**: a pure thinking role. Goes around and thinks. Leaves thoughts. No restrictions on what it thinks about. No implementation, no proposals - just observations and musings.