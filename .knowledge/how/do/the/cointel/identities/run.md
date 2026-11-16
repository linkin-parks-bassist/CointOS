---
status: green
revised_at: "2026-11-16T18:24:51+11:00"
---

One `cointosd` on port 4200 serves three Coin processes. `COINTEL=<profile>` selects `config/coins/<profile>.json` through `cointos/coins.py`; profiles own name, identity, station and Telegram env-file path. Without a profile, Coin retains the historical `state/coin` archive.

Units are `cointel-<profile>-coin.service` from one installed root with identity-specific WorkingDirectory and PYTHONPATH pointing to that root. `cointos up` and `halt` control these services. The historical `cointos-coin.service` remains disabled because Professional uses its bot token and duplicate polling conflicts. The removed three-installation deployment must not return.

Archives and wake registries live in `state/coin-<identity>/`; each service polls only its own wakes. Professional inherited both legacy schedules: the paused runtime-review wake and weekday 18:00 Australia/Sydney wake. The legacy state/coin copy is inactive; Amateur has no migrated wake registry. Monday's weekday occurrence was acknowledged and its cursor advanced to Tuesday; this does not prove the requested work happened. Professional inherited the historical conversation. Each request carries its assistant identity; the gateway builds `<identity>/<user digest>` as its conversation owner. Knowledge roots follow station policy without new grants. The single scheduler admits independent owners without a Coin serialization lock.

The prefill loop came from lifecycle cleanup: snapshots.coin_conversation recognized only the daemon's old Coin prefix, and retire_residents released unrecognized owners even during active thoughts. The deployed correction recognizes every configured profile plus historical Coin, and protects all active thoughts independently of task/prefix recognition. Do not trim prompts or change the GPU runner to address this incident.

Assisted qualification on 2026-11-16: the original runner completed an 11,056-token system-first synthetic user request in 24.46 seconds; a new diagnostic Coin owner timed out after 50 seconds with repeated resident retirements and debugger evidence of prefill restarting at zero. After the four-module deployment and daemon restart, three concurrent synthetic system-first requests completed under the actual profile identities in 23.33, 25.74 and 28.96 seconds. 193 focused checks passed. One daemon and all three Coin services are active; the same model runner survived. This is mechanism evidence, not sustained autonomous acceptance or Telegram reply qualification. Evidence: ~/.local/state/cointos/identity-repair-20261116/verification.json.

The user accepts correctly stationed bots with separate identities and conversations. Filesystem sandboxing is not required or planned; ordinary filesystem/Bash reach remains available. The dashboard Coin status slot remains shared and generic durable intake is unfinished. Never read personal content into hosted debugging context.
