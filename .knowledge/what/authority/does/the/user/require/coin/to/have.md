---
status: green
revised_at: "2026-11-02T18:47:42+11:00"
---

User requirement: Coin is an extension of the user and has ultimate control over the computer. The user operates the workstation through Coin when away from it, so Coin exists to do the user's bidding, and a restricted tool set works against that. The user's words: "coin should have god-like powers"; "coin is an extension of me, he is to do my bidding, it is not in the interest of my bidding for coin to have a restricted set of tools."

That is about capability, not doing the work himself. The user's decision: Coin defers almost everything, because of priority and scheduling, and handles only super trivial things directly. He judges each request's size: plausibly large work goes to a manager, never to one Operator.

Current state:

- `dispatch` starts any role. It is one tool with one definition (`schema.DISPATCH_PROPERTIES`) shared by Coin and agents, and the daemon decides from the caller what each may start. Managers and workers need a registered project, and `project_new` creates one.
- Coin has every kt tool, including access requests, and `allow` on all 47 roots.
- Coin himself is not a dispatchable role. Only Coin, system daemons and the user via Telegram start his turns. His prompt lives at `roles/coin.md`.

Remaining limits: only Operators can be stationed in a directory, `mcp_call` refuses remote servers, and `sudo` needs a password.
