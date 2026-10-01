#!/usr/bin/env python3
"""Locate, arm, and consume a standalone session handoff note.

`/handoff:handoff` writes a Markdown note for the current project directory;
the SessionStart hook bound to the `clear` matcher injects that note into the
next session and retires it. The note is the only state that crosses a /clear.

Notes live outside the repository, under ~/.claude/handoffs/, keyed by the
project directory. Nothing is ever written to the repo or its CLAUDE.md, so a
handoff never shows up in `git status` and never leaks into a teammate's
context.

Deliberately stdlib-only: `read` runs on every /clear and plugins cannot
declare python dependencies.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

DEFAULT_TTL_MINUTES = 60
# The note is injected verbatim; cap it so a runaway note cannot flood the
# fresh context it exists to protect.
MAX_INJECT_BYTES = 16 * 1024


def handoff_dir() -> Path:
    override = os.environ.get("HANDOFF_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".claude" / "handoffs"


def project_dir() -> Path:
    """The directory a handoff belongs to.

    CLAUDE_PROJECT_DIR is set by Claude Code for hooks and Bash calls alike,
    so `path` (run by the skill) and `read` (run by the hook) agree. Each git
    worktree is its own launch directory, hence its own handoff.
    """
    raw = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    return Path(raw).expanduser().resolve()


def note_key(directory: Path) -> str:
    """Flatten an absolute path into a filename, as ~/.claude/projects does."""
    return re.sub(r"[^A-Za-z0-9._-]", "-", str(directory)).strip("-") or "root"


def note_path(directory: Path) -> Path:
    """The single source of truth for where a project's note lives.

    `path`, `read` and `clear` all go through this. A divergence here would
    make the handoff silently never fire.
    """
    return handoff_dir() / f"{note_key(directory)}.md"


def consumed_path(directory: Path) -> Path:
    return handoff_dir() / f"{note_key(directory)}.consumed.md"


def ttl_seconds() -> int:
    try:
        minutes = int(os.environ.get("HANDOFF_TTL_MINUTES", DEFAULT_TTL_MINUTES))
    except ValueError:
        minutes = DEFAULT_TTL_MINUTES
    return max(minutes, 1) * 60


def emit(payload: dict) -> None:
    print(json.dumps(payload, indent=2))


def humanize_age(seconds: float) -> str:
    minutes = int(seconds // 60)
    if minutes < 1:
        return "just now"
    if minutes == 1:
        return "1 minute ago"
    if minutes < 60:
        return f"{minutes} minutes ago"
    hours = minutes // 60
    return "1 hour ago" if hours == 1 else f"{hours} hours ago"


def retire(path: Path, directory: Path) -> None:
    """Move a note aside so it cannot fire twice, keeping it for recovery."""
    try:
        path.replace(consumed_path(directory))
    except OSError:
        try:
            path.unlink()
        except OSError:
            pass


def consume(directory: Path) -> tuple[str, float] | None:
    """Return (note text, age in seconds) if a fresh note exists, else None.

    The note is retired whenever it existed, whatever its state, so a
    repeated /clear cannot re-fire and a stale note never fires late.
    Never raises: a bad note must not disturb a session start.
    """
    path = note_path(directory)
    if not path.is_file():
        return None
    try:
        age = time.time() - path.stat().st_mtime
        text = path.read_bytes()[:MAX_INJECT_BYTES].decode("utf-8", "replace")
    except OSError:
        retire(path, directory)
        return None

    retire(path, directory)

    if age > ttl_seconds() or not text.strip():
        return None
    # A negative age means clock skew, not a note from the future.
    return text, max(age, 0.0)


def build_context(text: str, age: float, directory: Path) -> str:
    return (
        f"Handoff from the previous session (saved {humanize_age(age)}) "
        f"for {directory}.\n\n"
        "Treat the note below as your working context. Before doing anything "
        "else: read the files it lists under \"Read first\", re-check the git "
        "state it describes (it may have changed), then report in two or "
        "three lines where things stand and what you will do next, and wait "
        "for the user to confirm.\n\n"
        "--- BEGIN HANDOFF NOTE ---\n"
        f"{text.rstrip()}\n"
        "--- END HANDOFF NOTE ---"
    )


def cmd_path(_: argparse.Namespace) -> int:
    directory = project_dir()
    path = note_path(directory)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        emit({"status": "error", "message": f"Could not create {path.parent}: {exc}"})
        return 0
    emit({
        "status": "ok",
        "project_dir": str(directory),
        "path": str(path),
        "exists": path.is_file(),
        "ttl_minutes": ttl_seconds() // 60,
        "workspace_detected": (directory / "dev-env.yaml").is_file(),
    })
    return 0


def cmd_read(_: argparse.Namespace) -> int:
    directory = project_dir()
    found = consume(directory)
    if found is None:
        return 0
    text, age = found
    emit({
        "systemMessage": (
            f"Loaded handoff note ({humanize_age(age)}). "
            "Send any message to resume work."
        ),
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": build_context(text, age, directory),
        },
    })
    return 0


def cmd_clear(_: argparse.Namespace) -> int:
    path = note_path(project_dir())
    existed = path.is_file()
    if existed:
        try:
            path.unlink()
        except OSError as exc:
            emit({"status": "error", "message": f"Could not delete {path}: {exc}"})
            return 0
    emit({"status": "ok", "deleted": existed})
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("path", help="Print where this project's handoff note goes")
    sub.add_parser("read", help="Consume a handoff at session start (hook mode)")
    sub.add_parser("clear", help="Disarm a pending handoff")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "path":
        return cmd_path(args)
    if args.command == "clear":
        return cmd_clear(args)
    if args.command == "read":
        try:
            return cmd_read(args)
        except Exception:
            # A SessionStart hook must never fail loudly; silence beats a
            # traceback in the user's fresh context.
            return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
