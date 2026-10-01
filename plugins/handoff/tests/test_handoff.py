#!/usr/bin/env python3
"""Tests for scripts/handoff.py.

Standalone: python3 tests/test_handoff.py
Requires no third-party modules (nor does the script under test).

Each test drives handoff.py as a subprocess with HANDOFF_DIR and
CLAUDE_PROJECT_DIR pointed at throwaway temp dirs, so nothing touches the
real ~/.claude.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "handoff.py"

NOTE = "# Handoff: demo\n\n**Goal:** ship it\n\n## Next task\nrun the e2e\n"


class HandoffFixture(unittest.TestCase):

    def setUp(self):
        # resolve(): on macOS mkdtemp returns /var/... which is a symlink to
        # /private/var/... — path-equality assertions need the real path.
        self.tmp = Path(tempfile.mkdtemp(prefix="handoff-test-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.store = self.tmp / "store"
        self.project = self.tmp / "repo"
        self.project.mkdir()

    def run_handoff(self, *args: str, project: Path | None = None,
                    **env: str) -> subprocess.CompletedProcess:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            capture_output=True, text=True,
            env={**os.environ,
                 "HANDOFF_DIR": str(self.store),
                 "CLAUDE_PROJECT_DIR": str(project or self.project),
                 **env},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def arm(self, text: str = NOTE, age_minutes: float = 0,
            project: Path | None = None) -> Path:
        """Write a note the way the skill does: to the path `path` reports."""
        out = json.loads(self.run_handoff("path", project=project).stdout)
        path = Path(out["path"])
        path.write_text(text)
        if age_minutes:
            stamp = time.time() - age_minutes * 60
            os.utime(path, (stamp, stamp))
        return path


class TestPath(HandoffFixture):

    def test_path_is_under_store_and_creates_it(self):
        out = json.loads(self.run_handoff("path").stdout)
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["project_dir"], str(self.project))
        self.assertEqual(Path(out["path"]).parent, self.store)
        self.assertTrue(self.store.is_dir())
        self.assertFalse(out["exists"])
        self.assertFalse(out["workspace_detected"])
        self.assertEqual(out["ttl_minutes"], 60)

    def test_path_is_stable_and_distinct_per_project(self):
        other = self.tmp / "other"
        other.mkdir()
        first = json.loads(self.run_handoff("path").stdout)["path"]
        again = json.loads(self.run_handoff("path").stdout)["path"]
        elsewhere = json.loads(self.run_handoff("path", project=other).stdout)["path"]
        self.assertEqual(first, again)
        self.assertNotEqual(first, elsewhere)

    def test_path_reports_existing_note_and_workspace(self):
        self.arm()
        (self.project / "dev-env.yaml").write_text("repos: []\n")
        out = json.loads(self.run_handoff("path").stdout)
        self.assertTrue(out["exists"])
        self.assertTrue(out["workspace_detected"])

    def test_ttl_override(self):
        out = json.loads(self.run_handoff(
            "path", HANDOFF_TTL_MINUTES="5").stdout)
        self.assertEqual(out["ttl_minutes"], 5)


class TestRead(HandoffFixture):

    def test_fresh_note_is_injected_and_retired(self):
        path = self.arm()
        out = json.loads(self.run_handoff("read").stdout)
        ctx = out["hookSpecificOutput"]["additionalContext"]
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "SessionStart")
        self.assertIn("run the e2e", ctx)
        self.assertIn("BEGIN HANDOFF NOTE", ctx)
        self.assertIn("handoff", out["systemMessage"].lower())
        self.assertFalse(path.exists())
        self.assertEqual(path.with_name(path.stem + ".consumed.md").read_text(), NOTE)

    def test_fires_only_once(self):
        self.arm()
        self.assertTrue(self.run_handoff("read").stdout)
        self.assertEqual(self.run_handoff("read").stdout, "")

    def test_no_note_is_silent(self):
        self.assertEqual(self.run_handoff("read").stdout, "")

    def test_stale_note_is_silent_and_retired(self):
        path = self.arm(age_minutes=61)
        self.assertEqual(self.run_handoff("read").stdout, "")
        self.assertFalse(path.exists())

    def test_empty_note_is_silent(self):
        self.arm(text="  \n")
        self.assertEqual(self.run_handoff("read").stdout, "")

    def test_note_for_other_project_does_not_fire(self):
        other = self.tmp / "other"
        other.mkdir()
        path = self.arm(project=other)
        self.assertEqual(self.run_handoff("read").stdout, "")
        self.assertTrue(path.exists())

    def test_oversized_note_is_truncated(self):
        self.arm(text="x" * 100_000)
        ctx = json.loads(self.run_handoff("read").stdout)[
            "hookSpecificOutput"]["additionalContext"]
        self.assertLess(len(ctx), 20_000)

    def test_unwritable_store_never_fails(self):
        self.store.write_text("not a directory")
        self.assertEqual(self.run_handoff("read").stdout, "")


class TestClear(HandoffFixture):

    def test_clear_removes_armed_note(self):
        path = self.arm()
        out = json.loads(self.run_handoff("clear").stdout)
        self.assertEqual(out, {"status": "ok", "deleted": True})
        self.assertFalse(path.exists())
        self.assertEqual(self.run_handoff("read").stdout, "")

    def test_clear_without_note(self):
        out = json.loads(self.run_handoff("clear").stdout)
        self.assertEqual(out, {"status": "ok", "deleted": False})


class TestHookManifest(unittest.TestCase):

    def test_hook_runs_read_on_clear_only(self):
        hooks = json.loads((SCRIPT.parent.parent / "hooks" / "hooks.json").read_text())
        entries = hooks["hooks"]["SessionStart"]
        self.assertEqual([e["matcher"] for e in entries], ["clear"])
        self.assertIn("handoff.py\" read", entries[0]["hooks"][0]["command"])


if __name__ == "__main__":
    unittest.main()
