#!/usr/bin/env python3
"""U1 upstream monitor helper and its deterministic fixture tests."""

import argparse
from datetime import date, datetime
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import unittest
import time
from typing import List, Optional
from zoneinfo import ZoneInfo


ANCHOR_DATE = date(2026, 8, 20)
FORK_OWNED_PATHS = {"README.md", "update.json"}
FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
AUTOMATION_REASONS = {
    "fixture-tests-failure",
    "date-gate-failure",
    "probe-error",
    "candidate-preview-error",
    "candidate-conflict",
    "main-divergence",
    "candidate-validation-failure",
    "validated-tree-mismatch",
    "write-failure",
    "repair-failure",
    "candidate-branch-no-pr",
    "candidate-branch-missing-after-main",
    "candidate-closed-or-merged",
    "stale-open",
    "patched-behind-main",
    "no-actionable-delta",
}


@dataclass
class CandidateResult:
    status: str
    candidate_sha: Optional[str]
    conflicts: List[str]
    preserved: List[str]
    changed_paths: List[str]
    candidate_needed: bool
    validated_tree: Optional[str]


def _require_full_sha(value, label="upstream SHA"):
    if not FULL_SHA_RE.fullmatch(value or ""):
        raise ValueError(f"{label} must be a full 40-character lowercase SHA")
    return value


def candidate_branch_name(upstream_sha):
    return f"automation/upstream-{_require_full_sha(upstream_sha)}"


def issue_key(upstream_sha):
    return upstream_sha if FULL_SHA_RE.fullmatch(upstream_sha or "") else "global"


def issue_marker(reason, upstream_sha):
    if reason not in AUTOMATION_REASONS:
        raise ValueError(f"unsupported automation reason: {reason}")
    return f"<!-- tvbox-upstream-monitor:{reason}:{issue_key(upstream_sha)} -->"


def recovery_marker(issue_number):
    return f"<!-- tvbox-upstream-recovery:{issue_number} -->"


def marker_status(issue_body, comments, marker):
    if marker in (issue_body or ""):
        return 0
    if not isinstance(comments, list):
        return 2
    for comment in comments:
        if marker in (comment.get("body") or ""):
            return 0
    return 1


def tree_matches(actual_tree, validated_tree):
    return bool(validated_tree) and actual_tree == validated_tree


def notification_reason(
    fixture_result,
    date_gate_result,
    probe_state,
    validation,
    validation_result,
    write_result,
    repair_result,
    write_failure_reason="",
    repair_failure_reason="",
):
    if date_gate_result != "success":
        return "date-gate-failure"
    if fixture_result != "success":
        return "fixture-tests-failure"
    if repair_result in {"failure", "cancelled"}:
        return repair_failure_reason or "repair-failure"
    if write_result in {"failure", "cancelled"}:
        return write_failure_reason or "write-failure"
    if validation_result in {"failure", "cancelled"} or validation == "fail":
        return "candidate-validation-failure"
    if probe_state == "no-actionable-delta" and write_result == "success":
        return "no-actionable-delta"
    return probe_state if probe_state in AUTOMATION_REASONS else "probe-error"


def _flatten_pages(payload):
    if not isinstance(payload, list):
        raise ValueError("paginated GitHub response must be a list")
    if payload and all(isinstance(page, list) for page in payload):
        return [item for page in payload for item in page]
    return payload


def normalize_pull_requests(payload):
    normalized = []
    for item in _flatten_pages(payload):
        if not isinstance(item, dict):
            continue
        head = item.get("head") or {}
        head_repo = head.get("repo") or {}
        normalized.append(
            {
                "number": item.get("number"),
                "url": item.get("html_url", ""),
                "state": (
                    "MERGED"
                    if item.get("merged_at") is not None
                    else "OPEN"
                    if item.get("state") == "open"
                    else "CLOSED"
                ),
                "headRefName": head.get("ref", ""),
                "headRefOid": head.get("sha", ""),
                "headRepository": {"nameWithOwner": head_repo.get("full_name", "")},
                "baseRefName": (item.get("base") or {}).get("ref", ""),
            }
        )
    return normalized


def find_candidate_pr(prs, repository, branch, candidate_oid, base_ref="patched"):
    for pr in prs:
        if (
            pr.get("state") == "OPEN"
            and (pr.get("headRepository") or {}).get("nameWithOwner") == repository
            and pr.get("headRefName") == branch
            and pr.get("headRefOid") == candidate_oid
            and pr.get("baseRefName") == base_ref
        ):
            return pr
    return None


def unvalidated_candidate_prs(prs, repository, branch, candidate_oid, base_ref="patched"):
    return [
        pr
        for pr in prs
        if (
            pr.get("state") == "OPEN"
            and (pr.get("headRepository") or {}).get("nameWithOwner") == repository
            and pr.get("headRefName") == branch
            and (pr.get("headRefOid") != candidate_oid or pr.get("baseRefName") != base_ref)
        )
    ]


def recoverable_issue_numbers(issues, recovery_key):
    numbers = []
    for issue in issues:
        title = issue.get("title") or ""
        match = re.match(r"^\[upstream-monitor\] (?P<reason>[^ ]+) ", title)
        if not match or match.group("reason") not in AUTOMATION_REASONS:
            continue
        reason = match.group("reason")
        body = issue.get("body") or ""
        same_run_marker = issue_marker(reason, recovery_key)
        legacy_global_marker = issue_marker(reason, "global")
        if (
            same_run_marker in body
            or (
                recovery_key != "global"
                and reason in {"fixture-tests-failure", "date-gate-failure", "probe-error"}
                and legacy_global_marker in body
            )
        ):
            numbers.append(issue.get("number"))
    return [number for number in numbers if number is not None]


def run_gh(args, timeout=30, attempts=3, env=None):
    """Run a GitHub CLI command with bounded retry and argv-only execution."""
    if not args:
        raise ValueError("gh command arguments cannot be empty")
    command = ["gh", *args]
    command_env = os.environ.copy()
    if env:
        command_env.update(env)
    last_error = "unknown gh failure"
    for attempt in range(1, attempts + 1):
        try:
            completed = subprocess.run(
                command,
                check=False,
                text=True,
                capture_output=True,
                timeout=timeout,
                env=command_env,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            last_error = str(exc)
        else:
            if completed.returncode == 0:
                return completed.stdout
            last_error = completed.stderr.strip() or f"gh exited {completed.returncode}"
        if attempt < attempts:
            time.sleep(attempt * 2)
    raise RuntimeError(last_error)


def _gh_json(args, timeout=30):
    output = run_gh(args, timeout=timeout)
    try:
        return json.loads(output)
    except json.JSONDecodeError as exc:
        raise RuntimeError("gh returned invalid JSON") from exc


def list_pull_requests(repository, state="open"):
    payload = _gh_json(
        [
            "api",
            "--paginate",
            "--slurp",
            f"repos/{repository}/pulls?state={state}&per_page=100",
        ]
    )
    return normalize_pull_requests(payload)


def normalize_issues(payload):
    normalized = []
    for item in _flatten_pages(payload):
        if not isinstance(item, dict) or "pull_request" in item:
            continue
        normalized.append(
            {
                "number": item.get("number"),
                "title": item.get("title", ""),
                "body": item.get("body") or "",
                "state": (item.get("state") or "").upper(),
                "url": item.get("html_url", ""),
            }
        )
    return normalized


def list_issues(repository, state="all"):
    payload = _gh_json(
        [
            "api",
            "--paginate",
            "--slurp",
            f"repos/{repository}/issues?state={state}&per_page=100",
        ]
    )
    return normalize_issues(payload)
def list_issue_comments(repository, number):
    payload = _gh_json(
        [
            "api",
            "--paginate",
            "--slurp",
            f"repos/{repository}/issues/{number}/comments?per_page=100",
        ]
    )
    return _flatten_pages(payload)


def find_issue_by_marker(repository, marker, state="all"):
    for issue in list_issues(repository, state):
        if marker in (issue.get("body") or ""):
            return issue
        status = remote_issue_marker_status(repository, issue["number"], marker)
        if status == 0:
            return issue
        if status == 2:
            raise RuntimeError("could not establish Issue marker state")
    return None


def remote_issue_marker_status(repository, number, marker):
    try:
        issue = _gh_json(["api", f"repos/{repository}/issues/{number}"])
        comments = list_issue_comments(repository, number)
    except RuntimeError:
        return 2
    return marker_status(issue.get("body", ""), comments, marker)


def comment_issue_idempotent(repository, number, body, marker):
    status = remote_issue_marker_status(repository, number, marker)
    if status == 0:
        return
    if status != 1:
        raise RuntimeError("could not establish Issue marker state")
    last_error = None
    for attempt in range(1, 4):
        try:
            run_gh(
                ["issue", "comment", str(number), "--repo", repository, "--body", body],
                attempts=1,
            )
            return
        except RuntimeError as exc:
            last_error = exc
            status = remote_issue_marker_status(repository, number, marker)
            if status == 0:
                return
            if status != 1:
                raise RuntimeError("could not reconcile ambiguous Issue comment") from exc
            if attempt < 3:
                time.sleep(attempt * 2)
    raise RuntimeError("Issue comment could not be reconciled") from last_error


def edit_issue(repository, number, assignee="slashinchi"):
    run_gh(["issue", "edit", str(number), "--repo", repository, "--add-assignee", assignee])


def create_issue_with_reconcile(repository, title, body, assignee="slashinchi"):
    command = [
        "issue",
        "create",
        "--repo",
        repository,
        "--title",
        title,
        "--assignee",
        assignee,
        "--body",
        body,
    ]
    body_markers = re.findall(r"<!-- tvbox-upstream-monitor:[^>]+ -->", body)
    last_error = None
    for attempt in range(1, 4):
        try:
            return run_gh(command, attempts=1).strip()
        except RuntimeError as exc:
            last_error = exc
            existing = [
                issue
                for issue in list_issues(repository, "all")
                if any(marker in (issue.get("body") or "") for marker in body_markers)
                or (not body_markers and issue.get("title") == title)
            ]
            if existing:
                return str(existing[0].get("number"))
            if attempt < 3:
                time.sleep(attempt * 2)
    raise RuntimeError("Issue creation could not be reconciled") from last_error


def close_issue(repository, number):
    run_gh(["issue", "close", str(number), "--repo", repository])


def close_pr(repository, number):
    run_gh(
        [
            "pr",
            "close",
            str(number),
            "--repo",
            repository,
            "--comment",
            "U1 closed this PR because its head was not the validated candidate.",
        ]
    )


def create_pr_with_reconcile(repository, base, head, title, body, expected_oid, reviewer="slashinchi"):
    command = [
        "pr",
        "create",
        "--repo",
        repository,
        "--base",
        base,
        "--head",
        head,
        "--title",
        title,
        "--body",
        body,
        "--reviewer",
        reviewer,
    ]
    pr_url = ""
    last_error = None
    for attempt in range(1, 4):
        try:
            output = run_gh(command, timeout=60, attempts=1)
            pr_url = next((line.strip() for line in reversed(output.splitlines()) if line.strip()), "")
        except RuntimeError as exc:
            last_error = exc
        if pr_url:
            break
        try:
            recovered = find_candidate_pr(
                list_pull_requests(repository, "open"), repository, head, expected_oid, base
            )
        except RuntimeError as exc:
            last_error = exc
            recovered = None
        if recovered:
            pr_url = recovered.get("url", "")
            break
        if attempt < 3:
            time.sleep(attempt * 2)

    prs = list_pull_requests(repository, "open")
    recovered = find_candidate_pr(prs, repository, head, expected_oid, base)
    if recovered:
        pr_url = recovered.get("url", pr_url)
    if not pr_url:
        for pr in unvalidated_candidate_prs(prs, repository, head, expected_oid, base):
            close_pr(repository, pr["number"])
        raise RuntimeError("validated candidate PR could not be created or recovered") from last_error

    try:
        viewed = json.loads(
            run_gh(
                [
                    "pr",
                    "view",
                    pr_url,
                    "--repo",
                    repository,
                    "--json",
                    "state,headRefName,headRefOid,headRepository,baseRefName",
                ]
            )
        )
    except (RuntimeError, json.JSONDecodeError):
        viewed = recovered
    if not viewed or not (
        viewed.get("state") == "OPEN"
        and viewed.get("headRefName") == head
        and viewed.get("headRefOid") == expected_oid
        and (viewed.get("headRepository") or {}).get("nameWithOwner") == repository
        and viewed.get("baseRefName") == base
    ):
        for pr in unvalidated_candidate_prs(prs, repository, head, expected_oid, base):
            close_pr(repository, pr["number"])
        raise RuntimeError("candidate PR identity verification failed")
    for pr in unvalidated_candidate_prs(
        list_pull_requests(repository, "open"), repository, head, expected_oid, base
    ):
        close_pr(repository, pr["number"])
    return pr_url


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
    exact = candidate_branch_name(upstream_sha)
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
        return CandidateResult(
            "clean",
            base_sha,
            [],
            [],
            [],
            False,
            _git(repo, "rev-parse", f"{base_sha}^{{tree}}"),
        )

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
            return CandidateResult("conflict", None, unsafe, preserved, [], True, None)

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
    validated_tree = _git(repo, "rev-parse", "HEAD^{tree}")
    return CandidateResult(
        "clean",
        candidate_sha,
        [],
        preserved,
        changed_paths,
        bool(changed_paths),
        validated_tree,
    )


def _result_json(result):
    return {
        "status": result.status,
        "candidate_sha": result.candidate_sha,
        "conflicts": result.conflicts,
        "preserved": result.preserved,
        "changed_paths": result.changed_paths,
        "candidate_needed": result.candidate_needed,
        "validated_tree": result.validated_tree,
        "classification": classify_paths(result.changed_paths or result.conflicts),
    }


def _run_fixture_tests():
    project_root = Path(__file__).resolve().parents[1]
    test_dir = project_root / "scripts" / "tests"
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    suite = unittest.defaultTestLoader.discover(str(test_dir), pattern="test_*.py")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


def _read_json_stdin():
    try:
        value = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        raise ValueError("stdin must contain JSON") from exc
    return value


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

    branch_parser = subparsers.add_parser("candidate-branch")
    branch_parser.add_argument("--upstream-sha", required=True)

    key_parser = subparsers.add_parser("issue-key")
    key_parser.add_argument("--upstream-sha", default="")

    marker_parser = subparsers.add_parser("issue-marker")
    marker_parser.add_argument("--reason", required=True)
    marker_parser.add_argument("--upstream-sha", default="")

    recovery_marker_parser = subparsers.add_parser("recovery-marker")
    recovery_marker_parser.add_argument("--number", required=True, type=int)

    tree_parser = subparsers.add_parser("tree-check")
    tree_parser.add_argument("--actual", required=True)
    tree_parser.add_argument("--expected", required=True)

    reason_parser = subparsers.add_parser("notification-reason")
    reason_parser.add_argument("--fixture-result", required=True)
    reason_parser.add_argument("--date-gate-result", required=True)
    reason_parser.add_argument("--probe-state", default="")
    reason_parser.add_argument("--validation", default="")
    reason_parser.add_argument("--validation-result", default="")
    reason_parser.add_argument("--write-result", default="")
    reason_parser.add_argument("--write-failure-reason", default="")
    reason_parser.add_argument("--repair-result", default="")
    reason_parser.add_argument("--repair-failure-reason", default="")

    find_issue_parser = subparsers.add_parser("find-issue")
    find_issue_parser.add_argument("--repo", required=True)
    find_issue_parser.add_argument("--marker", required=True)
    find_issue_parser.add_argument("--state", choices=("open", "all"), default="all")

    policy_parser = subparsers.add_parser("candidate-policy")
    policy_parser.add_argument("--upstream-sha", required=True)
    policy_parser.add_argument("--repository")
    policy_parser.add_argument("--candidate-oid")
    policy_parser.add_argument("--base-ref", default="patched")

    prs_parser = subparsers.add_parser("list-prs")
    prs_parser.add_argument("--repo", required=True)
    prs_parser.add_argument("--state", choices=("open", "all"), default="open")

    issues_parser = subparsers.add_parser("list-issues")
    issues_parser.add_argument("--repo", required=True)
    issues_parser.add_argument("--state", choices=("open", "all"), default="all")

    recover_parser = subparsers.add_parser("recoverable-issues")
    recover_parser.add_argument("--recovery-key", required=True)

    create_pr_parser = subparsers.add_parser("create-pr")
    create_pr_parser.add_argument("--repo", required=True)
    create_pr_parser.add_argument("--base", required=True)
    create_pr_parser.add_argument("--head", required=True)
    create_pr_parser.add_argument("--title", required=True)
    create_pr_parser.add_argument("--body-file", required=True)
    create_pr_parser.add_argument("--expected-oid", required=True)
    create_pr_parser.add_argument("--reviewer", default="slashinchi")

    create_issue_parser = subparsers.add_parser("issue-create")
    create_issue_parser.add_argument("--repo", required=True)
    create_issue_parser.add_argument("--title", required=True)
    create_issue_parser.add_argument("--body-file", required=True)
    create_issue_parser.add_argument("--assignee", default="slashinchi")

    comment_parser = subparsers.add_parser("issue-comment")
    comment_parser.add_argument("--repo", required=True)
    comment_parser.add_argument("--number", required=True, type=int)
    comment_parser.add_argument("--body-file", required=True)
    comment_parser.add_argument("--marker", required=True)

    edit_parser = subparsers.add_parser("issue-edit")
    edit_parser.add_argument("--repo", required=True)
    edit_parser.add_argument("--number", required=True, type=int)
    edit_parser.add_argument("--assignee", default="slashinchi")

    close_issue_parser = subparsers.add_parser("issue-close")
    close_issue_parser.add_argument("--repo", required=True)
    close_issue_parser.add_argument("--number", required=True, type=int)

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
    if args.command == "candidate-branch":
        print(candidate_branch_name(args.upstream_sha))
        return 0
    if args.command == "issue-key":
        print(issue_key(args.upstream_sha))
        return 0
    if args.command == "issue-marker":
        print(issue_marker(args.reason, args.upstream_sha))
        return 0
    if args.command == "recovery-marker":
        print(recovery_marker(args.number))
        return 0
    if args.command == "tree-check":
        return 0 if tree_matches(args.actual, args.expected) else 1
    if args.command == "notification-reason":
        print(
            notification_reason(
                fixture_result=args.fixture_result,
                date_gate_result=args.date_gate_result,
                probe_state=args.probe_state,
                validation=args.validation,
                validation_result=args.validation_result,
                write_result=args.write_result,
                repair_result=args.repair_result,
                write_failure_reason=args.write_failure_reason,
                repair_failure_reason=args.repair_failure_reason,
            )
        )
        return 0
    if args.command == "find-issue":
        issue = find_issue_by_marker(args.repo, args.marker, args.state)
        if issue:
            print(json.dumps(issue, separators=(",", ":")))
        return 0
    if args.command == "candidate-policy":
        print(
            candidate_policy(
                _read_json_stdin(),
                args.upstream_sha,
                repository=args.repository,
                candidate_oid=args.candidate_oid,
                base_ref=args.base_ref,
            )
        )
        return 0
    if args.command == "list-prs":
        print(json.dumps(list_pull_requests(args.repo, args.state), separators=(",", ":")))
        return 0
    if args.command == "list-issues":
        print(json.dumps(list_issues(args.repo, args.state), separators=(",", ":")))
        return 0
    if args.command == "recoverable-issues":
        print(json.dumps(recoverable_issue_numbers(_read_json_stdin(), args.recovery_key)))
        return 0
    if args.command == "create-pr":
        body = Path(args.body_file).read_text()
        print(
            create_pr_with_reconcile(
                args.repo,
                args.base,
                args.head,
                args.title,
                body,
                args.expected_oid,
                args.reviewer,
            )
        )
        return 0
    if args.command == "issue-create":
        body = Path(args.body_file).read_text()
        print(create_issue_with_reconcile(args.repo, args.title, body, args.assignee))
        return 0
    if args.command == "issue-comment":
        body = Path(args.body_file).read_text()
        comment_issue_idempotent(args.repo, args.number, body, args.marker)
        return 0
    if args.command == "issue-edit":
        edit_issue(args.repo, args.number, args.assignee)
        return 0
    if args.command == "issue-close":
        close_issue(args.repo, args.number)
        return 0
    parser.error(f"unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
