# Resource survival, model routing, and context continuity

**Maintainer:** Codex agent `/root`; evidence contributors: Popper
(`/root/gpu_controls`), Sartre (`/root/lemonade_runtime`), and Peirce
(`/root/memory_controls`). The 2026-09-04 resource reconciliation was consolidated
by Codex agent `/root/plan1_task5_docs`.

## Incident evidence

The pre-2026-09-04 design was unsafe. A 51.8 GiB FP16 vLLM model was admitted with
only 11.5 GiB Linux memory available while Radeon GTT was already 80.5/100 GiB.
The previous boot recorded 58 kernel OOM kills and 257 amdgpu command-submission
allocation failures. GNOME and chatbot processes were killed while Lemonade lived
because inference had no GPU allocation boundary and unfavorable protection was
applied to the user session rather than inference.

Systemd `MemoryMax=` is necessary containment for host allocations but is not a
complete bound for Vulkan GTT on this APU. The effective hard GPU-side boundary is
the TTM page limit.

Later on 2026-09-04, an independent control failure caused a contact restart storm.
A single non-OOM pressure sample entered emergency; preparation then crossed an
underscore-rejecting role validator and could not create `sole_survivor`. The
durable latch remained restrictive. The old guard also equated liveness with exact
model status `ready`, so a loaded/backend-alive busy model looked absent. Its
one-second retry restarted Telegram, control, and notifier repeatedly until systemd
rate-limited Telegram. All contemporaneous unit tests passed because the resource
tests mocked the transition above the role, model-health, persistence, and systemd
postcondition boundaries. This was a composition-test failure, not evidence that
the stated priority of Cointelprofessional was adequate enforcement.

## Current invariant

- TTM allocations are bounded to 64 GiB (`ttm.pages_limit=16777216`); the page pool
  is 8 GiB. A reboot is still required to prove these parameters load from initramfs,
  although the values are live now.
- Lemonade runs in `inference.slice` with low CPU/I/O priority, high OOM victim
  preference, `MemoryHigh=72G`, `MemoryMax=80G`, and `MemorySwapMax=2G`.
- Desktop/control services receive protection. `systemd-oomd` watches inference
  pressure rather than treating the UI as the first disposal target.
- Only `Qwen3.5-4B-GGUF` is pinned. It exists to keep chatbot, routing, and emergency
  control responsive. At most one larger work model is loaded, always unpinned.
- The small model chooses `use_loaded`, `load`, or `defer`, the target model, and a
  generous context size from prevalidated choices. Caller choices are hints.
- Deterministic validation owns existence, role compatibility, model count, memory,
  GTT, and context limits. A malformed or unsafe model answer becomes `defer`.
- A compatible loaded large model should absorb smaller new work rather than causing
  another load. This is an inference upgrade, not a semantic downgrade.
- Resource emergency is a durable, fail-closed phase transition. Roles are optional
  advisory context and do not grant admission or survivor authority. Loaded,
  backend-alive busy or in-use models are live even when unavailable for admission.
- Non-OOM pressure is confirmed over monotonic durations from `config/time.cfg`.
  Every external phase advances only after its process/model postcondition is
  observed; recovery stays restrictive until all required restarts are verified.

Qwen3.5 4B was selected for the resident routing kernel by measurement: constrained
JSON returned in about 0.7 seconds. DeepSeek-Qwen3 8B repeatedly spent 6–20 seconds
in hidden reasoning and exhausted 256–768 output tokens before emitting JSON.

## Preemption and context continuity

OpenCode runs are process-group preemptible. Priorities are Sole Survivor, Telegram,
local CLI/default work, verification, then watchdog stewardship. Higher priority
work interrupts lower priority work; equal priority work rotates after five minutes.
The exact prompt, JSONL transcript, and OpenCode `ses_…` identifier survive, allowing
same-session resume.

Each job gets a model-chosen context allocation. The current conservative KV estimate
is 128 KiB/token and allocations are checked against live GTT and a 55 GiB normal
target. At 75% of the selected window, the executor interrupts the main turn, asks
the same session to write a semantic handoff, archives that context's log, then starts
a fresh session using the original prompt, handoff, and current filesystem. If the
semantic handoff is absent, a clearly marked mechanical artifact preserves recovery
pointers; it must never be mistaken for a verified summary.

## OOM transition

The one-second guard treats any increment of `/proc/vmstat` `oom_kill` as an
emergency regardless of current utilization. Non-OOM pressure must remain beyond
its configured confirmation window. The guard records an incident manifest,
checkpoints durable sessions/prompts/logs/jobs/control turns, stops model clients,
unloads every model, reloads only Qwen3.5 4B, and prepares exactly one concrete
`sole_survivor` job. Its persisted sequence is `recorded`, `clients_stopped`,
`models_unloaded`, `model_loaded`, `survivor_ready`, then `active`; retries resume
the last verified phase. Ordinary dispatch stays mechanically latched until that
exact job invokes `scripts/resource-control recover` and the live health gate
succeeds. A crashed Survivor or failed restart postcondition does not reopen
dispatch.

Lemonade does not expose serialization of backend KV caches. Never claim otherwise:
the durable recovery boundary is the OpenCode session database, exact prompts,
structured job/control records, logs, handoff artifacts, tool/file state, and model
snapshot.

## Verification state

Earlier on 2026-09-04 the Python suite passed 54 tests, including unsafe routing
rejection, process-level priority preemption with session preservation, 75% context
rollover, abandoned-run recovery, exclusive Survivor admission, and single-OOM
emergency entry. That evidence did not cover the later restart-storm composition.
A live routed verifier loaded Qwen3-Coder-30B unpinned with a model-selected
131,072-token window; observed GTT was about 35.6 GiB, available memory about 79 GiB,
swap zero, memory PSI zero, and the OOM counter remained zero.

After the phase/postcondition repair, one foreground reconciliation converted the
legacy latch into incident `20260904T033110Z-0`, restored the pinned Qwen3.5 4B, and
prepared survivor `task-e01f5d8c44f8421d`. Six samples over 25 seconds showed stable
resource-guard, Telegram, control-worker, and notifier process identities with zero
restarts; the dirty-checkout suite passed 113/113. The configured Lemonade endpoint
is loopback port 13305, not the obsolete port 8000 used in an initial incident probe.

That stability sample did not complete the semantic gate. The survivor policy
requested 32,768 tokens, while Lemonade's `--ctx-size 32768 --parallel 2` exposed an
effective 16,384 tokens per request; its first full incident read attempted 25,523
tokens and failed. The guard then emitted the same failed-survivor error every second.
It was stopped again while Telegram retained its process identity.

The repair subsequently made JSON identity exact by type as well as value, verified
the realized backend allocation, and added a durable canonical replacement
transition. Live retry preserved the old failed record hashes, observed total
`ctx_size=65536` with parallel two, and created `task-a02f3a746e5a0914` as the sole
admitted running owner. Its first context rollover succeeded: a 3,956-byte semantic
handoff was written and a fresh session began. The new session then reread the full
incident, issued a 33,891-token request against 32,768 effective tokens, and failed.
One foreground tick preserved a single deduplicated `emergency_escalation` with
reason `context_overflow` for that replacement. Telegram/notifier PIDs 272721 and
272720 remained unchanged with zero restarts; the guard remains stopped and disabled
at the user-service boot boundary.

This closes the unsafe retry-loop boundary but not automated repair. Plan 4 owns the
required escalation from a context-overflow finding to a larger safely supportable
model and context. Do not reactivate the guard merely to replay the same contained
failure, and do not mistake a successful handoff for successful completion.

This is evidence for the repaired current user-level resource transition only. The
root-installed permanent gateway, guardian, survival spools, and command lifecycle
remain undeployed until Plan 5 and must not be inferred from active user units or
this successful sample window.
