---
status: green
revised_at: "2026-09-25T17:11:55+10:00"
---

After explicit deployment authority and fresh state checks, deploy application payload with scripts/install-cointos, then back up matching ~/.config/systemd/user unit files and copy rendered ~/.CointOS/services/systemd units there. Never copy the source templates directly: an unrendered watchdog template once made reconciliation operate on empty checkout state while installed work remained blocked. Run systemctl --user daemon-reload and verify every affected loaded ExecStart/WorkingDirectory resolves ~/.CointOS. This installs definitions without enabling or starting them. Preserve existing drop-ins and unrelated units. agent-models.service is a oneshot residency operation that loads pinned Qwen3.5-4B with two sequences; starting dependent Telegram/control/notifier units can pull it in. Installation alone does not qualify or activate live inference.
