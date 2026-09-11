# OpenCode Live Capacity Contract Design

**Status:** approved architecture, documentation only, 2026-09-10

**Decision owner:** David

**Document maintainer:** Codex agent `/root`

## Purpose

Every OpenCode inference request must use limits derived from the backend allocation
which will actually serve it. This applies equally to a managed CointOS worker and
to David typing plain `opencode`. A stale catalogue, model training maximum, total
KV pool, or desired launch setting must never be presented to OpenCode as the live
per-request capacity.

Launch fails explicitly before inference when the effective capacity cannot be
proved. A backend `length` stop is incomplete work, never successful completion.

This document specifies the mechanism but does not authorize its implementation or
activation.

## Incident evidence

Two incidents exposed the same missing contract at different boundaries.

On 2026-09-09, Qwen3.8 was once loaded with `--ctx-size 131072 --parallel 4`.
The effective fixed context was approximately 32768 tokens per sequence, while the
client expected 131072. Requests exceeded the real sequence context before OpenCode
could compact them.

Later that day, a prior Codex session changed
`/home/david/.config/opencode/opencode.json` to advertise Qwen3.8 limits of 131072
context and 43690 output tokens. David then invoked only `opencode`; the command
resolved through `/home/david/.local/bin/opencode`, which was a direct symlink to
the raw binary. The interactive process therefore loaded the per-user JSON without
CointOS admission or live-capacity validation.

Quill's final request started at 23:05:44 AEST and ended at 00:05:57. Lemonade
reported 3227 prompt tokens, 32000 generated tokens, HTTP 200, and no truncation at
the llama.cpp transport. OpenCode 1.18.30 recorded `finish: "length"`, total context
95444, and exited its agent loop. The machine did not reboot and the kernel recorded
no OOM termination. Quill stopped mid-sentence because the installed client path
enforced a 32000-token output ceiling below the advertised 43690, then treated the
length stop as a terminal turn.

The managed catalogue separately advertises 32768 output tokens for Qwen3.8. Prior
commissioning notes had already established 32000 as the installed OpenCode ceiling.
Thus the user catalogue, managed catalogue, client adapter, and live backend did not
share one authoritative capacity record.

## Capacity is a validated record

The authoritative runtime representation is one `effective_inference_capacity`
plain-data record constructed immediately before launch. It contains:

- model and backend-incarnation identity;
- observation identity, time, and evidence reference;
- context allocation mode: fixed or shared;
- backend context pool, parallel sequence count, and per-request context cap;
- installed OpenCode version and its qualified maximum output cap;
- selected output reserve and context rollover threshold; and
- the exact context and output limits to emit into OpenCode configuration.

The record distinguishes four facts which must not be collapsed:

1. The model's trained maximum is a capability ceiling.
2. The backend launch and slot observations describe the live allocation.
3. The installed OpenCode adapter has its own qualified request/output ceiling.
4. Output reserve and rollover fraction are policy within those observed ceilings.

`effective_context_tokens` is the observed per-request context cap, never the total
fixed pool divided a second time and never an unqualified registry maximum. In
shared mode, aggregate occupancy remains a separate admission concern; the record
still carries the observed per-request cap.

`effective_output_tokens` is the smallest of the qualified OpenCode ceiling, any
observed backend output ceiling, and the selected policy reserve. It must be positive
and strictly smaller than `effective_context_tokens`. Absence of a required fact is
not a default.

## Observation and validation boundary

Existing backend observation and `ecosystem/context_layout.py` remain the owners of
literal Lemonade health, launch arguments, llama.cpp slot metadata, and fixed/shared
layout interpretation. A new pure capacity function consumes their meaningful
record plus a version-qualified OpenCode capability record. It does not scrape
process text or query HTTP itself.

The installed OpenCode ceiling is not guessed from a context ratio. It is qualified
once per OpenCode version using a focused probe or an authoritative client fact and
stored with that exact version identity. An unknown or changed version invalidates
the qualification and closes launch until requalified.

Validation rejects, at minimum:

- absent, stale, contradictory, or differently incarnated backend observations;
- unknown context mode or ambiguous slot allocation;
- selected model differing from the observed backend model;
- configured limits larger than effective limits;
- an unqualified OpenCode version;
- non-positive output reserve or insufficient room for rollover; and
- a request whose prompt plus reserved output cannot fit the effective context.

Errors name the disagreeing facts and their evidence. The mechanism never silently
shrinks a pre-existing session and continues as though its prior turns were valid.

## One launch fingertip

Both interactive and managed launches consume the same capacity constructor and
the same ephemeral OpenCode-config encoder.

For managed workers, the admitted inference lease continues to own model, context,
and output reservation. Before spawning OpenCode, the launcher validates that lease
against a fresh effective-capacity record. The anonymous memfd config contains only
the validated effective limits.

For interactive use, the first `opencode` on `PATH` becomes a small CointOS launcher,
not a copied static configuration. It observes the selected live backend, constructs
the same effective record, writes an anonymous per-process OpenCode config, and then
executes `/home/david/.opencode/bin/opencode` with the user's original arguments.
The wrapper must avoid resolving itself recursively. Interactive admission policy
may remain distinct from managed worker admission, but capacity truth may not.

`/home/david/.config/opencode/opencode.json` may retain presentation, plugins, MCP,
and model names. Its capacity fields are non-authoritative and must either be
removed from the launch input or overwritten only in the ephemeral derived config.
No persistent generated capacity catalogue becomes a second source of truth.

## Compaction and terminal outcomes

OpenCode receives the exact effective context and output limits, so its built-in
compaction operates before the serving backend's boundary. CointOS's explicit 75%
continuation state machine remains a separate durable worker guarantee; it uses the
same effective context denominator and must not disagree with OpenCode.

Every completed response is classified from its semantic finish reason:

- `stop` or a valid tool-call boundary may advance normal execution;
- `length` means incomplete output and cannot complete a worker, release a task as
  successful, or leave an interactive autonomous run silently idle;
- context-overrun and capacity disagreement are explicit failed/pre-continuation
  outcomes with retained evidence; and
- transport success and process exit zero are not semantic success.

Automatic continuation after `length` is not assumed safe. The initial mechanism
must preserve the session and report the incomplete boundary visibly. A later,
separately approved policy may request continuation when the remaining context and
cumulative budgets make that valid.

## Failure behavior and evidence

A preflight failure performs no inference and prints one actionable diagnostic with
the selected model, effective live allocation, OpenCode qualification, and failed
invariant. It returns nonzero.

A runtime capacity change invalidates new launches. Existing requests retain the
incarnation-bound contract under which they were admitted; CointOS does not rewrite
their meaning underneath them. If the backend changes incompatibly, the outcome is
an observed backend failure and recovery boundary, not a guessed new allowance.

Each launch records a sanitized capacity attestation sufficient to reproduce the
decision without recording credentials or prompt contents. Managed runtime JSONL
remains append-only. Interactive diagnostics may be ephemeral unless a separately
approved operator-session policy owns their persistence.

## Testing and acceptance

Pure tests cover fixed and shared layouts, minimum-limit derivation, version binding,
staleness, model/incarnation disagreement, prompt-plus-output fit, and exact failure
messages. Adapter tests prove both launch paths emit identical capacity fields from
the same record and cannot fall back to persistent JSON limits.

Integration tests use fake loopback endpoints and a fake OpenCode executable. They
prove plain `opencode` argument/exit/signal propagation, non-recursive resolution,
no inference on failed preflight, and preservation of unrelated user configuration.

A bounded live acceptance probe is required before activation. It must observe the
loaded backend, display the derived contract, run a deliberately short response,
and confirm the request payload and recorded usage agree. It must not consume a
32000-token response merely to prove a ceiling. Activation then verifies both a
plain interactive launch and a managed worker launch.

Success means no OpenCode launch can advertise capacity larger than the backend and
installed client combination actually serving it, compaction uses that same truth,
and a length stop is always visible as incomplete.
