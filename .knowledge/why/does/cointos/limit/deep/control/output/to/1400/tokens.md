---
status: "unverified"
created_at: "2026-09-16T04:48:55+10:00"
scope: "local"
source: "ecosystem/control_agent.py and configured output policies inspected 2026-09-16"
updated_at: "2026-09-16T17:23:12+10:00"
---

`ecosystem/control_agent.respond` currently passes `max_tokens=1400` to injected inference and `managed_request`, while the live-capacity policy used for general workers reserves 32000 output tokens. The source contains no comment, measurement, or protocol constraint explaining 1400. A truncated control response can prevent a complete tool call and consume another loop iteration; after removal of the six-round loop cap it no longer creates that specific terminal failure, but it still needlessly starves a priority control session.

The output allowance should come from one canonical policy value rather than another literal in the call site. The current canonical configured allowance is `config/opencode-capacity.json` field `output_reserve_tokens`, also reflected in the resource policy's dynamic-model context reserves. The implementation should load and strictly validate the configured positive non-boolean integer, pass it to injected inference and managed inference, and include it in the explicit `inference_request` payload. This may route a large-context control turn away from the small control model when its actual prompt plus output allowance does not fit; that is preferable to silent truncation or false admission.

The separate 180-second backend request timeout remains unresolved. It needs retry/cleanup semantics rather than simple deletion because it also bounds an unresponsive HTTP/backend call.

A direct implementation attempt to substitute the canonical 32000 allowance was reverted after focused qualification exposed a deeper routing barrier. `control_agent.respond` first resolves the active chat model to Qwen3.5 and calls `managed_request` with that exact model. In the managed-inference fixture, a 32000-token request could not fit the selected small model, so acquisition remained in its wait loop rather than selecting available larger capacity. The owned test process was interrupted after preserving its stack; no backend mutation or source failure was inferred. Restoring 1400 made all 27 existing optional-role/managed-inference checks pass while the unrelated six-round removal remained intact.

Blocker: deep control output cannot safely be raised until control acquisition selects a model from fresh routes using the actual prompt plus requested output allowance, or explicitly reroutes an exact-model capacity wait to a fitting model. Simply raising the literal converts output starvation into indefinite false unavailability. Next check: trace the control-agent/managed-inference model-selection seam and add fitting-model reroute before replacing 1400. The 180-second request timeout remains separate.

Resolution 2026-09-16: the 1400-token limit and small-model deep binding are removed. The fast first-contact lane deliberately remains Qwen3.5 for low prefill latency; the separate deep/action service now selects Qwen3.8 and requests the canonical 32000-token output allowance. Focused control and managed-inference checks pass. The 180-second backend timeout remains an unresolved recovery/backoff concern rather than an output-cap justification.


Timeout resolution 2026-09-16: Cointelprofessional deep/action inference now explicitly uses no elapsed backend deadline. The admitted client carries `timeout: null` to `urllib.request.urlopen(timeout=None)`, and managed inference omits its elapsed-time cancellation branch only for that explicit value. Ordinary managed-inference callers retain the 180-second compatibility default. Explicit caller cancellation and higher-priority preemption still invoke proxy cancellation, whose socket shutdown path has already been qualified. Sixteen managed-inference and eleven optional-role checks pass; the one stale fast-output expectation was updated from the retired 96-token value to 512. Installed assets contain the change; live long-turn behavior remains observable rather than preemptively timed out.
