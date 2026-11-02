---
status: green
revised_at: "2026-10-31T16:56:19+11:00"
checked_at: "2026-10-31T16:02:35+11:00"
expires_every: "7d"
---

The current build checkout is `~/.cache/cointos-speed/gufo-current-20261031`, at upstream `192b75a8b6079b498461b598b8514ecd05d71caf`, fetched from origin/main. CointOS owns `patches/gufo/` and `scripts/build-gufo-control`: the pinned revision, native-control.patch, control sources and qwen_runner.inc are reproducible build inputs. The separate wave64 patch is obsolete because this engine includes it upstream. The compatibility runner retains the persistent control interface while upstream HTTP serving uses component-cache slots.

Production selects `~/.local/share/cointos/gufo/192b75a-native-v13-20261031`, qualified with native CPU/GPU tests, exact long-context replay, resident switching and persistence continuation. The earlier `gufo-qwen-kernels-20261031` checkout and V12 package are historical evidence, not a drop-in downgrade: V12 cannot import newly written DFlash payloads. Private checkouts are not canonical CointOS source. `build.json` records the actual upstream revision, binary, libraries and build-time source hashes; native info reports upstream_revision separately from the stable snapshot compatibility identity. Checkout HEAD alone cannot prove installed byte identity. The backend and benchmark owners retain qualification and runtime identity.
