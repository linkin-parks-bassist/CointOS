---
status: green
revised_at: "2026-10-05T18:48:14+11:00"
---

Every task gets a personal name when it is created (`tasks.create` → `names.invent`), unique among all tasks and kept for the task's whole life, so a paused and resumed agent keeps its name while a new task gets a new one. Live tasks created before names existed are named when the daemon starts (`state.fresh`). Agent ids such as `worker-0b23e3` remain the internal run keys.

Names are generated, never chosen from a list of names (the user's requirement from the original ecosystem design): `cointos/names.py` assembles two or three syllables from weighted inventories of onsets, vowels and codas drawn from many languages' sound systems, with plain sounds common and exotic ones rare, no consonant pile-ups where syllables join, and a filter for unpronounceable clusters. Results range from familiar to alien, such as Gartan, Virta, Xorzak, Rakhi, Zozu or Zedritek; a few clunky ones are accepted.

The name appears in the agent's identity line (`prompts.identity`: "Your name is …"), in delivered messages (`<message from="NAME (TASK)">`), first in `cointos_peers`, in `cointos agents`, and on dashboard cards before the agent id. Only runs launched after the name exists see it in their own prompt.

Evidence: `tests/test_mcp.py` checks that tasks get distinct, well-formed names, that the identity line carries the name, that invented names avoid taken ones and rarely collide, and that messages carry the sender's name.
