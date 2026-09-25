---
status: green
revised_at: "2026-09-26T02:34:41+10:00"
---

`systemctl --user show` reports `ActiveState=inactive` but omits `MainPID` and `ControlGroup` for stopped `.path`, `.timer` and `.target` units. The old `resource_control._user_unit_state()` required all three service-process fields for every unit. The emergency stop command succeeded for each managed unit, but its postcondition was marked `unit state could not be verified`, leaving incident `20260925T162248Z-0` in phase `recorded` with a draining work gate. This occurred after an unintended Qwen3-Coder load crossed the critical GTT/resource threshold while two disposable CointOS-only review jobs were being routed; both jobs were terminally cancelled with no runner.

The installed repair requires `ActiveState` for non-process units, accepts absent process fields as empty/zero, and still requires exact `ActiveState`, `ControlGroup` and `MainPID` for `.service` units. Live read-only probes of the three stopped unit types and 56 existing resource-control tests passed. The guard then advanced through verified managed-client shutdown, unloaded all models, and loaded the configured emergency model. Subsequent routing and drain-admission fixes let the recorded Sole Survivor run; emergency mode remains in effect until an authorized, verified recovery. Do not resume ordinary work merely because the two review jobs were cancelled. Recheck this contract whenever managed stop membership adds a new systemd unit type.
