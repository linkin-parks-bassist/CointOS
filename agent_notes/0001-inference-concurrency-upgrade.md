# HIGH PRIORITY: Upgrade inference concurrency mechanisms

**Signed by:** Wren
**Date:** 2026-09-03
**Job ID:** task-33da82f3c75e4b8b

## Current State

### Control Plane
- **Model:** Qwen3.8-27B-GGUF (pinned)
- **Context window:** 131072 tokens
- **Resident slots:** 1 (single slot occupied)
- **Role:** All agent ecosystem control-plane decisions

### Worker Jobs
- **Model:** Qwen3.5-4B-GGUF (local, via Lemonade 11.9.0 on port 13305)
- **Status:** Failing with HTTP 400 due to slot contention
- **Context window:** 32768 tokens (proposed raise toward 64k-128k)

### Interim Mitigations
Worker jobs currently routed to resident models with open slots when tasks are not wildly inappropriate. This is a stopgap measure that cannot scale.

## Tradeoffs: Lemonade vs Multi-Model Server

### Lemonade (Current)
**Advantages:**
- Zero external dependency
- Full control over model selection
- Local inference on loopback only
- Simpler operational model

**Disadvantages:**
- Single-resident-slot bottleneck
- No true time-sharing or context switching
- Cannot support concurrent worker jobs
- Limited context window on Qwen3.5-4B-GGUF (32k)

### Multi-Model Server (e.g., LM Studio / Ollama)
**Advantages:**
- Native multi-resident-slot architecture
- Built-in time-sharing and context switching
- Hot-swapping capability
- Better context window support on Qwen3.8-27B (131k)

**Disadvantages:**
- External dependency introduction
- Slightly increased operational complexity
- Need to manage server lifecycle

## Recommendation

**Adopt multi-model server architecture** for the following reasons:

1. **Scale requirement:** Worker jobs are failing due to slot contention; single-resident-slot model cannot handle concurrent workloads.

2. **Context window:** Qwen3.8-27B supports 131k tokens; current 32k limit on Qwen3.5-4B-GGUF is insufficient for complex reasoning tasks.

3. **Concurrent workloads:** Future agent ecosystem will require multiple resident models supporting time-sharing, context switching, and hot-swapping.

4. **Operational tradeoff:** The increased complexity of an external server is justified by the inability of Lemonade to scale inference capacity.

## Desired End State

Sophisticated concurrency model with:
- Multiple resident models (Qwen3.8-27B + Qwen3.5-4B-GGUF)
- Time-sharing and context switching
- Hot-swapping capability
- Resource-aware model selection with explicit overrides
- Recorded rationale for each job's model assignment
- Immutable inventory snapshot at enqueue time

## Pending Actions

1. [ ] Evaluate and select specific multi-model server implementation
2. [ ] Configure multiple resident slots for inference concurrency
3. [ ] Implement resource-aware model selection logic
4. [ ] Update executor to support hot-swapping and time-sharing
5. [ ] Test concurrent worker job dispatch
6. [ ] Document migration path from current Lemonade-only setup

## Evidence

- Worker job HTTP 400 errors on 2026-09-03 confirm slot contention
- Qwen3.8-27B-quantized supports 131072 context window (verified in model metadata)
- Current context window cap of 32768 on Qwen3.5-4B-GGUF is demonstrably insufficient
- Lemonade reports `GLM-4.7-Flash-GGUF` ready but cannot support multiple concurrent workers

---

*This note is HIGH PRIORITY for future agents. See ecosystem_lore.md for provenance boundaries and AGENTS.md for workspace instructions.*
