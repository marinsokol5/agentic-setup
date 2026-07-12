#!/usr/bin/env python3
"""agentic-mv: move/rename a project folder AND migrate Claude Code + Codex session storage.

Covers (per agent):
  Claude Code
    - <claude-home>/projects/<path-encoded>/       renamed (session .jsonl files + memory/ move with it)
    - session .jsonl files                         top-level "cwd" fields + file-history snapshot path keys rewritten
    - <claude-home>/.claude.json + ~/.claude.json  "projects" keys renamed (incl. nested sub-project keys)
    - <claude-home>/history.jsonl                  "project" field rewritten per entry
    - <claude-home>/sessions/*.json                live-session registry checked -> warns if a session is running in src
  Codex
    - <codex-home>/sessions/**/*.jsonl             payload "cwd" fields rewritten (session_meta, turn_context, ...)
    - <codex-home>/archived_sessions/**/*.jsonl    same, when present
    - <codex-home>/config.toml                     [projects."<path>"] trust entries renamed
    (history.jsonl / session_index.jsonl store no paths -> nothing to do)

Home dirs default to $CLAUDE_CONFIG_DIR / ~/.claude and $CODEX_HOME / ~/.codex.
Non-standard or extra locations: --claude-home-dirs / --codex-home-dirs (repeatable
or comma-separated). Storage shared between homes via symlinks is deduped by
realpath so nothing is rewritten twice.

If SRC no longer exists but DST does, the folder move is skipped and only session
metadata is migrated (recovery mode for "I already ran mv").

Rewritten files keep their original mtime so recency ordering in session pickers survives.
Originals are backed up to ~/.agentic-mv/backups/<timestamp>/ (disable with --no-backup).
"""

from __future__ import annotations

import argparse
import copy
import datetime
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator

# ---------------------------------------------------------------- path helpers


def norm(p: str) -> str:
    """Absolute path, ~ expanded, trailing slash stripped. Symlinks NOT resolved:
    session files record the literal cwd, so we must match it literally."""
    a = os.path.abspath(os.path.expanduser(p))
    return a.rstrip(os.sep) or os.sep


def encode_claude(path: str) -> str:
    """Claude Code's project-dir encoding: every non-alphanumeric char becomes '-'."""
    return re.sub(r"[^a-zA-Z0-9]", "-", path)


class Remapper:
    def __init__(self, src: str, dst: str):
        self.src, self.dst = src, dst

    def __call__(self, value: object) -> str | None:
        """New path if value is src or nested under it, else None."""
        if not isinstance(value, str):
            return None
        if value == self.src:
            return self.dst
        if value.startswith(self.src + os.sep):
            return self.dst + value[len(self.src):]
        return None


# ---------------------------------------------------------------- change model


@dataclass
class Change:
    """One planned mutation: a folder move, a dir rename, or a file rewrite."""

    group: str            # report section, e.g. "claude home: ~/.claude"
    description: str      # one explicit line, printed in plan and on apply
    path: Path | None     # file to back up before rewriting (None for renames/moves)
    apply: Callable[[], None]


@dataclass
class Plan:
    changes: list[Change] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)      # skips, ambiguities, dedupes
    warnings: list[str] = field(default_factory=list)   # live sessions etc.

    def add(self, group: str, description: str, apply: Callable[[], None],
            path: Path | None = None) -> None:
        self.changes.append(Change(group, description, path, apply))


# ---------------------------------------------------------------- file rewriting


def write_atomic(path: Path, data: str) -> None:
    """Write via temp file + rename, preserving the original mtime (session pickers
    sort by mtime; a metadata rewrite must not make old sessions look recent)."""
    st = path.stat()
    tmp = path.with_name(path.name + ".agentic-mv.tmp")
    tmp.write_text(data, encoding="utf-8")
    os.replace(tmp, path)
    os.utime(path, (st.st_atime, st.st_mtime))


def dumps_compact(obj: object) -> str:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def rewrite_jsonl(path: Path, transform: Callable[[dict], bool]) -> None:
    """Re-emit a .jsonl file, replacing only the lines `transform` mutates.
    Unparseable/untouched lines pass through byte-identical."""
    out: list[str] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            stripped = line.rstrip("\n")
            try:
                obj = json.loads(stripped)
            except (json.JSONDecodeError, ValueError):
                out.append(line)
                continue
            if isinstance(obj, dict) and transform(obj):
                out.append(dumps_compact(obj) + "\n")
            else:
                out.append(line)
    write_atomic(path, "".join(out))


# ---------------------------------------------------------------- Claude: session lines


def claude_line_hits(obj: dict, remap: Remapper, mutate: bool) -> int:
    """Count (and optionally apply) rewrites in one Claude session-jsonl line:
    the top-level cwd, plus file-history snapshot backups keyed by absolute path.
    Message bodies are history and are deliberately left untouched."""
    hits = 0
    new_cwd = remap(obj.get("cwd"))
    if new_cwd is not None:
        hits += 1
        if mutate:
            obj["cwd"] = new_cwd
    snapshot = obj.get("snapshot")
    if isinstance(snapshot, dict):
        backups = snapshot.get("trackedFileBackups")
        if isinstance(backups, dict):
            renames = [(k, remap(k)) for k in backups if remap(k) is not None]
            hits += len(renames)
            if mutate and renames:
                snapshot["trackedFileBackups"] = {
                    (dict(renames).get(k) or k): v for k, v in backups.items()
                }
    return hits


def probe_project_dir_cwd(project_dir: Path) -> str | None:
    """First top-level cwd recorded in any session file — identifies the real
    filesystem path behind an encoded dir name (encoding is lossy)."""
    for f in sorted(project_dir.glob("*.jsonl")):
        try:
            with open(f, encoding="utf-8") as fh:
                for line in fh:
                    try:
                        obj = json.loads(line)
                    except (json.JSONDecodeError, ValueError):
                        continue
                    cwd = obj.get("cwd") if isinstance(obj, dict) else None
                    if isinstance(cwd, str) and cwd:
                        return cwd
        except OSError:
            continue
    return None


def scan_claude_projects_dir(plan: Plan, group: str, projects_dir: Path,
                             remap: Remapper) -> None:
    enc_src = encode_claude(remap.src)
    enc_dst = encode_claude(remap.dst)

    candidates: list[tuple[Path, str, bool]] = []  # (dir, new_name, exact)
    for child in sorted(projects_dir.iterdir()):
        if not child.is_dir():
            continue
        if child.name == enc_src:
            candidates.append((child, enc_dst, True))
        elif child.name.startswith(enc_src + "-"):
            # Possibly a nested project (Claude opened in a subfolder of src) —
            # but the encoding is lossy, so /a/b-x and /a/b/x collide. Confirm
            # against a real cwd recorded inside before touching it.
            candidates.append((child, enc_dst + child.name[len(enc_src):], False))

    if not candidates:
        plan.notes.append(f"{group}: no session dirs match {enc_src}[-*] under {projects_dir}")
        return

    for child, new_name, exact in candidates:
        probed = probe_project_dir_cwd(child)
        if not exact:
            if probed is None:
                plan.notes.append(
                    f"{group}: SKIPPED {child.name} — name could be a nested project of src, "
                    f"but it has no session with a cwd to confirm (lossy encoding); rename manually if it is"
                )
                continue
            if remap(probed) is None:
                plan.notes.append(
                    f"{group}: skipped lookalike {child.name} (its sessions ran in {probed}, not under src)"
                )
                continue
        elif probed is not None and remap(probed) is None:
            plan.notes.append(
                f"{group}: note — {child.name} matches src exactly but its sessions record cwd={probed}"
            )

        sessions = sorted(child.glob("*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True)
        for f in sessions:
            hits = 0
            try:
                with open(f, encoding="utf-8") as fh:
                    for line in fh:
                        if remap.src not in line:
                            continue
                        try:
                            obj = json.loads(line)
                        except (json.JSONDecodeError, ValueError):
                            continue
                        if isinstance(obj, dict):
                            hits += claude_line_hits(obj, remap, mutate=False)
            except OSError as exc:
                plan.notes.append(f"{group}: could not read {f}: {exc}")
                continue
            mtime = datetime.datetime.fromtimestamp(f.stat().st_mtime)
            desc = (f"session {f.name}  (last active {mtime:%Y-%m-%d %H:%M})  "
                    f"{hits} path field(s) to rewrite")
            if hits:
                plan.add(group, desc, path=f, apply=lambda f=f: rewrite_jsonl(
                    f, lambda obj: claude_line_hits(obj, remap, mutate=True) > 0))
            else:
                plan.notes.append(f"{group}: {f.name} — no path fields to rewrite (moves with dir)")

        extras = [e.name for e in child.iterdir() if e.suffix != ".jsonl"]
        extra_note = f"  (+ {', '.join(sorted(extras))})" if extras else ""
        plan.add(
            group,
            f"rename project dir  {child.name}  ->  {new_name}"
            f"  ({len(sessions)} session file(s){extra_note})",
            apply=lambda child=child, new_name=new_name: child.rename(child.with_name(new_name)),
        )


# ---------------------------------------------------------------- Claude: config + history


def scan_claude_json(plan: Plan, group: str, cfg: Path, remap: Remapper) -> None:
    try:
        data = json.loads(cfg.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        plan.notes.append(f"{group}: could not parse {cfg}: {exc}")
        return
    projects = data.get("projects")
    if not isinstance(projects, dict):
        return
    renames = [(k, remap(k)) for k in projects if remap(k) is not None]
    for old, new in renames:
        if new in projects:
            plan.notes.append(
                f"{group}: {cfg.name} already has an entry for {new}; keeping it, dropping the {old} entry"
            )
    if not renames:
        plan.notes.append(f"{group}: {cfg} — no matching \"projects\" keys")
        return

    def apply() -> None:
        d = json.loads(cfg.read_text(encoding="utf-8"))
        d["projects"] = _rename_keys(d["projects"], dict(renames))
        write_atomic(cfg, dumps_compact(d))

    # one line per renamed key so the report is explicit; the file is written once
    for old, new in renames[:-1]:
        plan.add(group, f'{cfg}: projects["{old}"] -> projects["{new}"]',
                 apply=lambda: None, path=cfg)
    old, new = renames[-1]
    plan.add(group, f'{cfg}: projects["{old}"] -> projects["{new}"]', apply=apply, path=cfg)


def _rename_keys(d: dict, table: dict[str, str]) -> dict:
    out = {}
    for k, v in d.items():
        nk = table.get(k, k)
        if nk in out:  # collision with a pre-existing entry: keep the existing one
            continue
        out[nk] = v
    return out


def scan_claude_history(plan: Plan, group: str, hist: Path, remap: Remapper) -> None:
    hits = 0
    try:
        with open(hist, encoding="utf-8") as fh:
            for line in fh:
                if remap.src not in line:
                    continue
                try:
                    obj = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if isinstance(obj, dict) and remap(obj.get("project")) is not None:
                    hits += 1
    except OSError as exc:
        plan.notes.append(f"{group}: could not read {hist}: {exc}")
        return
    if not hits:
        plan.notes.append(f"{group}: {hist.name} — no entries for this project")
        return

    def transform(obj: dict) -> bool:
        new = remap(obj.get("project"))
        if new is None:
            return False
        obj["project"] = new
        return True

    plan.add(group, f"{hist}: rewrite \"project\" on {hits} prompt-history entr(ies)",
             path=hist, apply=lambda: rewrite_jsonl(hist, transform))


def check_claude_live_sessions(plan: Plan, group: str, sessions_dir: Path,
                               remap: Remapper) -> None:
    for f in sorted(sessions_dir.glob("*.json")):
        try:
            info = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(info, dict) or remap(info.get("cwd")) is None:
            continue
        pid = info.get("pid")
        try:
            os.kill(int(pid), 0)
            alive = True
        except (ProcessLookupError, TypeError, ValueError):
            alive = False
        except PermissionError:
            alive = True
        if alive:
            plan.warnings.append(
                f"{group}: LIVE Claude session (pid {pid}, session {info.get('sessionId')}) is running "
                f"in {info.get('cwd')} — quit it before moving, or it will keep writing to the old path"
            )


# ---------------------------------------------------------------- Codex


def codex_line_hits(obj: dict, remap: Remapper, mutate: bool) -> int:
    payload = obj.get("payload")
    if not isinstance(payload, dict):
        return 0
    new = remap(payload.get("cwd"))
    if new is None:
        return 0
    if mutate:
        payload["cwd"] = new
    return 1


def scan_codex_sessions(plan: Plan, group: str, sessions_dir: Path, remap: Remapper) -> None:
    found = False
    for f in sorted(sessions_dir.rglob("*.jsonl")):
        meta_cwd, session_id, hits = None, None, 0
        try:
            with open(f, encoding="utf-8") as fh:
                for i, line in enumerate(fh):
                    if i == 0 and '"session_meta"' in line:
                        try:
                            payload = json.loads(line).get("payload", {})
                            meta_cwd = payload.get("cwd")
                            session_id = payload.get("id") or payload.get("session_id")
                        except (json.JSONDecodeError, ValueError):
                            pass
                    if remap.src not in line:
                        continue
                    try:
                        obj = json.loads(line)
                    except (json.JSONDecodeError, ValueError):
                        continue
                    if isinstance(obj, dict):
                        hits += codex_line_hits(obj, remap, mutate=False)
        except OSError as exc:
            plan.notes.append(f"{group}: could not read {f}: {exc}")
            continue
        if not hits:
            continue
        found = True
        scope = "session cwd" if remap(meta_cwd) is not None else "some turns only"
        rel = f.relative_to(sessions_dir)
        plan.add(group,
                 f"session {rel}  (id {session_id}, {scope})  {hits} cwd field(s) to rewrite",
                 path=f,
                 apply=lambda f=f: rewrite_jsonl(
                     f, lambda obj: codex_line_hits(obj, remap, mutate=True) > 0))
    if not found:
        plan.notes.append(f"{group}: no sessions under {sessions_dir} recorded cwd in src")


CODEX_PROJECT_HEADER = re.compile(r'^(\s*\[projects\.")([^"]+)(".*)$')


def scan_codex_config(plan: Plan, group: str, cfg: Path, remap: Remapper) -> None:
    try:
        lines = cfg.read_text(encoding="utf-8").splitlines(keepends=True)
    except OSError as exc:
        plan.notes.append(f"{group}: could not read {cfg}: {exc}")
        return
    renames = []
    for line in lines:
        m = CODEX_PROJECT_HEADER.match(line)
        if m and remap(m.group(2)) is not None:
            renames.append((m.group(2), remap(m.group(2))))
    if not renames:
        plan.notes.append(f"{group}: {cfg.name} — no [projects] trust entries for this path")
        return

    def apply() -> None:
        current = cfg.read_text(encoding="utf-8").splitlines(keepends=True)
        out = []
        for line in current:
            m = CODEX_PROJECT_HEADER.match(line)
            new = remap(m.group(2)) if m else None
            out.append(m.group(1) + new + m.group(3) + ("\n" if line.endswith("\n") else "")
                       if m and new is not None else line)
        write_atomic(cfg, "".join(out))

    for old, new in renames:
        plan.add(group, f'{cfg.name}: [projects."{old}"] -> [projects."{new}"]',
                 apply=lambda: None, path=cfg)
    plan.changes[-1].apply = apply


# ---------------------------------------------------------------- home discovery


def resolve_homes(flag_values: list[str] | None, env_var: str, default_name: str) -> list[Path]:
    """Home dirs from the CLI flag (repeatable, comma-separated), or the default:
    $<env_var> if set, plus ~/<default_name>. Missing dirs are reported and dropped;
    duplicates (incl. via symlinks) collapse to the first occurrence."""
    if flag_values:
        homes = [Path(norm(p)) for v in flag_values for p in v.split(",") if p.strip()]
    else:
        homes = []
        if os.environ.get(env_var):
            homes.append(Path(norm(os.environ[env_var])))
        homes.append(Path.home() / default_name)

    seen, out = set(), []
    for h in homes:
        if not h.is_dir():
            if flag_values:  # only complain about dirs the user asked for
                print(f"warning: home dir {h} does not exist — skipped")
            continue
        r = h.resolve()
        if r not in seen:
            seen.add(r)
            out.append(h)
    return out


# ---------------------------------------------------------------- scan orchestration


class RealpathOnce:
    """Shared storage (AgentManager homes symlink projects/, history.jsonl, config.toml
    back to the primary home) must be rewritten exactly once."""

    def __init__(self, plan: Plan):
        self.seen: dict[Path, str] = {}
        self.plan = plan

    def first(self, path: Path, group: str) -> bool:
        real = path.resolve()
        if real in self.seen:
            self.plan.notes.append(
                f"{group}: {path} resolves to storage already handled under \"{self.seen[real]}\"")
            return False
        self.seen[real] = group
        return True


def build_plan(src: str, dst: str, claude_homes: list[Path], codex_homes: list[Path],
               move_folder: bool) -> Plan:
    plan = Plan()
    remap = Remapper(src, dst)

    if move_folder:
        def do_move() -> None:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.move(src, dst)
        plan.add("filesystem", f"move folder  {src}  ->  {dst}", apply=do_move)
    else:
        plan.notes.append(f"filesystem: {dst} already exists and {src} is gone — "
                          "folder move skipped, migrating session metadata only")

    once = RealpathOnce(plan)

    for home in claude_homes:
        group = f"claude home: {home}"
        projects = home / "projects"
        if projects.is_dir() and once.first(projects, group):
            scan_claude_projects_dir(plan, group, projects, remap)
        for cfg in [home / ".claude.json", Path.home() / ".claude.json"]:
            if cfg.is_file() and once.first(cfg, group):
                scan_claude_json(plan, group, cfg, remap)
        hist = home / "history.jsonl"
        if hist.is_file() and once.first(hist, group):
            scan_claude_history(plan, group, hist, remap)
        live = home / "sessions"
        if live.is_dir() and once.first(live, group):
            check_claude_live_sessions(plan, group, live, remap)

    for home in codex_homes:
        group = f"codex home: {home}"
        for name in ("sessions", "archived_sessions"):
            d = home / name
            if d.is_dir() and once.first(d, group):
                scan_codex_sessions(plan, group, d, remap)
        cfg = home / "config.toml"
        if cfg.is_file() and once.first(cfg, group):
            scan_codex_config(plan, group, cfg, remap)

    return plan


# ---------------------------------------------------------------- reporting + apply


def print_plan(plan: Plan, applied: bool = False) -> None:
    header = "applying" if applied else "plan"
    print(f"\n== {header} ==")
    current_group = None
    for c in plan.changes:
        if c.group != current_group:
            current_group = c.group
            print(f"\n[{current_group}]")
        print(f"  {c.description}")
    if plan.notes:
        print("\n[notes]")
        for n in plan.notes:
            print(f"  - {n}")
    if plan.warnings:
        print("\n[warnings]")
        for w in plan.warnings:
            print(f"  !! {w}")


def backup_file(path: Path, backup_root: Path) -> None:
    dest = backup_root / str(path.resolve()).lstrip(os.sep)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        shutil.copy2(path, dest)


def apply_plan(plan: Plan, backup_root: Path | None) -> int:
    failures = 0
    backed_up: set[Path] = set()
    for c in plan.changes:
        try:
            if backup_root is not None and c.path is not None and c.path not in backed_up:
                backup_file(c.path, backup_root)
                backed_up.add(c.path)
            c.apply()
            print(f"  ok    {c.description}")
        except Exception as exc:  # keep going; each change is independent
            failures += 1
            print(f"  FAIL  {c.description}\n        {exc}")
    return failures


# ---------------------------------------------------------------- main


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="agentic-mv",
        description="mv a project folder and migrate Claude Code + Codex session storage with it",
        epilog="examples:\n"
               "  agentic-mv ~/projects/agentic-setup ~/projects/agentic-mv\n"
               "  agentic-mv -n old/ new/          # dry-run: show what would be touched\n"
               "  agentic-mv old/ new/ --yes       # no confirmation prompt\n"
               "  agentic-mv old/ new/             # if you already ran plain mv: metadata-only mode\n"
               "  agentic-mv old/ new/ --claude-home-dirs ~/.claude,~/other-claude-home",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src", help="current project folder path")
    ap.add_argument("dst", help="new project folder path")
    ap.add_argument("-n", "--dry-run", action="store_true", help="report what would change, touch nothing")
    ap.add_argument("-y", "--yes", action="store_true", help="skip the confirmation prompt")
    ap.add_argument("--no-backup", action="store_true", help="don't back up files before rewriting")
    ap.add_argument("--claude-home-dirs", action="append", metavar="DIR[,DIR...]",
                    help="Claude Code home dir(s) to migrate; repeatable or comma-separated "
                         "(default: $CLAUDE_CONFIG_DIR if set, plus ~/.claude)")
    ap.add_argument("--codex-home-dirs", action="append", metavar="DIR[,DIR...]",
                    help="Codex home dir(s) to migrate; repeatable or comma-separated "
                         "(default: $CODEX_HOME if set, plus ~/.codex)")
    args = ap.parse_args()

    src, dst = norm(args.src), norm(args.dst)
    if src == dst:
        ap.error("src and dst are the same path")
    if dst.startswith(src + os.sep):
        ap.error(f"dst is inside src ({dst})")
    if src.startswith(dst + os.sep):
        ap.error(f"src is inside dst ({src})")

    src_exists, dst_exists = os.path.isdir(src), os.path.exists(dst)
    if src_exists and dst_exists:
        ap.error(f"both {src} and {dst} exist — refusing to overwrite")
    if not src_exists and not dst_exists:
        ap.error(f"neither {src} nor {dst} exists")
    move_folder = src_exists

    claude_homes = resolve_homes(args.claude_home_dirs, "CLAUDE_CONFIG_DIR", ".claude")
    codex_homes = resolve_homes(args.codex_home_dirs, "CODEX_HOME", ".codex")
    print(f"agentic-mv: {src}  ->  {dst}")
    print(f"claude homes: {', '.join(str(h) for h in claude_homes) or '(none found)'}")
    print(f"codex homes:  {', '.join(str(h) for h in codex_homes) or '(none found)'}")

    plan = build_plan(src, dst, claude_homes, codex_homes, move_folder)
    print_plan(plan)

    if not plan.changes:
        print("\nnothing to do.")
        return 0
    if args.dry_run:
        print(f"\ndry-run: no changes made ({len(plan.changes)} pending).")
        return 0

    if plan.warnings and not args.yes:
        print("\nlive sessions detected — resolve the warnings above or pass --yes to force.")
        return 1
    if not args.yes:
        if not sys.stdin.isatty():
            print("\nstdin is not a tty; pass --yes to proceed non-interactively.")
            return 1
        if input(f"\napply {len(plan.changes)} change(s)? [y/N] ").strip().lower() not in ("y", "yes"):
            print("aborted.")
            return 1

    backup_root = None
    if not args.no_backup:
        stamp = datetime.datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
        backup_root = Path.home() / ".agentic-mv" / "backups" / stamp
        backup_root.mkdir(parents=True, exist_ok=True)
        print(f"\nbacking up rewritten files under: {backup_root}")

    print()
    failures = apply_plan(plan, backup_root)
    edits = len({c.path for c in plan.changes if c.path is not None})
    print(f"\ndone: {len(plan.changes) - failures}/{len(plan.changes)} change(s) applied "
          f"({edits} file rewrite(s); original mtimes preserved).")
    if failures:
        print("some changes failed — fix the cause and re-run; the folder move is skipped "
              "automatically on re-run (metadata-only mode).")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
