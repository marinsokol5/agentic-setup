#!/usr/bin/env python3
"""agentic-init: seed a folder with the AGENTS.md / CLAUDE.md pair.

Creates two files in the target folder (default: the current one):

  AGENTS.md   empty — the single place shared agent instructions go
  CLAUDE.md   one line, "@AGENTS.md", so Claude Code imports the same file
              every other agent already reads

If either file is already there, nothing is written at all — the folder is
left exactly as it was and the command exits non-zero. Existing instructions
are the thing you least want an init script to touch, so there is no --force.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

AGENTS_MD = ""              # deliberately empty: the user fills it in
CLAUDE_MD = "@AGENTS.md\n"  # Claude Code import syntax -> reads AGENTS.md

FILES = {"AGENTS.md": AGENTS_MD, "CLAUDE.md": CLAUDE_MD}


def describe(name: str, content: str) -> str:
    return f"{name}  (empty)" if not content else f'{name}  ("{content.strip()}")'


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="agentic-init",
        description="create an empty AGENTS.md plus a CLAUDE.md that imports it",
        epilog="examples:\n"
               "  agentic-init .            # seed the current folder\n"
               "  agentic-init ~/projects/new-thing\n"
               "  agentic-init -n .         # dry-run: show what would be created",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dir", nargs="?", default=".", help="folder to initialize (default: .)")
    ap.add_argument("-n", "--dry-run", action="store_true",
                    help="report what would be created, write nothing")
    args = ap.parse_args()

    target = Path(os.path.abspath(os.path.expanduser(args.dir)))
    if not target.is_dir():
        ap.error(f"{target} is not a directory")

    print(f"agentic-init: {target}")

    # existence check first, across both files: either one present aborts the
    # whole thing, so we never leave a half-initialized folder behind
    present = [n for n in FILES if (target / n).exists() or (target / n).is_symlink()]
    if present:
        verb = "already exists" if len(present) == 1 else "already exist"
        print(f"\nabort: {' and '.join(present)} {verb} in {target} — nothing written.")
        return 1

    print("\n== plan ==\n")
    for name, content in FILES.items():
        print(f"  create {describe(name, content)}")

    if args.dry_run:
        print(f"\ndry-run: no files created ({len(FILES)} pending).")
        return 0

    print()
    created: list[Path] = []
    try:
        for name, content in FILES.items():
            path = target / name
            with open(path, "x", encoding="utf-8") as fh:  # x: last-moment race guard
                fh.write(content)
            created.append(path)
            print(f"  ok    create {describe(name, content)}")
    except OSError as exc:
        print(f"  FAIL  {exc}")
        for path in created:  # roll back, so an abort really writes nothing
            try:
                path.unlink()
                print(f"  ok    rolled back {path.name}")
            except OSError as rb:
                print(f"  FAIL  could not roll back {path}: {rb}")
        return 1

    print(f"\ndone: {len(created)} file(s) created in {target}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
