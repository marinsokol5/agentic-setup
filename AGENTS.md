# Prompt prefixes

All prefixes below are composable — they can be chained in any combination (e.g. `st: ro: s:`).

## Response length prefixes

When the user's prompt starts with one of these prefixes, constrain the response length:

- **`ss:`** (super-short) — answer in a **single sentence**.
- **`s:`** (short) — answer in **two short paragraphs**, 1–2 sentences each.
- **`yn:`** (yes/no) — lead with a literal **"Yes"/"No"/"It depends"**, then at most one sentence of justification.
- **`cvm:`** (caveman) — answer that one reply in caveman **full** style per the rules in `CAVEMAN.md` (imported below); use another level if the prefix names one (e.g. `cvm:ultra`). Keep all technical substance, code blocks, commands, and error strings exact. No length cap beyond the terseness itself.

No preambles, summaries, or follow-up offers that would push past the limit.

## Behavior prefixes

- **`ro:`** (read-only) — investigate and answer, but **do not modify any files or state**.
- **`ross:`** (read-only super-short) — shorthand for `ro: ss:`
- **`st:`** (standalone) — treat the question as basic and independent of the current project or folder, exactly as if asked fresh in a plain chat with no workspace context. Do not read any files, inspect the repo, or use project context; answer purely from general knowledge.

# Prompt commands

Unlike prefixes, these are standalone commands — the whole prompt is the command itself. They end with `!` (the reverse of the shell's `!` prefix) to avoid collisions with ordinary prose.

- **`gcm!`** (git commit) — commit the current code: bundle **all** outstanding changes (staged, unstaged, and untracked files) into a single commit with a concise message. If text follows `gcm!`, use it as the commit message.
- **`pl!`** (plain) — restate your previous message in plain language, shorter: short sentences, everyday words, lead with the point, no jargon without a one-word gloss. Simpler, not dumber — keep the technical substance and don't talk down to the reader.

@/Users/marinsokol/.codex/RTK.md
@/Users/marinsokol/.codex/CAVEMAN.md
