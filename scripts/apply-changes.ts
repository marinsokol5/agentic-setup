#!/usr/bin/env bun
// The targets are real copies, not symlinks: tools that write configs atomically
// (write temp file, then rename) reject or silently replace symlinked files —
// a symlinked CLAUDE.md has caused exactly those write errors before. Copying
// also keeps half-finished repo edits from going live before an explicit apply.
import { copyFileSync, existsSync, mkdirSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");

const MANAGED_FILES = [
  { src: "AGENTS.md", dest: join(homedir(), ".codex", "AGENTS.md") },
  { src: "CLAUDE.md", dest: join(homedir(), ".claude", "CLAUDE.md") },
];

const dryRun = process.argv.includes("--dry-run");
const useColor = process.stdout.isTTY && !process.env.NO_COLOR;
const paint = (code: string, text: string) => (useColor ? `\x1b[${code}m${text}\x1b[0m` : text);
const pretty = (path: string) => path.replace(homedir(), "~");

const LABELS = {
  created: paint("32", "+ created  "),
  replaced: paint("33", "● replaced "),
  unchanged: paint("2", "· unchanged"),
};

const counts = { created: 0, replaced: 0, unchanged: 0 };

for (const { src, dest } of MANAGED_FILES) {
  const srcPath = join(repoRoot, src);
  const repoContent = readFileSync(srcPath, "utf8");

  let status: keyof typeof counts;
  if (!existsSync(dest)) status = "created";
  else if (readFileSync(dest, "utf8") === repoContent) status = "unchanged";
  else status = "replaced";
  counts[status]++;

  console.log(`${LABELS[status]}  ${pretty(dest)}  ${paint("2", `← ${src}`)}`);

  if (status !== "unchanged" && !dryRun) {
    mkdirSync(dirname(dest), { recursive: true });
    copyFileSync(srcPath, dest);
  }
}

const summary = `${counts.created} created, ${counts.replaced} replaced, ${counts.unchanged} unchanged`;
console.log(dryRun ? `\ndry run — nothing written (${summary})` : `\ndone — ${summary}`);
