---
verified_at: '2026-09-12T09:42:22+10:00'
verified_by: opencode /home/david
scope: project local
source: pre-99318d9 Git history; ecosystem/opencode_capacity.py; ecosystem/opencode_client.py; config/opencode-capabilities.json; ecosystem/models.py observe_opencode_backend_capacity; ecosystem/inference_proxy.py opencode_environment; ecosystem/executor.py launch_runner_round capacity preflight; ecosystem/inference_capacity.py validate_launch_capacity; config/opencode-capacity.json
verification: Distilled the accepted contract and implementation seams; the pure record, version-qualified capability, observation adapter, ephemeral config encoder, and pre-spawn managed-launch validation are implemented and test-verified (focused suites pass; full suite 747 tests shows the same 19 pre-existing failures as the tree without the new files), no activation claimed.
review_when: Recheck after each accepted live-capacity implementation stage.
---

Every OpenCode launch should derive one effective capacity record from fresh backend
per-request allocation, qualified model limits, and the installed client's exact
version capabilities. Total pool size, training maximum, static catalogues, and
saved user configuration are not runtime capacity truth. Contradictory, stale, or
unknown inputs fail closed. OpenCode compaction and CointOS continuation must use
the same effective denominator; `finish: length` is incomplete even after HTTP 200
and process exit zero.

The pure record seam is implemented in `ecosystem/opencode_capacity.py`
(`effective_inference_capacity`, `launch_fingerprint`); effective output is the
smallest of the qualified client ceiling, any observed backend output ceiling, and
the policy reserve, and the effective context is the observed per-sequence cap
verbatim. The version-qualified capability seam is implemented in
`ecosystem/opencode_client.py` against `config/opencode-capabilities.json`
(1.18.30 -> 32000); an unknown version has no default and closes launch. The
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
record. The next independently verified stage is wrapper integration and
activation.
Do not begin by editing user OpenCode configuration, replacing the executable
symlink, restarting services, or changing live model allocation.
Wrapper integration and activation are later independently verified stages.
