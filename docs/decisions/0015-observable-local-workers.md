# 0015 — Native live view for local workers

David requested attachable, nicely formatted OpenCode output by default, and a
standing repository instruction. Astra records the approved direction, 2026-09-07.

Use one ephemeral loopback server and attached CLI inside the admitted worker
process group. A separate TUI observes that exact session; it does not own the
worker's lifetime. Keep JSONL evidence, local-only inference, gated credentials,
and existing conservative close checks. No permanent server or mid-run restart.
R4-PRECISE remains required; a UI endpoint is not backend-release evidence.

The implementation and operational boundaries are in
[local-worker-view](../operations/local-worker-view.md). Real no-inference server,
TUI-disconnect and supervisor cleanup probes precede the first admitted live run.
