---
status: green
revised_at: "2026-10-14T23:34:40+11:00"
---

Service weights are unreadable to this user; public copies support experiments. `lemonade config set llamacpp.vulkan_bin=PATH` persists a selector and attempts reload. Current [official configuration](https://lemonade-server.ai/docs/guide/configuration/) describes directories; installed 11.9.0 executes the path itself, requiring the full executable path. CLI success does not prove reload: verify health and launch arguments. Record and restore the prior selector.

The service has `ProtectHome=yes`, `PrivateTmp=yes`: home and host `/tmp` builds cannot be deployment paths. Selected `/opt/cointos-llama-stop-010be9683/explicit-continuation/llama-server` uses packaged compute libraries plus rebuilt server/common components; its wrapper enables `LLAMA_MTP_SLOT_STATE`. The bundle manifest pins every file. The cumulative `patches/llama-b10723-mtp-state.patch` applies after the speculative-stop patch. Native installed stop/restore/tool checks pass (`/tmp/cointos-mtp-install-evidence.json`); live acceptance remains workload-specific. Rollback of rendering requires restoring the prior adapter and selecting preserved `mtp-state/llama-server` together while paused; reload the original recipe/pin and verify health. The parent bundle remains the target-only rollback. Comparative evidence belongs to the benchmark owner.
