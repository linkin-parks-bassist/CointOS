---
scope: project local
source: "David exact harness/backend agreement and prevention-first SADS clarification 2026-09-15; current capacity implementation"
review_when: Recheck after each accepted live-capacity implementation stage.
status: "unverified"
updated_at: "2026-09-15T22:09:32+10:00"
---

The host-level abundance and reserve policy is `what/is/the/local/strix/halo/resource/policy.md`; apply it before choosing worker ceilings.

Every OpenCode launch must derive one effective capacity record from fresh backend
per-request allocation, qualified model limits, and the installed client's exact
version capabilities. Total pool size, training maximum, static catalogues, and
saved user configuration are not runtime capacity truth. CointOS must configure the agent harness from that exact record and read it back before inference; context, input, and output values must agree exactly with the allocated backend and admitted lease. On disagreement, automatically replace the harness values from live truth and recheck. If facts or resources are temporarily unavailable, retain and queue the request while repairing them; do not deny it. There are no exceptions to agreement and no terminal mismatch gate. A launch must not invent limits from contradictory or stale inputs.
David allocation clarification: preserve benign demand and automatically refresh,
repair or qualify the missing facts; holding that launch is not terminal denial.
Internal paperwork must not obstruct available resources. Queue or suspend by
trusted priority as defined in `what/is/intended/agent_scheduling.md`. OpenCode compaction must use the observed effective context; CointOS context
handoffs and fresh-session continuation are deferred pending future review; `finish: length` is incomplete even after HTTP 200
and process exit zero.

The pure record seam is implemented in `ecosystem/opencode_capacity.py`
(`effective_inference_capacity`, `launch_fingerprint`); effective output is the largest useful allowance bounded by the qualified client ceiling, any observed backend output ceiling, the per-request context, and policy. General workers receive at least 32000 output tokens whenever those verified bounds support it, and the effective context is the observed per-sequence cap
verbatim. The version-qualified capability seam is implemented in
`ecosystem/opencode_client.py` against `config/opencode-capabilities.json`
(1.18.30 -> 32000); an unknown version adds no package-version barrier and remains bounded by fresh backend capacity and policy. The
fresh backend-capacity observation adapter is implemented in `ecosystem/models.py`
(`observe_opencode_backend_capacity`), a pure incarnation-bound projection of one
verified resident observation (reusing `_observed_model_record` and
`context_layout.observed_context_layout`) into the constructor's record: the
per-request context, aggregate pool, and mode come verbatim from the layout, the
backend reports no output ceiling, the prompt estimate is zero until the launcher
supplies it, and contradictions return explicit absence (None). The one ephemeral
OpenCode configuration encoder is implemented in `ecosystem/inference_proxy.py`
(`opencode_environment`): it consumes the validated effective record, strips every
model's static `limit` from the base catalogue so capacity claims cannot escape,
and writes only the selected model's `opencode_context_tokens` /
`opencode_output_tokens`; the base catalogue `config/executor-opencode.json` now
carries names and non-capacity options only, and independent lease values are
rejected. The final pre-spawn validation seam is implemented in
`ecosystem/executor.py` `launch_runner_round`: a `capacity_preflight` phase runs
before `r1_acquire_intent` and, through three mockable producers
(`observe_capacity`, `qualify_capability`, `capacity_policy`, each with a
fail-closed default), derives the one effective record for the routed model and
checks the admitted lease against it via
`ecosystem/inference_capacity.py` `validate_launch_capacity` (lease model,
context, and output must fit the live record); the checked-in policy lives in
`config/opencode-capacity.json` (output reserve, rollover fraction, freshness
window). Any stale observation, changed incarnation, model mismatch, lease context
above the live cap, or lease output above the qualified ceiling raises, the job is
returned to `ready` with a `runner_deferred_reasons` entry, and no child process or
inference request is started; `opencode_environment` then consumes the validated
record. Observable wrapper source integration is now implemented and tested; adoption/activation remains separate.
Do not begin by editing user OpenCode configuration, replacing the executable
symlink, restarting services, or changing live model allocation.
Installed-wrapper adoption and activation remain separate operational stages.

David amendment 2026-09-14: OpenCode owns compaction within retained sessions. Legacy capacity-record rollover metadata is informational and no longer rejects prompts crossing its threshold. See `why/are/cointos/context/handoffs/deferred.md`.

Implemented launch clarification: `constrain_launch_capacity` retains measured backend caps/incarnation while setting OpenCode limits to the admitted context and output; input is context minus output. The shared encoder selects the same qualified model for main/small/compaction and enables normal auto-compaction. The observable supervisor reads `/config` and `/provider` before inference, then reobserves the backend with the same binary/root. See `how/does/cointos/verify/opencode/resolved/limits/before/inference.md`. This startup gate must be repeated after backend reincarnation, model switching, lease reacquisition, or any capacity change before the next generation. Prevention is primary; retained-session recovery is the mandatory backstop for residual failures.
