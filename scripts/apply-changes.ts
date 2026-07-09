#!/usr/bin/env bun
// Sync the repo's managed dotfiles with their live locations, in either direction:
//   push (default) — copy repo → live (~/.codex, ~/.claude). Applies committed edits.
//   pull           — copy live → repo. Persists edits made to the live files back here.
//
// The targets are real copies, not symlinks: tools that write configs atomically
// (write temp file, then rename) reject or silently replace symlinked files —
// a symlinked CLAUDE.md has caused exactly those write errors before. Copying
// also keeps half-finished repo edits from going live before an explicit push.
import { copyFileSync, existsSync, mkdirSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");

const MANAGED_FILES = [
  { src: "AGENTS.md", dest: join(homedir(), ".codex", "AGENTS.md") },
  { src: "CLAUDE.md", dest: join(homedir(), ".claude", "CLAUDE.md") },
];

const args = process.argv.slice(2);
const dryRun = args.includes("--dry-run");
const positional = args.filter((a) => !a.startsWith("-"));
const direction = positional[0] ?? "push";
if (positional.length > 1 || (direction !== "push" && direction !== "pull")) {
  console.error("usage: apply-changes.ts [push|pull] [--dry-run]");
  process.exit(1);
}
const reverse = direction === "pull";

const useColor = process.stdout.isTTY && !process.env.NO_COLOR;
const paint = (code: string, text: string) => (useColor ? `\x1b[${code}m${text}\x1b[0m` : text);
const pretty = (path: string) => path.replace(homedir(), "~");

const LABELS = {
  created: paint("32", "+ created  "),
  replaced: paint("33", "● replaced "),
  unchanged: paint("2", "· unchanged"),
  missing: paint("31", "⚠ missing  "),
};

const counts = { created: 0, replaced: 0, unchanged: 0, missing: 0 };

type Status = keyof typeof counts;

// Copy `from` → `to`, but only when they differ. Returns what happened so the
// caller can report and tally it. `missing` means `from` doesn't exist (only
// reachable on pull, when a live file was never applied) — nothing is written.
function syncOne(from: string, to: string): Status {
  if (!existsSync(from)) return "missing";
  const fromContent = readFileSync(from, "utf8");

  let status: Status;
  if (!existsSync(to)) status = "created";
  else if (readFileSync(to, "utf8") === fromContent) status = "unchanged";
  else status = "replaced";

  if (status !== "unchanged" && !dryRun) {
    mkdirSync(dirname(to), { recursive: true });
    copyFileSync(from, to);
  }
  return status;
}

for (const { src, dest } of MANAGED_FILES) {
  const repoPath = join(repoRoot, src);
  const from = reverse ? dest : repoPath;
  const to = reverse ? repoPath : dest;
  // Keep the repo file shown by its short relative name and the live file with ~.
  const fromDisplay = reverse ? pretty(dest) : src;
  const toDisplay = reverse ? src : pretty(dest);

  const status = syncOne(from, to);
  counts[status]++;
  console.log(`${LABELS[status]}  ${toDisplay}  ${paint("2", `← ${fromDisplay}`)}`);
}

const parts = [`${counts.created} created`, `${counts.replaced} replaced`, `${counts.unchanged} unchanged`];
if (counts.missing) parts.push(`${counts.missing} missing`);
const summary = `${direction}: ${parts.join(", ")}`;
console.log(dryRun ? `\ndry run — nothing written (${summary})` : `\ndone — ${summary}`);
