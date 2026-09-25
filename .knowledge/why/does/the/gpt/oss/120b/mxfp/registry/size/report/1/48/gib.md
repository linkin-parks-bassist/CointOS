---
status: green
revised_at: "2026-09-20T09:14:55+10:00"
checked_at: '2026-09-16T03:24:00+10:00'
---

Lemonade 11.9.0's live `lemonade list` and `/api/v1/models` endpoint on its reported port 13305 currently report `gpt-oss-120b-mxfp-GGUF` as downloaded with size 1.48 GiB. CointOS normalizes that live value to 1,589,137,900 bytes and can therefore admit the nominal 120B route.

The package-owned registry `/usr/share/lemonade-server/resources/server_models.json` defines the same model ID with checkpoint `ggml-org/gpt-oss-120b-GGUF:*` and size **63.4 GiB**. The distinct `gpt-oss-120b-GGUF` CLI entry reports 12.20 GiB. Therefore the 1.48 GiB live value is a shadowed or derived runtime value and is not trustworthy physical-capacity evidence. Do not live-load this entry or treat its admitted route as proof until the expanded artifact is identified.

The first API probe incorrectly assumed port 8000; `lemonade status` is the authoritative discovery used here and reported port 13305. Two search probes were also badly scoped: a broad configuration search crossed into a minified OpenCode dependency and emitted roughly 2.5 million tokens before truncation, while `head` on `/usr/bin/lemonade` dumped bytes because the launcher is a stripped ELF executable. Future probes must exclude dependency trees, check file type before textual reads, and use strict output bounds. The installed package is `lemonade-server`; its manifest identifies the package registry above and the system service as `lemond.service`.

Blocker: The Lemonade service user's state and model cache are not readable by the current account, so the expanded checkpoint and actual downloaded artifact have not been inspected.
Next check: Inspect the service-owned runtime model record and expanded files through a bounded Lemonade API/CLI operation or authorized service-user read; determine why the wildcard checkpoint shadows the installed 63.4 GiB size with 1.48 GiB.
