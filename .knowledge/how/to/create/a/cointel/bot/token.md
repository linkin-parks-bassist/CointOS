---
status: green
revised_at: "2026-11-15T21:33:10+11:00"
---

Telegram bots are created by talking to **@BotFather** in Telegram; there is no developer-account or web step.

1. Open @BotFather (verified tick), press Start, send `/newbot`.
2. Give a display name, free text, for example "Cointel Professional".
3. Give a username, unique across Telegram and ending in `bot`, for example `cointel_professional_bot`. A taken name is refused and another is tried.
4. BotFather replies with the HTTP API token, `<digits>:<string>`; that line is the credential.
5. Repeat for the other instances, then send `/start` to each new bot from David's own account, because a bot cannot open a conversation and cannot message anyone until that chat exists.

Retrieve a lost token with `/mybots` -> the bot -> **API Token**; revoke a leaked one with the same menu's **Revoke current token**, then update the instance's env file. Optional per bot: `/setdescription`, `/setuserpic`, and `/setjoingroups` -> Disable for direct-message-only bots. `/setprivacy` only matters for group membership.

Where the token is stored, and the permitted-user list that must accompany it, are owned by where/are/the/cointel/bot/credentials.md.
