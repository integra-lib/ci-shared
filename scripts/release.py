#!/usr/bin/env python3
"""Release a component from its conventional commits: version, changelog, tag.

Run by the `release` job of templates/component.yml on a protected `main`, from the
component's root. Standard library only, so the job installs nothing: the runner
cannot reach GitHub reliably, and npm or PyPI are no better bets.

What it does, in order:
  1. finds the latest `vX.Y.Z` tag reachable from HEAD;
  2. derives the bump from the commits after it (rules below);
  3. writes the version into the `  VERSION x.y.z` line of CMakeLists.txt, which is
     what dependants check through the HWLIB_VERSION target property;
  4. prepends a section to CHANGELOG.md;
  5. commits `chore(release): a -> b [skip ci]`, tags `vb`, and with --push pushes
     both in one atomic push.

Bump rules — the ones the components' former .releaserc.js used. Before 1.0 a
minor release may break the API, so a breaking change raises the minor:
  breaking change (`type!:` or a `BREAKING CHANGE` footer), feat -> minor
  fix, perf, refactor, docs, build                               -> patch
  anything else — `chore(release)` commits included — -> no release

A repository without a tag is released at the version CMakeLists.txt already
declares, unbumped. A version in CMakeLists.txt above the computed one stops the
release: someone raised it by hand, and guessing which one is meant is worse than
asking.

Usage:
  release.py --dry-run     print the plan, change nothing
  release.py               commit and tag locally
  release.py --push        commit, tag and push
"""

from __future__ import annotations

import argparse
import datetime
import re
import subprocess
import sys
from pathlib import Path

TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
HEADER_RE = re.compile(r"^(?P<type>[a-zA-Z]+)(?:\([^)]*\))?(?P<bang>!)?:\s*(?P<text>.*)$")
BREAKING_RE = re.compile(r"^BREAKING[ -]CHANGE:", re.MULTILINE)
VERSION_LINE_RE = re.compile(r"^  VERSION (\d+)\.(\d+)\.(\d+)$", re.MULTILINE)

eNONE, ePATCH, eMINOR = 0, 1, 2
MINOR_TYPES = {"feat"}
PATCH_TYPES = {"fix", "perf", "refactor", "docs", "build"}

# Changelog sections, in order; other types are not listed.
SECTIONS = [("feat", "Features"), ("fix", "Bug Fixes"), ("refactor", "Refactoring"),
            ("perf", "Performance improvements")]


class ReleaseError(Exception):
    pass


def git(root: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    if proc.returncode != 0:
        raise ReleaseError(f"git {' '.join(args)}: {proc.stderr.strip()}")
    return proc.stdout.strip()


def parse_version(text: str) -> tuple[int, int, int]:
    major, minor, patch = (int(part) for part in text.split("."))
    return major, minor, patch


def format_version(version: tuple[int, int, int]) -> str:
    return ".".join(str(part) for part in version)


def commit_level(subject: str, body: str) -> int:
    header = HEADER_RE.match(subject)
    if header is None:
        return eNONE
    if header["bang"] or BREAKING_RE.search(body):
        return eMINOR
    kind = header["type"].lower()
    if kind in MINOR_TYPES:
        return eMINOR
    if kind in PATCH_TYPES:
        return ePATCH
    return eNONE


def bump(version: tuple[int, int, int], level: int) -> tuple[int, int, int]:
    major, minor, patch = version
    if level == eMINOR:
        return major, minor + 1, 0
    if level == ePATCH:
        return major, minor, patch + 1
    return version


def latest_tag(root: Path) -> str | None:
    proc = subprocess.run(["git", "-C", str(root), "describe", "--tags", "--abbrev=0", "--match", "v[0-9]*"],
                          capture_output=True, text=True)
    tag = proc.stdout.strip()
    return tag if proc.returncode == 0 and TAG_RE.match(tag) else None


def commits_since(root: Path, tag: str | None) -> list[tuple[str, str, str]]:
    """(sha, subject, body) of the non-merge commits after `tag`, oldest first."""
    revision = f"{tag}..HEAD" if tag else "HEAD"
    # NUL between fields and RS between records: bodies contain newlines.
    out = git(root, "log", revision, "--no-merges", "--reverse", "--format=%h%x00%s%x00%b%x1e")
    commits = []
    for record in out.split("\x1e"):
        record = record.strip("\n")
        if record:
            sha, subject, body = (record.split("\x00", 2) + ["", ""])[:3]
            commits.append((sha, subject, body))
    return commits


def cmake_version(cmake: str) -> tuple[int, int, int]:
    found = VERSION_LINE_RE.findall(cmake)
    if len(found) != 1:
        raise ReleaseError(f"CMakeLists.txt must have exactly one '  VERSION x.y.z' line, found {len(found)}")
    return tuple(int(part) for part in found[0])  # type: ignore[return-value]


def set_cmake_version(cmake: str, version: tuple[int, int, int]) -> str:
    updated = VERSION_LINE_RE.sub(f"  VERSION {format_version(version)}", cmake)
    if cmake_version(updated) != version:
        raise ReleaseError("CMakeLists.txt VERSION line was not updated")
    return updated


def changelog_section(version: tuple[int, int, int], commits: list[tuple[str, str, str]], day: datetime.date) -> str:
    lines = [f"## v{format_version(version)} ({day.isoformat()})", ""]
    breaking = [s for _, s, b in commits
                if HEADER_RE.match(s) and (HEADER_RE.match(s)["bang"] or BREAKING_RE.search(b))]
    if breaking:
        lines += ["### Breaking changes", ""] + [f"* {s}" for s in breaking] + [""]
    for kind, title in SECTIONS:
        entries = []
        for sha, subject, _ in commits:
            header = HEADER_RE.match(subject)
            if header and header["type"].lower() == kind:
                entries.append(f"* {header['text']} ({sha})")
        if entries:
            lines += [f"### {title}", ""] + entries + [""]
    return "\n".join(lines) + "\n"


def plan(root: Path) -> tuple[tuple[int, int, int], tuple[int, int, int], list[tuple[str, str, str]]] | None:
    """(current, next, commits), or None when there is nothing to release."""
    declared = cmake_version((root / "CMakeLists.txt").read_text())
    tag = latest_tag(root)
    if tag is None:
        # First release: the version the repository already declares.
        return declared, declared, commits_since(root, None)
    current = parse_version(tag[1:])
    commits = commits_since(root, tag)
    level = max((commit_level(s, b) for _, s, b in commits), default=eNONE)
    if level == eNONE:
        return None
    new = bump(current, level)
    if declared > new:
        raise ReleaseError(f"CMakeLists.txt declares {format_version(declared)}, above the computed "
                           f"{format_version(new)} (from {tag}); fix one of them by hand")
    return current, new, commits


def release(root: Path, push: bool, dry_run: bool, today: datetime.date | None = None) -> str | None:
    """Returns the tag created, or None when there is nothing to release."""
    result = plan(root)
    if result is None:
        print("nothing to release: no release-worthy commit since the last tag")
        return None
    current, new, commits = result
    tag = f"v{format_version(new)}"
    print(f"release {format_version(current)} -> {format_version(new)} as {tag} ({len(commits)} commit(s))")
    if dry_run:
        return tag
    if git(root, "tag", "-l", tag):
        raise ReleaseError(f"tag {tag} already exists")

    cmake_path = root / "CMakeLists.txt"
    cmake_path.write_text(set_cmake_version(cmake_path.read_text(), new))
    changelog_path = root / "CHANGELOG.md"
    previous = changelog_path.read_text() if changelog_path.exists() else "# Changelog\n\n"
    head, _, rest = previous.partition("\n\n")
    section = changelog_section(new, commits, today or datetime.date.today())
    changelog_path.write_text(f"{head}\n\n{section}\n{rest}".rstrip("\n") + "\n")

    git(root, "add", "CMakeLists.txt", "CHANGELOG.md")
    git(root, "commit", "-m", f"chore(release): {format_version(current)} -> {format_version(new)} [skip ci]")
    git(root, "tag", "-a", tag, "-m", tag)
    if push:
        branch = git(root, "rev-parse", "--abbrev-ref", "HEAD")
        git(root, "push", "--atomic", "origin", branch, tag)
        print(f"pushed {branch} and {tag}")
    return tag


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--push", action="store_true", help="push the release commit and tag to origin")
    parser.add_argument("--dry-run", action="store_true", help="print the plan, change nothing")
    args = parser.parse_args()
    try:
        release(Path.cwd(), push=args.push, dry_run=args.dry_run)
    except ReleaseError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
