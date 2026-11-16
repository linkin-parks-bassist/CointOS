---
status: green
revised_at: "2026-11-07T16:03:04+11:00"
---

The user removed automatic elapsed-time budget stops. recovery.enforce terminates on generated-token exhaustion only; Supervisors have no token cap. Existing generation_seconds budget fields remain compatibility metadata, not enforced time limits. The dashboard no longer offers a minutes limit or displays it as an active allowance. New tool schemas omit time-budget overrides. Time telemetry is still recorded.

Tasks should finish or hand off within 30 GPU minutes. This is a supervisory expectation, not a hard timeout: the Supervisor judges useful advancement and intervenes when needed. A check occurs at each configured 5,000-output-token boundary or recovery.supervise_every_gpu_seconds (1,800 charged GPU seconds), coalescing while a check is pending. The no-recursive-supervision rule remains. The supervision owner governs decisions and the existing implementer-only 40k split.

GPU time is elapsed physical worker service including prefill, generation, switching and adapter overhead; lane waits/tools do not count. Current-run GPU seconds and generated tokens are available in task inspection and Supervisor launches. A completed receipt records last-run usage before settlement, preserving completed-task immutability. Llama generation_seconds is completion-call wall time rather than pure decode; separate decode_seconds drives native-speed telemetry. Do not confuse the two counters.

Token defaults remain 2,000,000 for ordinary work and 30,000 for First Responders; Supervisors are uncapped. warning_fraction sends a token-only warning once. Source/installed policy must be distinguished until compatible deployment. Initial prompts omit budget notices. Optional per-reply reasoning caps and the existing per-reply output maximum are separate; the live original-steer retry has reasoning.budgets={}.

The budget control retains waiting/undispatched token settings and explicit monotonic live increases, preserving usage, grants, sessions and work. Legacy numeric time arguments do not reintroduce an enforced time stop. Workers, managers, integrators, Operators and Supervisors retain zero automatic fresh token-budget retries; unchanged failures cannot refill themselves. Authorised interruptions preserve sessions, and unreceipted death still reaches First Responder recovery.

Tests cover token exhaustion, no time-triggered termination, 30-GPU-minute supervision without stopping work, accurate usage, receipt immutability and checked recovery. They do not establish model judgment or useful autonomous throughput.
