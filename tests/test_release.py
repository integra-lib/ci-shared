#!/usr/bin/env python3
"""Tests for scripts/release.py. Standard library only.

Run:  python3 -m unittest discover -s tests -v
"""

import datetime
import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("release", ROOT / "scripts" / "release.py")
release = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(release)

CMAKE = "cmake_minimum_required(VERSION 3.21)\n\nproject(\n  hwlib_demo\n  VERSION {}\n  LANGUAGES CXX)\n"
DAY = datetime.date(2026, 9, 25)


class CommitLevel(unittest.TestCase):
    def test_feat_and_breaking_raise_the_minor(self):
        self.assertEqual(release.commit_level("feat: add Find", ""), release.eMINOR)
        self.assertEqual(release.commit_level("refactor!: rename", ""), release.eMINOR)
        self.assertEqual(release.commit_level("fix(ci): x", "text\n\nBREAKING CHANGE: api"), release.eMINOR)

    def test_patch_types(self):
        for kind in ("fix", "perf", "refactor", "docs", "build"):
            self.assertEqual(release.commit_level(f"{kind}: x", ""), release.ePATCH, kind)

    def test_other_types_and_release_commits_do_not_release(self):
        for subject in ("ci: x", "test: x", "style: x", "chore: x", "Merge branch 'a'",
                        "chore(release): 0.1.0 -> 0.2.0 [skip ci]"):
            self.assertEqual(release.commit_level(subject, ""), release.eNONE, subject)

    def test_breaking_word_in_body_text_is_not_a_footer(self):
        self.assertEqual(release.commit_level("docs: x", "mentions a BREAKING CHANGE: in prose"), release.ePATCH)


class Bump(unittest.TestCase):
    def test_bump(self):
        self.assertEqual(release.bump((0, 1, 4), release.eMINOR), (0, 2, 0))
        self.assertEqual(release.bump((0, 1, 4), release.ePATCH), (0, 1, 5))
        self.assertEqual(release.bump((0, 1, 4), release.eNONE), (0, 1, 4))


class CmakeVersion(unittest.TestCase):
    def test_reads_and_writes_the_project_version_only(self):
        cmake = CMAKE.format("0.1.0")
        updated = release.set_cmake_version(cmake, (0, 2, 0))
        self.assertIn("  VERSION 0.2.0\n", updated)
        self.assertIn("cmake_minimum_required(VERSION 3.21)", updated)
        self.assertEqual(release.cmake_version(updated), (0, 2, 0))

    def test_refuses_ambiguous_or_missing_line(self):
        with self.assertRaises(release.ReleaseError):
            release.cmake_version("project(x)\n")
        with self.assertRaises(release.ReleaseError):
            release.cmake_version(CMAKE.format("0.1.0") + CMAKE.format("0.1.0"))


class Repository(unittest.TestCase):
    """End to end on a throwaway repository with a bare remote."""

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        base = Path(self._dir.name)
        self.remote = base / "remote.git"
        self.repo = base / "repo"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.remote)], check=True)
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.repo)], check=True)
        self.git("config", "user.name", "test")
        self.git("config", "user.email", "test@example.com")
        self.git("remote", "add", "origin", str(self.remote))

    def tearDown(self):
        self._dir.cleanup()

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], check=True, capture_output=True,
                              text=True).stdout.strip()

    def commit(self, subject, body="", version=None):
        path = self.repo / "CMakeLists.txt"
        if version is not None:
            path.write_text(CMAKE.format(version))
        else:
            (self.repo / "file.txt").write_text(subject + body)
        self.git("add", "-A")
        message = subject + ("\n\n" + body if body else "")
        self.git("commit", "-q", "-m", message)

    def run_release(self, push=False):
        return release.release(self.repo, push=push, dry_run=False, today=DAY)

    def test_breaking_change_after_tag_releases_next_minor(self):
        self.commit("feat: initial", version="0.1.0")
        self.git("tag", "-a", "v0.1.0", "-m", "v0.1.0")
        self.commit("refactor!: rename integra to hwlib")
        self.commit("ci: pipeline tweak")

        self.assertEqual(self.run_release(), "v0.2.0")
        self.assertIn("  VERSION 0.2.0\n", self.git("show", "HEAD:CMakeLists.txt") + "\n")
        self.assertIn("## v0.2.0", self.git("show", "HEAD:CHANGELOG.md"))
        self.assertEqual(self.git("status", "--porcelain"), "")
        self.assertEqual(self.git("log", "-1", "--format=%s"), "chore(release): 0.1.0 -> 0.2.0 [skip ci]")
        self.assertEqual(self.git("describe", "--tags", "--exact-match"), "v0.2.0")
        changelog = (self.repo / "CHANGELOG.md").read_text()
        self.assertTrue(changelog.startswith("# Changelog\n\n## v0.2.0 (2026-09-25)\n"))
        self.assertIn("### Breaking changes\n\n* refactor!: rename integra to hwlib\n", changelog)
        self.assertIn("### Refactoring\n\n* rename integra to hwlib (", changelog)
        self.assertNotIn("pipeline tweak", changelog)

    def test_only_non_release_commits_release_nothing(self):
        self.commit("feat: initial", version="0.1.0")
        self.git("tag", "-a", "v0.1.0", "-m", "v0.1.0")
        self.commit("ci: pipeline tweak")
        head = self.git("rev-parse", "HEAD")

        self.assertIsNone(self.run_release())
        self.assertEqual(self.git("rev-parse", "HEAD"), head)

    def test_release_commit_does_not_trigger_another_release(self):
        self.commit("feat: initial", version="0.1.0")
        self.git("tag", "-a", "v0.1.0", "-m", "v0.1.0")
        self.commit("fix: off by one")
        self.assertEqual(self.run_release(), "v0.1.1")

        self.assertIsNone(self.run_release())

    def test_untagged_repository_releases_the_declared_version(self):
        self.commit("feat: initial", version="0.2.0")
        self.commit("fix: something")

        self.assertEqual(self.run_release(), "v0.2.0")
        self.assertIn("  VERSION 0.2.0\n", (self.repo / "CMakeLists.txt").read_text())

    def test_hand_raised_version_above_computed_stops(self):
        self.commit("feat: initial", version="0.1.0")
        self.git("tag", "-a", "v0.1.0", "-m", "v0.1.0")
        self.commit("fix: small", version="0.3.0")
        head = self.git("rev-parse", "HEAD")

        with self.assertRaises(release.ReleaseError):
            self.run_release()
        self.assertEqual(self.git("rev-parse", "HEAD"), head)
        self.assertEqual(self.git("tag", "-l", "v0.1.1"), "")

    def test_declared_version_equal_to_computed_is_accepted(self):
        self.commit("feat: initial", version="0.1.0")
        self.git("tag", "-a", "v0.1.0", "-m", "v0.1.0")
        self.commit("refactor!: rename", version="0.2.0")

        self.assertEqual(self.run_release(), "v0.2.0")

    def test_existing_changelog_keeps_older_sections_below(self):
        self.commit("feat: initial", version="0.1.0")
        (self.repo / "CHANGELOG.md").write_text("# Changelog\n\n## v0.1.0 (2026-09-01)\n\n* old\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "docs: changelog")
        self.git("tag", "-a", "v0.1.0", "-m", "v0.1.0")
        self.commit("feat: new thing")

        self.run_release()
        changelog = (self.repo / "CHANGELOG.md").read_text()
        self.assertLess(changelog.index("## v0.2.0"), changelog.index("## v0.1.0"))
        self.assertIn("* old\n", changelog)

    def test_push_publishes_commit_and_tag_together(self):
        self.commit("feat: initial", version="0.1.0")
        self.git("tag", "-a", "v0.1.0", "-m", "v0.1.0")
        self.git("push", "-q", "origin", "main", "v0.1.0")
        self.commit("feat: more")

        self.assertEqual(self.run_release(push=True), "v0.2.0")
        remote = subprocess.run(["git", "ls-remote", str(self.remote)],
                                check=True, capture_output=True, text=True).stdout
        self.assertIn("refs/tags/v0.2.0", remote)
        self.assertIn(self.git("rev-parse", "HEAD") + "\trefs/heads/main", remote)

    def test_dry_run_changes_nothing(self):
        self.commit("feat: initial", version="0.1.0")
        self.git("tag", "-a", "v0.1.0", "-m", "v0.1.0")
        self.commit("feat: more")
        head = self.git("rev-parse", "HEAD")

        self.assertEqual(release.release(self.repo, push=False, dry_run=True), "v0.2.0")
        self.assertEqual(self.git("rev-parse", "HEAD"), head)
        self.assertEqual(self.git("tag", "-l", "v0.2.0"), "")


if __name__ == "__main__":
    unittest.main()
