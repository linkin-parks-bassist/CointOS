---
status: green
revised_at: "2026-11-02T17:00:09+11:00"
---

`cointos/coin_mirror.py` shows Coin in OpenCode's own viewer through a mirrored session, because Coin is a Python service with no OpenCode session. It is installed and passes against real OpenCode 1.18.35 windows with fixture journal entries; it has not yet shown a live Coin turn. Running viewer processes keep their imported code, so a window opened before installation still uses the Rich monitor until reopened.

Coin appends each turn's user messages, reasoning, words, tool inputs and tool outputs to the private `state/coin/turns.jsonl`, bounded by `coin.journal_bytes`. `cli.coin_log` starts a loopback `opencode serve` with isolated XDG directories and a password, attaches the same OpenCode window agents get, fills in the last 60 journal entries and follows new ones. If it cannot start, the Rich monitor in cointos/coin_view.py is the fallback. The server and its directory last only while the window is open; the journal owns history. Only the server is isolated: the window must keep the user's XDG state, because `thinking_mode` and tool-detail settings live in `~/.local/state/opencode/kv.json` and an isolated window hides reasoning.

Why this shape, tested against 1.18.35:

- `POST /session/{id}/prompt_async` against a stand-in OpenAI-compatible provider creates a real assistant message that an attached window shows live.
- `PATCH /session/{id}/message/{mid}/part/{pid}` then adds reasoning, words and tool parts, and the window shows them live.
- `POST /sync/replay` stores messages but publishes no live events, so an attached window misses them. Mirroring does not use it.

The stand-in receives OpenCode's tool definitions and must never emit a tool call. Tool activity is display-only.

Limits: the window is view-only. Typed text gets a reply saying to message Coin on Telegram, because Coin's intake is bound to Telegram update IDs and replies go to Telegram. Words still being generated come from the daemon's `live` record, capped by `dashboard.live_chars`, until the finished message replaces them. With four fixture entries, history was absent at 14 seconds and present at 30 seconds, so backfill can lag a short Coin turn; the cause is unmeasured. A viewer slot still ends when Coin goes idle, so `cointos coin` is the window that stays open between turns.

Measured resident memory is about 368 MB for the server and 322 MB for the window.

Evidence: tests/test_coin_mirror.py and a pty-driven run covering backfill, live reasoning, words, tool parts, typed text and cleanup.
