---
status: "unverified"
created_at: "2026-09-14T22:59:39+10:00"
scope: "local"
source: "David instruction to copy and globally expose KT; kt register/access help; root access contract"
updated_at: "2026-09-14T23:04:15+10:00"
---

Copy the project `.knowledge` tree into the CointOS installation and register its canonical installed root with standalone KT under the name `cointos`. Installing CointOS automatically grants lookup from every project, including noninteractive agent installs. David explicitly authorized this blanket package policy on 2026-09-14. The grant covers the installed CointOS root only; other roots and standalone KT ownership are unchanged.

`scripts/install-cointos` calls `kt register cointos PREFIX/.knowledge`, then `kt access PREFIX/.knowledge allow --scope all`. Current KT requires a terminal for the confirmation; the installer supplies its authorized package approval through a bounded pseudo-terminal invocation of the public CLI. It does not edit registry internals or enable general permission bypass. Approval failure makes installation report failure rather than quietly leave knowledge unavailable. `--no-register` remains an explicit copying-only option for isolated deployment tests.

The installed project tree is the runtime knowledge owner; source `.knowledge` is development/install input. Preserve installed new/edited leaves, update unchanged shipped leaves and reject simultaneous divergent edits before application replacement. Do not create `.dist` conflicts inside the semantic tree. Copying does not provide bidirectional synchronization.

Existing root-wide access and an outside-project `cointos:` lookup were verified. Noninteractive registration/approval behavior is checked with real standalone KT and an isolated registry before deploying this change.
