---
status: "unverified"
created_at: "2026-09-14T23:54:24+10:00"
scope: "local"
source: "rendered installed services/systemd files and current systemctl --user state 2026-09-14"
---

After explicit deployment authority and fresh state checks, deploy application payload with scripts/install-cointos, then back up matching ~/.config/systemd/user unit files and copy rendered ~/.CointOS/services/systemd units there. Run systemctl --user daemon-reload and verify loaded ExecStart/WorkingDirectory resolve ~/.CointOS. This installs definitions without enabling or starting them. Preserve existing drop-ins and unrelated units. agent-models.service is a oneshot residency operation that loads pinned Qwen3.5-4B with two sequences; starting dependent Telegram/control/notifier units can pull it in. Installation alone does not qualify or activate live inference.
