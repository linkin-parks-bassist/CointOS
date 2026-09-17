---
status: "unverified"
scope: project local
source: "scripts/cointos-system; telegram-999135394; live systemd restart/status 2026-09-17"
review_when: Recheck when user service membership, installation boundaries, or service dependencies change.
updated_at: "2026-09-17T16:25:12+10:00"
---

Operate the complete user-session CointOS generation through installed `/home/david/.CointOS/scripts/cointos-system` (or the source counterpart before installation): `start`, `stop`, `restart`, and `status` are the supported whole-system actions. Use this boundary after installing code/configuration changes that affect running services. Do not restart individual CointOS units during an ordinary upgrade because that can leave old Python processes interpreting new on-disk configuration.

The command owns resident models, inference proxy, resource guard, Telegram gateway, control worker, notifier, ecosystem path/timer, watchdog timer, and their triggered oneshots. Stop includes triggers and oneshots so they cannot reactivate a partial generation. Start reloads systemd and starts all long-running units plus triggers. Restart stops the whole set, reloads, then starts it. If any start fails, it stops the complete set rather than leaving a partially active system. `status` reports every expected long-running unit and trigger in one call.

This was required after installation moved physical reserve keys while a 24-hour-old control worker retained the previous module generation. One Telegram turn hot-retried `invalid inference capacity policy` more than 1,200 times. A whole-system restart loaded matching code/config, ended policy errors, and recovered the retained turn.

For one manual intake pass use installed `scripts/ecosystem run-once`; inspect queue counts with installed `scripts/ecosystem status`. Live state and append-only run evidence are under `~/.CointOS`, not the checkout. Credentials remain in protected environment files and never on command lines. Root-owned survival-plane services remain a separate authority boundary and are not controlled by this user-session command.