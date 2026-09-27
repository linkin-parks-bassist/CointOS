---
status: green
revised_at: "2026-09-27T17:03:42+10:00"
---

CointOS is David's autonomous, local-first agent ecosystem. This repository on rebuild/simple-core is its source. The standalone scripts/install copies the runtime to ~/.CointOS; cointosd.service and cointos-coin.service run there, and ~/.local/bin/cointos points to its bin/cointos. The installed runtime owns a separate globally readable knowledge tree explaining CointOS and publishing daemon-owned queues.

Python implementation is in cointos/, configuration in config/cointos.json, prompts in roles/, dashboard in web/, unit templates in systemd/, installer in scripts/ and tests in tests/. Managed projects are independent repositories under ~/Projects with their own orientation, spec, plan and broken leaves; worktrees live under ~/Projects/.worktrees/<project>/<task>. Todo's existing skeletons, product brief and manager frontier now belong to ~/Projects/todo-cli, the only configured autonomous project. The sandbox retains unrelated utilities. CointOS is paused, with the Todo continuation command queued for a future authorized resume. Full live acceptance remains open; OpenCode stays at 1.18.32 and V2 migration is deferred.

Read what/is/cointos.md for purpose, how/to/keep/cointos/simple.md for governing rules, what/is/the/architecture/of/cointos.md for design, and what/is/the/shape/of/cointos/work.md plus what/are/the/cointos/roles.md for bounded work and ownership. what/is/the/spec.md owns requirements; what/is/the/plan.md contains remaining steps; what/is/broken.md lists current defects. how/to/install/cointos.md explains installation.

what/ owns purpose, architecture, lifecycle, roles and model facts. how/ owns development, installation, Lemonade, Telegram and OpenCode procedures, including how/to/launch/opencode/for/a/cointos/agent.md. where/ owns orientation and where/are/reusable/cointos/parts.md. why/, does/ and is/ are empty.

The dead pre-rebuild install and 20 agent-* units are archived under ~/.local/share and removed; its kt grant was revoked before the new runtime tree was registered. Lemonade is shared with other clients. ~/Avnet and professional data must never reach a hosted model other than work-provided GitHub Copilot; hosted assistants working on CointOS never read it.
