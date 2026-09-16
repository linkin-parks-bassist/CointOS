---
status: "unverified"
created_at: "2026-09-15T21:58:24+10:00"
scope: "project local"
source: "git show/blame commit 2e4377b; current uncommitted operator_inference.py; retained OpenCode session finish events 2026-09-15"
---

The 4096-token general-worker ceiling had no recorded workload rationale. Commit `2e4377b` introduced `config/opencode-capacity.json` on 2026-09-12 while adding pre-launch capacity validation; it supplied `output_reserve_tokens: 4096` as a bare constant. The accompanying tests proved that a configured bound was enforced but did not test whether the bound was large enough for sustained tool-using agent work. Newer uncommitted `ecosystem/operator_inference.py` copied 4096 into managed worker requests.

A live supervised Qwen worker on 2026-09-15 ended its stream at exactly 4096 output tokens with semantic finish reason `length`, only 32652 total conversation tokens inside a 131072-token backend context. It had not edited its owned source. The observable wrapper ignored length and accepted process exit zero, exposing sudden agent death syndrome rather than total-context exhaustion.

General worker policy is now at least 32000 output tokens whenever verified client/backend bounds support it. CointOS must allocate a fitting backend and configure/read back matching OpenCode limits instead of shrinking the worker. The observable wrapper classifies a stream ending in `finish=length` as incomplete, continues the exact retained session automatically, rechecks backend/harness capacity before each recovery generation, and emits a nonzero emergency outcome after repeated uncompleted truncations. An earlier length followed by a later stop in the same client stream is already-recovered work and does not cause a redundant continuation.

The broader prevention owner is `global:what/is/the/agent/continuity/policy.md`; exact CointOS capacity agreement is `what/is/intended/live_capacity_contract.md`. Intake stays paused until the installed 32000 allowance and retained-session recovery are live-qualified.
