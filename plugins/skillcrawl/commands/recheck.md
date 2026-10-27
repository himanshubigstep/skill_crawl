---
description: Re-check the website after developers have fixed the issues (same as running /skillcrawl again).
argument-hint: (no arguments)
allowed-tools: Bash, Read, Write, Edit, mcp__claude-in-chrome__tabs_context_mcp, mcp__claude-in-chrome__tabs_create_mcp, mcp__claude-in-chrome__navigate, mcp__claude-in-chrome__get_page_text, mcp__claude-in-chrome__tabs_close_mcp
---

Run the SkillCrawl re-check. This is exactly the same workflow as `/skillcrawl`: follow every step
of `commands/skillcrawl.md` (next to this file) with empty arguments. `python3 "$SC" auto`
detects the earlier run by itself and starts a re-check. If it prints `NEEDS_SETUP` or
`MODE=FIRST_RUN`, tell the user no earlier check was found and that a first full check is
starting.
