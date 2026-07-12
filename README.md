# My Agentic Setup

Dump of my personal agentic coding setup. 

## Personal Skills

- [resume-lite](https://github.com/marinsokol5/resume-lite) -> Resume a Claude Code or Codex session from a deterministic transcript. It's the fast, deterministic alternative to `/compact`, made to be lighter than `--resume`.
- [change-review](https://github.com/marinsokol5/change-review) -> The human review step for AI-written changes: your agent proposes, you decide — inline diff in the browser, line comments, per-chunk apply, verdict back to the agent as JSON.

## Scripts

- [agentic-mv](scripts/agentic-mv.py) -> `agentic-mv.py old/ new/`: `mv` that persists your Claude Code and Codex sessions and settings; resume history, project trust, allowed tools, and MCP config all follow the folder to its new path. Prints an explicit plan of every session it found, asks for confirmation, and backs up whatever it rewrites.

