---
status: "unverified"
review_when: "Recheck after any Qwen3.8 recipe-option update or model reload."
updated_at: "2026-09-16T00:38:35+10:00"
source: "fresh Lemonade health recipe_options and effective launch_command after controlled merge_args=false reload 2026-09-16"
---

Lemonade's saved registry metadata for `Qwen3.8-27B-GGUF` contained `--reasoning-budget 2048`, first observed in the system journal on 2026-09-09 alongside manually changed context and parallel settings. No CointOS source or Git history contains this argument, and no rationale or benchmark was found. The actor that originally persisted it remains unknown.

The stale option was removed during the controlled batch-setting reload on 2026-09-16. Qwen3.8 was unloaded and reloaded with `merge_args: false`, pinned at 131072 context, one parallel sequence, 512/128 batch settings, poll 0, priority -1 and MTP draft speculation. Fresh Lemonade health showed both saved `recipe_options.llamacpp_args` and the effective live `launch_command`; neither contained `--reasoning-budget`. Qwen3.5 remained pinned and untouched.

Current invariant: Qwen3.8 saved and effective launch options must omit an arbitrary reasoning-token cap. Recheck both representations after reload because saved metadata can otherwise resurrect an option absent from the previous live process.
