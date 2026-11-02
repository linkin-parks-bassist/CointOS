---
status: green
revised_at: "2026-11-02T16:38:56+11:00"
---

Coin is visible in four places, all fed by the daemon's single `coin` ledger record:

- **Dashboard card:** appears only while Coin is active. Its title is the turn's trigger (`Answering a message`, `Issuing a reminder`, `Following up on requested work`, `Explaining a work update`, `Checking a service`, etc.), with the live phase, model, tokens/rate, worker uptime, turns and last words. Like every agent card, its words scroll; scrolling up holds the view behind Return to live. `dashboard.live_chars` (600) bounds how much reasoning and reply text there is to scroll. It disappears when Coin is idle or offline; the panel remains.
- **Coin panel:** the side column always shows status, model, turns, worker uptime, this turn's trigger, current/last turn timing, tokens/rate, GPU time, PID, last words and the last eight activity entries. `Open viewer` enables viewer windows; while active, Coin occupies a normal viewer slot.
- **Viewer:** Coin occupies an existing `cointos view` slot while active, using the same window mechanism as agents. It cannot use `opencode attach` directly because Coin is a separate Python service, not an OpenCode session; the slot uses the Rich terminal monitor in cointos/coin_view.py. how/can/an/opencode/viewer/show/coin.md owns the selected mirrored replacement. `cointos view --coin` or enabling viewers (`view --all`/the dashboard switch) makes a slot available. `cointos coin` (also `cointos watch coin`) opens the same log standalone.
- **Status:** `cointos status` has one `coin` line with the trigger, live phase, current tool, turns, current-turn elapsed and last-turn age; idle shows `idle` and the last trigger.

The Rich monitor renders a rounded status header, Markdown replies, a separate thinking panel, current tool and timestamped activity. It retains four observed turns, shows the last two, caps each text field at 16,000 characters and follows the newest lines. It takes no input beyond Ctrl+C, so it lacks scrollback, tool arguments/results and message entry. Reconnect preserves the latest state and reply. It uses an alternate screen and restores it on exit; slot reassignment exits the monitor. Client modules refresh without restarting agents or inference.

Phase comes from a live thought first (reading/reasoning/writing), then a current tool only when no thought is running, then `working` while busy and `idle` otherwise. A retained tool name is not presented as current while the model is reasoning or writing. The title is the actual turn trigger.

The daemon derives this from Coin's busy/tool/trigger reports: `turns` increments on each turn start; `turn_started_at`, `last_turn_at` and `last_turn_seconds` describe the current and last turn; `worker_since` and `alive` track the reporting PID; `trigger`/`last_trigger` name what started the turn; `recent` keeps bounded turn-start, tool and turn-end events; `model` is the configured Coin/work model. No Telegram text, chat identities or credentials are copied into the ledger; live words are the same in-memory model output already held for the card. `/api/ledger` and `/api/live` expose the record.
