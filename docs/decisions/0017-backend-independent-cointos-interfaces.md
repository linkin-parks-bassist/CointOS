# 0017: CointOS owns its interfaces; model servers are adapters

Status: direction recorded from David, 2026-09-07, by Astra. Deferred until after
MVP unless David explicitly reprioritizes. Documentation only; no refactor or
backend activation authorized by this record.

Priority clarified by David, 2026-09-08: D9 is a top first-post-MVP improvement
alongside saved-state timesharing D10, after POC bringup. Initially support only
Lemonade/OpenCode through small centralized compatibility modules. Additional
implementations should fill in those bounded adapter details without spreading
vendor knowledge through core logic. A second production backend is not required
to finish this initial extraction. See decision 0019 for delivery order.

## Intent

CointOS is an orchestration system in its own right, not a Lemonade extension.
Its roles, spawning, scheduling, time-sharing, messaging and continuity should
depend on CointOS-native contracts rather than a particular inference server,
agent runner, machine layout or service manager.

David's illustrative `launch('Qwen3.8-27B-GGUF', 131, initial_prompt, socket)`
expresses the desired native interface, not an approved literal signature or
context unit. Use explicit token counts and plain request/result data. Keep
inference provisioning and agent-runner launch distinct where their lifetimes
differ. Configuration selects implementations of narrow functions; no classes,
universal plugin framework or generic interpreter is implied.

Lemonade currently supplies model-server control and OpenAI-compatible inference;
its inference backend performs actual allocation/execution. CointOS decides what
to admit and when to load, evict, dispatch or resume. Literal Lemonade HTTP/CLI,
OpenCode launch/attach commands, paths and service operations belong in the
appropriate backend, runner, UI or deployment adapter, not scattered core logic.

The architecture should also accommodate remotely hosted inference. Local memory,
model residency, slot observation and KV save/restore are backend capabilities,
not promises every provider can satisfy. Unsupported observations remain explicit;
do not invent physical capacity or weaken request ownership/release semantics.
Current inference remains local-only. Remote support does not authorize remote
requests, credentials, spending or disclosure of personal/professional data.

## Deferred execution and acceptance

Track as D9 in the MVP index. After MVP, Astra defines the small native contracts
and replacement boundaries; local GPU workers perform bounded, independent caller
migrations in isolated worktrees. This is suitable for substantial local offload,
not an expensive hosted-model rewrite or a blind global find-and-replace. Existing
admission/proxy seams should be reused where sound. Remove replaced core paths at
cutover instead of maintaining competing implementations indefinitely.

Acceptance: core roles/scheduling/messages are unchanged when a configured backend
or runner adapter is replaced; backend-specific commands and environment facts
reside at their owning adapters; lifecycle, cancellation, continuation, authority,
resource accounting and monitoring contracts remain truthful. Prove substitution
with a local test adapter first; exercising a real remote provider needs separate
approval. No current worker packet is expanded by this future item.
