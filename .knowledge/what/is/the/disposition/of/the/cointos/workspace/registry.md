---
status: green
revised_at: "2026-09-20T03:01:57+10:00"
---

David rejected the workspace registry as an unwanted feature. It has been removed from local worker brief generation, contact task default/selector resolution, authority-policy schema, and configuration. The default contact workspace in an installed deployment is the source checkout read from `.cointos-install.json` `source.root`, validated as an absolute existing directory; an explicit selector is a path. In an uninstalled source/test root, the default is `cli.ROOT`. This distinction matters because installed `cli.ROOT` is `/home/david/.CointOS`, not the source checkout.

The retained policy is `config/authority-profiles.json`, containing version 1 and the original seven authority profiles. `ecosystem/task_contracts.py` loads it with `accepted_authority_policy` and validates the profiles. Durable task contracts still carry explicit workspace and read/write scope; the rejected registry no longer supplies those values. The obsolete registry-only test file was removed; existing affected tests were adjusted. The installed loader returned the two expected top-level keys and all seven profiles, 100 focused tests passed after the filename rename, and six queried service/path members were active.

Historical state filenames such as `state/workspaces-policy.json` remain in test fixtures and may need separate migration if they are used by runtime code. The full installer still has an unrelated source/runtime knowledge conflict, so these code/config changes were deployed at drained whole-system boundaries without running the full installer. Check those migration concerns before claiming all historical workspace naming is gone.
