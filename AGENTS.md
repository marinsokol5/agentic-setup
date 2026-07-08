# Prompt prefixes

All prefixes below are composable — they can be chained in any combination (e.g. `st: ro: s:`).

## Response length prefixes

When the user's prompt starts with one of these prefixes, constrain the response length:

- **`ss:`** (super-short) — answer in a **single sentence**.
- **`s:`** (short) — answer in a **single paragraph**, max 4–5 sentences.
- **`yn:`** (yes/no) — lead with a literal **"Yes"/"No"/"It depends"**, then at most one sentence of justification.

No preambles, summaries, or follow-up offers that would push past the limit.

## Behavior prefixes

- **`ro:`** (read-only) — investigate and answer, but **do not modify any files or state**.
- **`st:`** (standalone) — treat the question as basic and independent of the current project or folder, exactly as if asked fresh in a plain chat with no workspace context. Do not read any files, inspect the repo, or use project context; answer purely from general knowledge.

# Prompt commands

Unlike prefixes, these are standalone commands — the whole prompt is the command itself.

- **`gcm`** (git commit) — commit the current code: bundle **all** outstanding changes (staged, unstaged, and untracked files) into a single commit with a concise message. If text follows `gcm`, use it as the commit message.

