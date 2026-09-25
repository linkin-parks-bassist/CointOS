---
status: green
revised_at: "2026-09-25T22:20:33+10:00"
---

At a drained whole-system boundary, run source `scripts/install-cointos --preserve-installed-knowledge --no-register`, then start the complete installed generation with `/home/david/.CointOS/scripts/cointos-system start`. The explicit preserve mode atomically installs the application payload while copying the installed `.knowledge` tree through unchanged and retaining the previous manifest’s shipped-knowledge hashes, so it does not disguise runtime edits as newly shipped source. It refuses a missing installed tree. Use the default installer when source/runtime knowledge is reconciled; do not use preserve mode as a substitute for authorized reconciliation.
