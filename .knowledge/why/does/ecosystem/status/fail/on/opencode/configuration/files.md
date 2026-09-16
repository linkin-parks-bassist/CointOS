---
status: "unverified"
created_at: "2026-09-14T23:55:58+10:00"
scope: "local"
source: "ecosystem/cli.py status; actual runtime sidecar key inspection and KeyError"
---

cli.status scans state/jobs/*.json and assumes each has a state field, but historical task-*.opencode.json files in that directory contain OpenCode provider configuration without job state. This makes installed status raise KeyError before reporting jobs. Exclude .opencode.json sidecars from job enumeration rather than deleting historical configuration or inventing job state. Fresh installed status reproduced the failure 2026-09-14. Check other job enumerators for the same assumption before activation.
