#!/usr/bin/env python3
"""U1 upstream monitor helper and its deterministic fixture tests."""

import argparse
from datetime import date, datetime
from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from typing import List, Optional
from zoneinfo import ZoneInfo


ANCHOR_DATE = date(2026, 8, 20)
FORK_OWNED_PATHS = {"README.md", "update.json"}


@dataclass
class CandidateResult:
    status: str
    candidate_sha: Optional[str]
    conflicts: List[str]
    preserved: List[str]
    changed_paths: List[str]


def _run_git(repo, *args, check=True):
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=check,
        text=True,
        capture_output=True,
    )


def _git(repo, *args):
    return _run_git(repo, *args).stdout.strip()


def is_check_day(day, anchor=ANCHOR_DATE):
    """Return whether a local calendar date is an active two-day check date."""
    if isinstance(day, str):
        day = date.fromisoformat(day)
    delta = (day - anchor).days
    return delta >= 0 and delta % 2 == 0


def sync_state(main_sha, upstream_sha, main_is_ancestor, patched_contains_main):
    """Classify the safe action before any remote write is attempted."""
    if not patched_contains_main:
        return "patched-behind-main"
    if main_sha == upstream_sha:
        return "no-change"
    if main_is_ancestor:
        return "fast-forward"
    return "main-divergence"


def classify_paths(paths):
    """Classify a candidate without treating arbitrary website files as docs."""
    paths = [path.strip("/") for path in paths if path.strip("/")]
    if not paths:
        return "docs-only"

    def path_class(path):
        if path.startswith(".github/") or path in {
            "build.gradle",
            "settings.gradle",
            "gradle.properties",
            "gradlew",
            "gradlew.bat",
        }:
            return "build/release-sensitive"
        if path == "README.md" or path.startswith("docs/"):
            return "docs-only"
        if path.endswith((".md", ".markdown")) and "/" not in path:
            return "docs-only"
        if path.startswith(("app/", "player/")) or path.endswith(
            (".java", ".kt", ".kts", ".xml", ".gradle")
        ):
            return "runtime/high-risk"
        return "unknown/high-risk"

    classes = {path_class(path) for path in paths}
    if classes == {"docs-only"}:
        return "docs-only"
    if "build/release-sensitive" in classes:
        return "build/release-sensitive"
    if "runtime/high-risk" in classes:
        return "runtime/high-risk"
    return "unknown/high-risk"


def candidate_policy(open_prs, upstream_sha):
    """Return the action for open automation PRs without replacing reviewed work."""
    exact = f"automation/upstream-{upstream_sha[:7]}"
    names = {
        item if isinstance(item, str) else item.get("headRefName", "")
        for item in open_prs
    }
    if exact in names:
        return "already-open"
    if any(name.startswith("automation/upstream-") for name in names):
        return "stale-open"
    return "create"


def merge_candidate(repo, upstream_ref, base_ref):
    """Merge upstream into a detached patched candidate, preserving only owned files."""
    if _git(repo, "status", "--porcelain"):
        raise ValueError("candidate workspace must be clean")

    base_sha = _git(repo, "rev-parse", base_ref)
    _git(repo, "config", "user.name", "tvbox-upstream-monitor")
    _git(repo, "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com")
    _git(repo, "-c", "core.hooksPath=/dev/null", "checkout", "--detach", base_sha)
    merge = _run_git(
        repo,
        "-c",
        "core.hooksPath=/dev/null",
        "merge",
        "--no-ff",
        "--no-edit",
        upstream_ref,
        check=False,
    )
    if merge.returncode == 0:
        conflicts = []
        preserved = []
    else:
        conflicts = _git(repo, "diff", "--name-only", "--diff-filter=U").splitlines()
        preserved = sorted(path for path in conflicts if path in FORK_OWNED_PATHS)
        unsafe = sorted(path for path in conflicts if path not in FORK_OWNED_PATHS)
        if unsafe:
            _run_git(repo, "-c", "core.hooksPath=/dev/null", "merge", "--abort")
            return CandidateResult("conflict", None, unsafe, preserved, [])
        for path in preserved:
            _git(repo, "-c", "core.hooksPath=/dev/null", "checkout", "--ours", "--", path)
            _git(repo, "-c", "core.hooksPath=/dev/null", "add", "--", path)
        _git(repo, "-c", "core.hooksPath=/dev/null", "commit", "--no-edit")

    candidate_sha = _git(repo, "rev-parse", "HEAD")
    changed_paths = _git(repo, "diff", "--name-only", f"{base_sha}...HEAD").splitlines()
    return CandidateResult("clean", candidate_sha, [], preserved, changed_paths)


def _result_json(result):
    return {
        "status": result.status,
        "candidate_sha": result.candidate_sha,
        "conflicts": result.conflicts,
        "preserved": result.preserved,
        "changed_paths": result.changed_paths,
        "classification": classify_paths(result.changed_paths or result.conflicts),
    }


def _run_fixture_tests():
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(U1FixtureTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


class U1FixtureTests(unittest.TestCase):
    def test_strict_every_two_days_uses_calendar_boundaries(self):
        self.assertTrue(is_check_day(date(2026, 8, 20)))
        self.assertFalse(is_check_day(date(2026, 8, 21)))
        self.assertTrue(is_check_day(date(2026, 8, 22)))
        self.assertFalse(is_check_day(date(2026, 8, 31)))
        self.assertTrue(is_check_day(date(2026, 9, 1)))
        self.assertFalse(is_check_day(date(2026, 12, 31)))
        self.assertTrue(is_check_day(date(2027, 1, 1)))

    def test_main_sync_states_fail_closed(self):
        self.assertEqual(sync_state("same", "same", True, True), "no-change")
        self.assertEqual(sync_state("old", "new", True, True), "fast-forward")
        self.assertEqual(sync_state("old", "new", False, True), "main-divergence")
        self.assertEqual(sync_state("same", "same", True, False), "patched-behind-main")

    def test_classification_keeps_docs_only_narrow(self):
        self.assertEqual(classify_paths(["README.md", "docs/MIGRATION.md"]), "docs-only")
        self.assertEqual(classify_paths(["app/src/main/AndroidManifest.xml"]), "runtime/high-risk")
        self.assertEqual(classify_paths([".github/workflows/other.yml"]), "build/release-sensitive")
        self.assertEqual(classify_paths(["website/index.html"]), "unknown/high-risk")

    def test_open_pr_policy_preserves_exact_candidate_and_blocks_stale(self):
        exact = [{"headRefName": "automation/upstream-abcdef1"}]
        stale = [{"headRefName": "automation/upstream-1234567"}]
        self.assertEqual(candidate_policy(exact, "abcdef123456"), "already-open")
        self.assertEqual(candidate_policy(stale, "abcdef123456"), "stale-open")
        self.assertEqual(candidate_policy([], "abcdef123456"), "create")

    def test_workflow_keeps_candidate_and_write_permissions_separate(self):
        workflow = (Path(__file__).parents[1] / ".github/workflows/upstream-monitor.yml").read_text()
        self.assertIn("timezone: Asia/Shanghai", workflow)
        self.assertIn("cron: '22 12 * * *'", workflow)
        self.assertIn("cron: '22 22 * * *'", workflow)
        self.assertIn("force_check", workflow)
        self.assertIn("actions/checkout@v5", workflow)
        self.assertNotIn("actions/checkout@v4", workflow)
        self.assertIn("contents: read", workflow)
        self.assertIn("contents: write", workflow)
        self.assertIn("GITHUB_TOKEN: ''", workflow)
        self.assertNotIn("secrets.", workflow)
        write_block = workflow.split("  write_candidate:", 1)[1].split("\n  notify:", 1)[0]
        self.assertNotIn("gradle", write_block.lower())

    def test_clean_candidate_merge_is_buildable(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._new_repo(Path(tmp))
            _git(repo, "checkout", "-b", "patched")
            (repo / "fork.txt").write_text("fork\n")
            self._commit(repo, "fork patch")
            _git(repo, "checkout", "-b", "upstream", "main")
            (repo / "docs.md").write_text("upstream docs\n")
            self._commit(repo, "upstream docs")
            result = merge_candidate(repo, "upstream", "patched")
            self.assertEqual(result.status, "clean")
            self.assertEqual(result.conflicts, [])
            self.assertEqual(result.preserved, [])
            self.assertIn("docs.md", result.changed_paths)

    def test_candidate_merge_with_head_base_reports_upstream_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._new_repo(Path(tmp))
            _git(repo, "checkout", "-b", "patched")
            (repo / "fork.txt").write_text("fork\n")
            self._commit(repo, "fork patch")
            _git(repo, "checkout", "-b", "upstream", "main")
            (repo / "docs.md").write_text("upstream docs\n")
            self._commit(repo, "upstream docs")
            _git(repo, "checkout", "patched")
            result = merge_candidate(repo, "upstream", "HEAD")
            self.assertEqual(result.status, "clean")
            self.assertIn("docs.md", result.changed_paths)

    def test_fork_owned_files_are_preserved_but_other_conflict_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._new_repo(Path(tmp))
            _git(repo, "checkout", "-b", "patched")
            (repo / "README.md").write_text("fork README\n")
            (repo / "update.json").write_text('{"fork":true}\n')
            (repo / "runtime.txt").write_text("fork runtime\n")
            self._commit(repo, "fork changes")
            _git(repo, "checkout", "-b", "upstream", "main")
            (repo / "README.md").write_text("upstream README\n")
            (repo / "update.json").write_text('{"upstream":true}\n')
            (repo / "runtime.txt").write_text("upstream runtime\n")
            self._commit(repo, "upstream changes")
            result = merge_candidate(repo, "upstream", "patched")
            self.assertEqual(result.status, "conflict")
            self.assertEqual(result.conflicts, ["runtime.txt"])
            self.assertEqual(result.preserved, ["README.md", "update.json"])
            self.assertEqual(_git(repo, "status", "--porcelain"), "")

    def test_fork_owned_only_conflict_is_auto_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._new_repo(Path(tmp))
            _git(repo, "checkout", "-b", "patched")
            (repo / "README.md").write_text("fork README\n")
            (repo / "update.json").write_text('{"fork":true}\n')
            self._commit(repo, "fork identity")
            _git(repo, "checkout", "-b", "upstream", "main")
            (repo / "README.md").write_text("upstream README\n")
            (repo / "update.json").write_text('{"upstream":true}\n')
            self._commit(repo, "upstream identity")
            result = merge_candidate(repo, "upstream", "patched")
            self.assertEqual(result.status, "clean")
            self.assertEqual(result.conflicts, [])
            self.assertEqual(result.preserved, ["README.md", "update.json"])
            self.assertEqual((repo / "README.md").read_text(), "fork README\n")
            self.assertEqual((repo / "update.json").read_text(), '{"fork":true}\n')

    @staticmethod
    def _new_repo(parent):
        repo = parent / "repo"
        repo.mkdir()
        _git(repo, "init", "-b", "main")
        _git(repo, "config", "user.email", "fixture@example.invalid")
        _git(repo, "config", "user.name", "U1 Fixture")
        (repo / "README.md").write_text("base README\n")
        (repo / "update.json").write_text('{"base":true}\n')
        (repo / "runtime.txt").write_text("base runtime\n")
        U1FixtureTests._commit(repo, "base")
        return repo

    @staticmethod
    def _commit(repo, message):
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", message)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        return _run_fixture_tests()

    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    date_parser = subparsers.add_parser("date-gate")
    date_parser.add_argument("--date")
    date_parser.add_argument("--force-check", action="store_true")

    fixture_parser = subparsers.add_parser("fixture-test")
    fixture_parser.set_defaults(_fixture=True)

    candidate_parser = subparsers.add_parser("prepare-candidate")
    candidate_parser.add_argument("--repo", default=".")
    candidate_parser.add_argument("--upstream-ref", required=True)
    candidate_parser.add_argument("--base-ref", default="HEAD")

    args = parser.parse_args(argv)
    if args.command == "date-gate":
        if args.date:
            local_date = date.fromisoformat(args.date)
        else:
            local_date = datetime.now(ZoneInfo("Asia/Shanghai")).date()
        active = args.force_check or is_check_day(local_date)
        print(
            json.dumps(
                {
                    "active": active,
                    "anchor": ANCHOR_DATE.isoformat(),
                    "date": local_date.isoformat(),
                    "forced": args.force_check,
                    "timezone": "Asia/Shanghai",
                },
                ensure_ascii=False,
            )
        )
        return 0
    if args.command == "fixture-test":
        return _run_fixture_tests()
    if args.command == "prepare-candidate":
        result = merge_candidate(Path(args.repo), args.upstream_ref, args.base_ref)
        print(json.dumps(_result_json(result), ensure_ascii=False))
        return 0 if result.status == "clean" else 2
    parser.error(f"unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
