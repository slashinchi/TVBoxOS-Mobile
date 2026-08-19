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
    candidate_needed: bool


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
        if path == "README.md":
            return "docs-only"
        if path.startswith("docs/") and path.endswith((".md", ".markdown", ".txt", ".adoc", ".rst")):
            return "docs-only"
        if path in {"CHANGELOG.md", "LICENSE.md", "NOTICE.md"}:
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


def candidate_policy(open_prs, upstream_sha, repository=None, candidate_oid=None, base_ref="patched"):
    """Mirror the workflow PR policy for deterministic fixture coverage."""
    exact = f"automation/upstream-{upstream_sha[:7]}"
    for item in open_prs:
        if isinstance(item, str):
            name = item
            state = "OPEN"
            head_repository = repository
            head_oid = None
            base_name = base_ref
        else:
            name = item.get("headRefName", "")
            state = item.get("state", "OPEN")
            head_repository = (item.get("headRepository") or {}).get("nameWithOwner")
            head_oid = item.get("headRefOid")
            base_name = item.get("baseRefName", base_ref)
        if repository is not None and head_repository != repository:
            continue
        if name == exact and state == "OPEN" and base_name != base_ref:
            return "stale-open"
        if name == exact and state == "OPEN" and (candidate_oid is None or head_oid == candidate_oid):
            return "already-open"
        if name == exact and state == "OPEN":
            return "stale-open"
        if name == exact and state != "OPEN":
            return "closed-or-merged"
        if name.startswith("automation/upstream-") and state == "OPEN":
            return "stale-open"
    return "create"


def merge_candidate(repo, upstream_ref, base_ref):
    """Merge upstream into a detached patched candidate, preserving only owned files."""
    if _git(repo, "status", "--porcelain"):
        raise ValueError("candidate workspace must be clean")

    base_sha = _git(repo, "rev-parse", base_ref)
    if _run_git(repo, "merge-base", "--is-ancestor", upstream_ref, base_sha, check=False).returncode == 0:
        return CandidateResult("clean", base_sha, [], [], [], False)

    upstream_changed_paths = _git(
        repo, "diff", "--name-only", f"{base_sha}...{upstream_ref}"
    ).splitlines()
    owned_upstream_changes = sorted(
        path for path in FORK_OWNED_PATHS if path in upstream_changed_paths
    )
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
        preserved = owned_upstream_changes
    else:
        conflicts = _git(repo, "diff", "--name-only", "--diff-filter=U").splitlines()
        preserved = sorted(
            set(owned_upstream_changes) | {path for path in conflicts if path in FORK_OWNED_PATHS}
        )
        unsafe = sorted(path for path in conflicts if path not in FORK_OWNED_PATHS)
        if unsafe:
            _run_git(repo, "-c", "core.hooksPath=/dev/null", "merge", "--abort")
            return CandidateResult("conflict", None, unsafe, preserved, [], True)

    for path in preserved:
        if _run_git(repo, "cat-file", "-e", f"{base_sha}:{path}", check=False).returncode == 0:
            _git(repo, "-c", "core.hooksPath=/dev/null", "checkout", base_sha, "--", path)
        else:
            _run_git(repo, "-c", "core.hooksPath=/dev/null", "rm", "-f", "--", path, check=False)
        _git(repo, "-c", "core.hooksPath=/dev/null", "add", "-A", "--", path)

    if merge.returncode == 0:
        if _run_git(repo, "diff", "--cached", "--quiet", check=False).returncode != 0:
            _git(repo, "-c", "core.hooksPath=/dev/null", "commit", "--amend", "--no-edit")
    else:
        _git(repo, "-c", "core.hooksPath=/dev/null", "commit", "--no-edit")

    candidate_sha = _git(repo, "rev-parse", "HEAD")
    changed_paths = _git(repo, "diff", "--name-only", f"{base_sha}...HEAD").splitlines()
    return CandidateResult("clean", candidate_sha, [], preserved, changed_paths, bool(changed_paths))


def _result_json(result):
    return {
        "status": result.status,
        "candidate_sha": result.candidate_sha,
        "conflicts": result.conflicts,
        "preserved": result.preserved,
        "changed_paths": result.changed_paths,
        "candidate_needed": result.candidate_needed,
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
        self.assertEqual(classify_paths(["AGENTS.md"]), "unknown/high-risk")
        self.assertEqual(classify_paths(["docs/release.sh"]), "unknown/high-risk")
        self.assertEqual(classify_paths(["docs/config.json"]), "unknown/high-risk")
        self.assertEqual(classify_paths(["app/src/main/AndroidManifest.xml"]), "runtime/high-risk")
        self.assertEqual(classify_paths([".github/workflows/other.yml"]), "build/release-sensitive")
        self.assertEqual(classify_paths(["website/index.html"]), "unknown/high-risk")

    def test_open_pr_policy_preserves_exact_candidate_and_blocks_stale(self):
        exact = [{"headRefName": "automation/upstream-abcdef1"}]
        stale = [{"headRefName": "automation/upstream-1234567"}]
        self.assertEqual(candidate_policy(exact, "abcdef123456"), "already-open")
        self.assertEqual(candidate_policy(stale, "abcdef123456"), "stale-open")
        self.assertEqual(candidate_policy([], "abcdef123456"), "create")
        self.assertEqual(
            candidate_policy(
                [{
                    "headRefName": "automation/upstream-abcdef1",
                    "state": "CLOSED",
                    "headRepository": {"nameWithOwner": "slashinchi/TVBoxOS-Mobile"},
                }],
                "abcdef123456",
                repository="slashinchi/TVBoxOS-Mobile",
            ),
            "closed-or-merged",
        )
        self.assertEqual(
            candidate_policy(
                [{
                    "headRefName": "automation/upstream-abcdef1",
                    "state": "OPEN",
                    "headRefOid": "other",
                    "headRepository": {"nameWithOwner": "external/fork"},
                }],
                "abcdef123456",
                repository="slashinchi/TVBoxOS-Mobile",
                candidate_oid="expected",
            ),
            "create",
        )
        self.assertEqual(
            candidate_policy(
                [{
                    "headRefName": "automation/upstream-abcdef1",
                    "state": "OPEN",
                    "headRefOid": "expected",
                    "headRepository": {"nameWithOwner": "slashinchi/TVBoxOS-Mobile"},
                    "baseRefName": "main",
                }],
                "abcdef123456",
                repository="slashinchi/TVBoxOS-Mobile",
                candidate_oid="expected",
            ),
            "stale-open",
        )

    def test_workflow_keeps_candidate_and_write_permissions_separate(self):
        workflow = (Path(__file__).parents[1] / ".github/workflows/upstream-monitor.yml").read_text()
        self.assertIn("timezone: Asia/Shanghai", workflow)
        self.assertIn("cron: '22 12 * * *'", workflow)
        self.assertIn("cron: '22 22 * * *'", workflow)
        self.assertIn("force_check", workflow)
        self.assertIn("actions/checkout@v5", workflow)
        self.assertNotIn("actions/checkout@v4", workflow)
        self.assertIn("$RUNNER_TEMP/candidate-result.json", workflow)
        self.assertIn("fetch-depth: 0", workflow)
        self.assertIn("needs: [fixture_tests, date_gate, probe, candidate_validation, write_candidate, repair_candidate_pr]", workflow)
        self.assertIn("needs.fixture_tests.result", workflow)
        self.assertIn("contents: read", workflow)
        self.assertIn("contents: write", workflow)
        self.assertIn("GITHUB_TOKEN: ''", workflow)
        self.assertNotIn("secrets.", workflow)
        self.assertIn('"$PROBE_STATE" != "no-actionable-delta"', workflow)
        self.assertIn("CANDIDATE_BRANCH_OID", workflow)
        self.assertIn("actual_candidate_oid", workflow)
        self.assertIn("expected_tree", workflow)
        self.assertIn("CANDIDATE_DIFF_STAT_B64", workflow)
        self.assertIn("recovery_key", workflow)
        self.assertIn("cache-disabled: true", workflow)
        self.assertNotIn("cache: gradle", workflow)
        self.assertIn("candidate-branch-missing-after-main", workflow)
        self.assertIn("candidate-closed-or-merged", workflow)
        self.assertIn("state=all&per_page=100", workflow)
        self.assertIn("headRepository", workflow)
        self.assertIn("headRefOid", workflow)
        self.assertIn("baseRefName", workflow)
        self.assertIn("--paginate", workflow)
        self.assertIn("pulls?state=all&per_page=100", workflow)
        self.assertIn("pulls?state=open&per_page=100", workflow)
        self.assertIn("candidate_validation.result == 'cancelled'", workflow)
        self.assertIn("needs.notify.result == 'success'", workflow)
        self.assertIn("timeout 30s gh pr close", workflow)
        self.assertIn("gh pr view", workflow)
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

    def test_fork_owned_changes_are_preserved_without_merge_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._new_repo(Path(tmp))
            _git(repo, "checkout", "-b", "patched")
            (repo / "README.md").write_text("fork README\nbase footer\n")
            (repo / "update.json").write_text('{"endpoint":"fork","version":1}\n')
            self._commit(repo, "fork identity")
            _git(repo, "checkout", "-b", "upstream", "main")
            (repo / "README.md").write_text("base README\nupstream footer\n")
            (repo / "update.json").write_text('{"endpoint":"base","version":2}\n')
            (repo / "docs.md").write_text("upstream docs\n")
            self._commit(repo, "upstream docs and identity")
            result = merge_candidate(repo, "upstream", "patched")
            self.assertTrue(result.candidate_needed)
            self.assertEqual(result.status, "clean")
            self.assertEqual(result.preserved, ["README.md", "update.json"])
            self.assertIn("docs.md", result.changed_paths)
            self.assertEqual((repo / "README.md").read_text(), "fork README\nbase footer\n")
            self.assertEqual((repo / "update.json").read_text(), '{"endpoint":"fork","version":1}\n')

    def test_only_fork_owned_clean_change_needs_no_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._new_repo(Path(tmp))
            _git(repo, "checkout", "-b", "patched")
            (repo / "README.md").write_text("fork README\nbase footer\n")
            self._commit(repo, "fork README")
            _git(repo, "checkout", "-b", "upstream", "main")
            (repo / "README.md").write_text("base README\nupstream footer\n")
            self._commit(repo, "upstream README")
            result = merge_candidate(repo, "upstream", "patched")
            self.assertEqual(result.status, "clean")
            self.assertFalse(result.candidate_needed)
            self.assertEqual(result.changed_paths, [])
            self.assertEqual(result.preserved, ["README.md"])
            self.assertEqual((repo / "README.md").read_text(), "fork README\nbase footer\n")

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

    def test_already_integrated_upstream_does_not_need_a_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._new_repo(Path(tmp))
            _git(repo, "checkout", "-b", "patched")
            (repo / "fork.txt").write_text("fork\n")
            self._commit(repo, "fork patch")
            _git(repo, "checkout", "-b", "upstream", "main")
            (repo / "docs.md").write_text("upstream docs\n")
            self._commit(repo, "upstream docs")
            _git(repo, "checkout", "patched")
            _git(repo, "merge", "--no-ff", "--no-edit", "upstream")
            result = merge_candidate(repo, "upstream", "HEAD")
            self.assertFalse(result.candidate_needed)
            self.assertEqual(result.changed_paths, [])

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
            self.assertFalse(result.candidate_needed)
            self.assertEqual((repo / "README.md").read_text(), "fork README\n")
            self.assertEqual((repo / "update.json").read_text(), '{"fork":true}\n')

    @staticmethod
    def _new_repo(parent):
        repo = parent / "repo"
        repo.mkdir()
        _git(repo, "init", "-b", "main")
        _git(repo, "config", "user.email", "fixture@example.invalid")
        _git(repo, "config", "user.name", "U1 Fixture")
        (repo / "README.md").write_text("base README\nbase footer\n")
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
