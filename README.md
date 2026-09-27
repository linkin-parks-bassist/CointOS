# CointOS

David's autonomous local-agent ecosystem. The daemon owns scheduling; agents work
in independent project repositories and share pre-emptive GPU lanes.

Run `scripts/install` from this repository to copy the runtime into `~/.CointOS/`
and configure its systemd user services. Pause first with `cointos stop` and wait
until `cointos agents` reports none. Installation leaves services stopped; start
with `cointos up`. Autonomous work remains paused until `cointos go`.

The source knowledge tree explains development. The installed runtime has its own
globally readable tree explaining runtime operation and daemon-owned task and command
queues. Each project owns its orientation, spec, plan and broken leaves. Submit work
through `cointos queue PROJECT NAME "BRIEF" --kind queued|urgent|command`.

Use `kt where am i` for orientation and `python3 -m unittest discover` for checks.
