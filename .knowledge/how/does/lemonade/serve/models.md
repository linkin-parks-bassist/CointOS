---
status: green
revised_at: "2026-10-19T06:11:03+11:00"
---

Lemonade is the machine-level model service (`lemond.service`, user `lemonade`) shared with other clients. Control: `http://127.0.0.1:13305`; logs: `journalctl -u lemond`. CointOS must tolerate another client changing the backend URL. MiniCPM was explicitly unloaded at the user's request. Coin and construction now select the separate Gufo Qwen process owned by what/is/the/gufo/backend/candidate/for/cointos.md.

`GET /api/v1/health` reports loaded state, backend URL, effective launch command, recipe options, PID and pin. CointOS refreshes this map during model checks. `POST /v1/load` accepts model name, context size, llama.cpp arguments, merge/save flags and pin. CointOS uses `merge_args: false`, `save_options: false`: operational config determines shape without rewriting saved recipes. Unload addresses one model; absence may return 404. Config removal does not unload pinned models.

Installed Lemonade rejects `--spec-draft-model`, `--model-draft` and their short aliases in custom arguments because it manages model paths. A custom-path rejection precedes native loading and says nothing about runtime compatibility or speed. Use registered `checkpoints.main`/`checkpoints.draft`: installed `lemonade pull --checkpoint TYPE CHECKPOINT` exposes this route. `/v1/pull` accepted `user.CointOS-DFlash2-Trial` with production main and DFlash2 Q4_K_M draft. Logs confirm `draft-dflash`, width 4 and matching weights. `/api/v1/downloads` tracks pulls. `subscribe: false` returns JSON job state despite `stream: true`; response completion does not establish download completion. Health reports its name as `CointOS-DFlash2-Trial`, omitting the `user.` namespace; normalize that prefix when matching registry names, and verify checkpoint/options. Adoption remains unverified. [Registration contract](https://lemonade-server.ai/docs/api/lemonade/) documents the draft checkpoint.

Lemonade runs in `inference.slice`: high/max memory 72/80 GiB, swap cap 2 GiB and 20% oomd pressure protection. `ManagedOOMSwap=auto` disables host-swap-triggered inference kills; root also uses `auto`. A persistent systemctl drop-in overrides `kill`; live `oomctl` confirms pressure-only monitoring without service restart. Rollback: `sudo systemctl set-property inference.slice ManagedOOMSwap=kill`. Old swap occupancy alone is not current pressure. Snapshots use configured `/dev/shm`, writable by `lemonade`; admission checks host/slice headroom.

Operational configuration defines complete load arguments with merge_args:false and save_options:false. Model identity/shape changes require paused full installation; removing configuration never unloads pinned models. Model facts own current selection.

Focused details: how/to/select/the/cointos/llama/server/build.md; how/does/the/cointos/llama/backend/preserve/generation/state.md; how/does/cointos/render/native/model/replies.md; what/is/the/cointos/model/sampling/policy.md. Model reasoning/stage policy is owned by what/is/the/cointos/construction/pipeline.md; low/medium/xhigh caps remain 256/384/1,024 and are not loosened for trials. XML Boolean arguments follow declared types case-insensitively.

The model-backend benchmark owner routes experimental measurements. Native fixtures and declared loaded shapes do not establish sustained quality.
