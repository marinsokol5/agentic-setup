# My Agentic Setup

Dump of my personal agentic coding setup on Macbook.  
I use 1xChatGPT-Plus and 2xClaude-Pro, roughly amounting to 65 euros per month.

## Apps

- [agent-manager](https://github.com/marinsokol5/agent-manager) -> Running multiple Claude and Codex accounts, tracking their usage, and pre-warming token windows.

## Skills

- [resume-lite](https://github.com/marinsokol5/resume-lite) -> Fast and deterministic alternative to `/compact` and lighter than `--resume; allows cross-referencing sessions between Claude and Codex.
- [change-review](https://github.com/marinsokol5/change-review) -> Per-line review of agent changes.
- [reddit-read](https://github.com/marinsokol5/reddit-read) -> Avoiding 403s when fetching a Reddit thread.

## Tools

- [rtk](https://github.com/rtk-ai/rtk) -> Saves input tokens by compressessing output of common CLI commands.

## Scripts

- [agentic-mv](scripts/agentic-mv.py) -> `mv` that persists your sessions and settings; can be used for moving, renaming, or even merging existing Claude/Codex projects.
- [agentic-init](scripts/agentic-init.py) -> Seeds a folder with an empty `AGENTS.md` and a `CLAUDE.md` that imports it.

