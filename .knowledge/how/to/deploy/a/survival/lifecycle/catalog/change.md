---
status: green
revised_at: "2026-09-26T00:20:18+10:00"
---

The root-owned survival plane is not installed on this host as of the 2026-09-26 read-only check: its systemd unit files, `/usr/local/lib/cointelprofessional-survival` release, and `/var/lib/cointelprofessional` state are absent. Therefore the user-session dynamic executor-lane deployment does not have an existing privileged survival process to cut over. Do not install a new privileged plane merely as an incidental step in adopting user executor units.

If the root survival plane is explicitly installed later, `scripts/install-survival-plane` stages the `survival/` modules and `config/survival-lifecycle.json`, verifies root units, then atomically switches its release symlink. Without `--enable` it does not activate root units. The catalog and `survival/system_control.py` now include the fixed `agent-executors.target` lifecycle boundary, so a future root installation must use this source generation or later before dynamic lanes coexist with it. Root installation/activation needs its own preflight, authority, and postconditions; the global `how/to/obtain/sudo-authorization.md` explains the interactive askpass mechanism for already-authorized commands but grants no authority by itself.
