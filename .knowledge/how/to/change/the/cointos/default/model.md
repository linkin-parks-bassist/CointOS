---
status: green
revised_at: "2026-10-25T22:48:38+11:00"
---

The Machine panel's Default model chooser uses GET /api/models to discover on-disk GGUFs from model_directories and configured recipe directories. dashboard.model_discovery_seconds owns its refresh interval (fifteen seconds). Draft/vision companions and partial downloads are excluded; unqualified architectures, split GGUFs and inaccessible locations have disabled explanations. New qwen35 files use a Gufo recipe, checked SHA256 and no speculative draft until explicitly qualified. Memory admission derives weight size and overhead from the configured recipe.

POST /api/default-model accepts one discovered path. models.py owns checking → draining → loading → ready, with restoring/failed on errors. It closes new chat admission while current replies finish, persists desired identity before native mutation, unloads the old default unless explicitly required, checks headroom and verifies native launch before active routing changes. It shares the replacement lease against installation. Failed loads attempt native cleanup and restoration of the previous configuration/engine; errors remain visible. Restart retires unused configured engines and reconciles the persisted selection. Upgrades retain the selected default and discovered recipes; source definitions override matching recipes.

Ordinary requests resolve to work_model. OpenCode config, command and session spec use cointos/default; old concrete names retained by surviving clients also follow it. Sessions, tasks, spend and artifacts remain. Optional coin.model expresses a separate explicit requirement; ordinary Coin omits it. required_model requests can only name already-required engines. New spawning and silent-agent enforcement defer during replacement; loading time is not an agent stall.

The feature is installed. Native acceptance switched from the original DFlash recipe to an independently launched autoregressive recipe using a temporary hardlink of known weights, then back. Tasks, queue and the pre-existing pause state matched; only the temporary fixture was retired. Source tests cover reply draining, running-agent state preservation, persisted desired identity, failed-load restoration, failed persistence, unused-engine exclusion and upgrade retention. Evidence: ~/.local/state/cointos/default-model-acceptance/replacement.json. Visual browser acceptance was unavailable.

For user GPU work, use opencode --model cointos/default with the configured host provider. how/to/run/a/user/opencode/session/alongside/cointos.md owns measured priority/cache behavior and latency limits. The abliterated Qwen is now selected with a draft-free discovered recipe; its host download owner retains publisher-verification scope.
