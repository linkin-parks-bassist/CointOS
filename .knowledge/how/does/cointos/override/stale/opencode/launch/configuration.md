---
status: green
revised_at: "2026-09-14T22:40:40+10:00"
---

prepare_environment copies the environment, reads an inherited OPENCODE_CONFIG JSON document if present, then recursively merges OPENCODE_CONFIG_CONTENT; incoming dicts merge while non-dicts replace. It subsequently overwrites capacity-related fields from fresh observations, preserving unrelated inherited settings such as permissions and credentials. Invalid/malformed config fails launch; JSONC inherited custom files are not currently parsed by this Python boundary.

A new anonymous memfd stores the full merged config. A separate secret-free inline overlay repeats authoritative size and compaction settings so lower-precedence size claims cannot win. OPENCODE_DISABLE_PROJECT_CONFIG is set for the launched server. Final resolved read-back, not assumptions about --pure or precedence, decides whether the launch is safe.

Ordinary launches target the configured loopback Lemonade gateway. An inherited admitted-proxy baseURL retains that transport and its secret, while its smaller allowances are revalidated against live facts. The wrapper grants neither inference admission nor tool authority. Explicit hosted-provider commands bypass this local backend qualification; an inference launch without an explicit model is rejected, except explicitly provider-disabled inert tests.

The supervisor owns the new fd, passes it to the server through pass_fds, removes config variables from the attached client, and closes the fd after cleanup. The parent's inherited fd remains parent-owned. Private config bytes and credentials are not logged. Owners: ecosystem/opencode_launch.py prepare_environment/_merge; scripts/opencode_observable.py start_server/main.
