---
status: green
revised_at: "2026-10-19T23:41:53+11:00"
checked_at: "2026-10-19T23:24:08+11:00"
expires_every: "7d"
---

The temporary native checkout used for CointOS inspection/builds is `/tmp/cointos-gufo-assessment-20261018`, with upstream HEAD `1f97092333af10f29887b098d9cb8a041610004a` (checked with git rev-parse). It contains the build tree and modified native integration; temporary files are not the canonical CointOS source.

CointOS owns `patches/gufo/` and `scripts/build-gufo-control`. Reproducible inputs are that integration plus the pinned upstream revision. The selected installed package is `~/.local/share/cointos/gufo/1f970923-native-dflash-v9-header-20261019`; its `build.json` binds the deployed binary/libraries/source hashes. A matching temporary checkout HEAD alone does not prove byte identity with the installed binary. The Gufo backend owner holds runtime identity and qualification.
