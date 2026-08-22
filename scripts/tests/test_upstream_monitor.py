import subprocess
import tempfile
import unittest
from datetime import date, datetime
import re
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from scripts.upstream_monitor import (
    _git,
    candidate_branch_name,
    candidate_policy,
    classify_probe_state,
    classify_paths,
    create_issue_with_reconcile,
    coverage_body,
    coverage_marker,
    event_gate,
    issue_marker,
    is_check_day,
    main,
    marker_status,
    merge_candidate,
    normalize_issues,
    normalize_pull_requests,
    notification_reason,
    recoverable_issue_numbers,
    run_gh,
    scheduled_occurrence,
    sync_state,
    tree_matches,
)


ROOT = Path(__file__).parents[2]
WORKFLOW = ROOT / ".github/workflows/upstream-monitor.yml"
BUILD_WORKFLOW = ROOT / ".github/workflows/build.yml"


class U1aContractTests(unittest.TestCase):
    def test_calendar_gate_and_sync_states_remain_fail_closed(self):
        self.assertTrue(is_check_day(date(2026, 8, 20)))
        self.assertFalse(is_check_day(date(2026, 8, 21)))
        self.assertTrue(is_check_day(date(2027, 1, 1)))
        shanghai = ZoneInfo("Asia/Shanghai")
        self.assertEqual(
            scheduled_occurrence(
                "22 12 * * *", datetime(2026, 8, 20, 12, 54, tzinfo=shanghai)
            ).isoformat(),
            "2026-08-20T12:22:00+08:00",
        )
        self.assertEqual(
            scheduled_occurrence(
                "22 22 * * *", datetime(2026, 8, 21, 0, 5, tzinfo=shanghai)
            ).isoformat(),
            "2026-08-20T22:22:00+08:00",
        )
        with self.assertRaises(ValueError):
            scheduled_occurrence("", datetime(2026, 8, 20, 12, 54, tzinfo=shanghai))
        with self.assertRaises(ValueError):
            main(["date-gate", "--schedule", "", "--now", "2026-08-20T12:54:00+08:00"])
        self.assertEqual(sync_state("same", "same", True, True), "no-change")
        self.assertEqual(sync_state("old", "new", True, True), "fast-forward")
        self.assertEqual(sync_state("old", "new", False, True), "main-divergence")
        self.assertEqual(sync_state("same", "same", True, False), "no-change")
        self.assertEqual(
            sync_state("old", "new", True, False, candidate_needed=True),
            "actionable-main-ahead",
        )
        self.assertEqual(
            classify_probe_state(
                "old", "new", "true", "false", "clean", "false", "false", "none"
            ),
            "no-actionable-delta",
        )
        self.assertEqual(
            classify_probe_state(
                "old", "old", "true", "false", "clean", "false", "false", "none"
            ),
            "no-change",
        )
        self.assertEqual(
            classify_probe_state(
                "old", "new", "true", "false", "clean", "true", "false", "create"
            ),
            "actionable-main-ahead",
        )

    def test_u1c_event_gate_accepts_exact_watchdog_request(self):
        shanghai = ZoneInfo("Asia/Shanghai")
        event = {
            "action": "created",
            "issue": {"number": 2, "locked": True},
            "comment": {
                "user": {"login": "slashinchi"},
                "body": (
                    "<!-- TVBOX_UPSTREAM_WATCHDOG_V1 REQUEST -->\n"
                    "version=1\n"
                    "scheduled_for=2026-08-20T22:22:00+08:00\n"
                    "source=private-control-reconciliation"
                ),
            },
        }

        result = event_gate(
            event,
            "issue_comment",
            2,
            datetime(2026, 8, 21, 0, 5, tzinfo=shanghai),
        )

        self.assertEqual(result["accepted"], "true")
        self.assertEqual(result["request"], "true")
        self.assertEqual(result["occurrence"], "2026-08-20T22:22:00+08:00")

    def test_u1c_event_gate_rejects_replay_shaped_invalid_comments(self):
        shanghai = ZoneInfo("Asia/Shanghai")
        base = {
            "action": "created",
            "issue": {"number": 2, "locked": True},
            "comment": {
                "user": {"login": "slashinchi"},
                "body": (
                    "<!-- TVBOX_UPSTREAM_WATCHDOG_V1 REQUEST -->\n"
                    "version=1\n"
                    "scheduled_for=2026-08-20T22:22:00+08:00\n"
                    "source=private-control-reconciliation"
                ),
            },
        }
        now = datetime(2026, 8, 21, 0, 5, tzinfo=shanghai)

        for mutation in (
            {"issue": {"number": 2, "locked": False}},
            {"issue": {"number": 2, "locked": True, "pull_request": {}}},
            {"comment": {"user": {"login": "attacker"}}},
            {"issue": {"number": 3, "locked": True}},
        ):
            event = {**base, **mutation}
            result = event_gate(event, "issue_comment", 2, now)
            self.assertEqual(result["accepted"], "false")
            self.assertNotEqual(result["reason"], "")

    def test_u1c_event_gate_accepts_natural_schedule_and_dispatch(self):
        shanghai = ZoneInfo("Asia/Shanghai")
        schedule = event_gate(
            {"schedule": "22 12 * * *"},
            "schedule",
            2,
            datetime(2026, 8, 20, 12, 54, tzinfo=shanghai),
        )
        dispatch = event_gate({}, "workflow_dispatch", 2, datetime(2026, 8, 20, 12, 54, tzinfo=shanghai))

        self.assertEqual(schedule["accepted"], "true")
        self.assertEqual(schedule["request"], "false")
        self.assertEqual(schedule["occurrence"], "2026-08-20T12:22:00+08:00")
        self.assertEqual(dispatch["accepted"], "true")

    def test_u1c_coverage_marker_binds_full_occurrence(self):
        occurrence = "2026-08-20T22:22:00+08:00"
        marker = coverage_marker(occurrence)
        body = coverage_body(occurrence, "run-123", "no-change", "a" * 40, "b" * 40)

        self.assertEqual(marker, f"<!-- TVBOX_UPSTREAM_COVERED_V1:{occurrence} -->")
        self.assertIn(marker, body)
        self.assertIn("run_id=run-123", body)

    def test_u1c_event_gate_precedes_all_business_jobs(self):
        workflow = WORKFLOW.read_text()
        event_start = workflow.index("  event_gate:")
        date_start = workflow.index("  date_gate:")
        notify_start = workflow.index("  notify:")
        coverage_start = workflow.index("  coverage:")

        self.assertLess(event_start, date_start)
        self.assertIn("issue_comment:", workflow)
        self.assertIn("types: [created]", workflow)
        event_block = workflow[event_start:date_start]
        self.assertIn("issues: read", event_block)
        self.assertIn("event-gate", event_block)
        date_block = workflow[date_start:workflow.index("  fixture_tests:")]
        self.assertIn("needs: event_gate", date_block)
        self.assertIn("needs.event_gate.outputs.accepted", date_block)
        self.assertLess(date_start, coverage_start)
        self.assertIn("coverage-body", workflow)
        coverage_block = workflow[coverage_start:workflow.index("  candidate_validation:")]
        self.assertIn("COVERAGE_ISSUE_NUMBER", coverage_block)
        self.assertNotIn("--number \"$CONTROL_ISSUE_NUMBER\"", coverage_block)
        notify_block = workflow[notify_start:workflow.index("  recover:")]
        self.assertIn("needs.event_gate.outputs.accepted == 'true'", notify_block)

    def test_signing_environment_is_limited_to_existing_signing_jobs(self):
        workflow = BUILD_WORKFLOW.read_text()
        signed_start = workflow.index("  build-signed-rc:")
        publish_start = workflow.index("  publish-github-release:")
        signed_block = workflow[signed_start:publish_start]
        publish_block = workflow[publish_start:]
        build_block = workflow[workflow.index("  build-apk:"):signed_start]

        self.assertIn("environment: release-signing", signed_block)
        self.assertIn("environment: release-signing", publish_block)
        self.assertNotIn("environment: release-signing", build_block)

    def test_risk_classification_stays_narrow(self):
        self.assertEqual(classify_paths(["README.md", "docs/MIGRATION.md"]), "docs-only")
        self.assertEqual(classify_paths(["AGENTS.md"]), "unknown/high-risk")
        self.assertEqual(classify_paths(["docs/release.sh"]), "unknown/high-risk")
        self.assertEqual(classify_paths(["app/src/main/AndroidManifest.xml"]), "runtime/high-risk")
        self.assertEqual(classify_paths([".github/workflows/other.yml"]), "build/release-sensitive")

    def test_candidate_identity_uses_full_upstream_sha(self):
        upstream_sha = "a" * 40
        self.assertEqual(
            candidate_branch_name(upstream_sha),
            f"automation/upstream-{upstream_sha}",
        )
        self.assertEqual(candidate_policy([], upstream_sha), "create")
        self.assertEqual(
            candidate_policy(
                [{
                    "headRefName": f"automation/upstream-{upstream_sha}",
                    "state": "OPEN",
                    "headRefOid": "candidate",
                    "headRepository": {"nameWithOwner": "fork/repo"},
                    "baseRefName": "patched",
                }],
                upstream_sha,
                repository="fork/repo",
                candidate_oid="candidate",
            ),
            "already-open",
        )

    def test_candidate_result_exposes_validated_tree(self):
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
            self.assertEqual(result.validated_tree, _git(repo, "rev-parse", "HEAD^{tree}"))

    def test_fork_owned_paths_are_preserved_while_upstream_code_is_retained(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._new_repo(Path(tmp))
            _git(repo, "checkout", "-b", "patched")
            (repo / "README.md").write_text("fork README\nbase footer\n")
            (repo / "update.json").write_text('{"endpoint":"fork"}\n')
            self._commit(repo, "fork identity")
            _git(repo, "checkout", "-b", "upstream", "main")
            (repo / "README.md").write_text("base README\nupstream footer\n")
            (repo / "update.json").write_text('{"endpoint":"base"}\n')
            (repo / "docs.md").write_text("upstream docs\n")
            self._commit(repo, "upstream docs")

            result = merge_candidate(repo, "upstream", "patched")

            self.assertTrue(result.candidate_needed)
            self.assertEqual(result.preserved, ["README.md", "update.json"])
            self.assertIn("docs.md", result.changed_paths)
            self.assertEqual((repo / "README.md").read_text(), "fork README\nbase footer\n")
            self.assertEqual((repo / "update.json").read_text(), '{"endpoint":"fork"}\n')

    def test_fork_owned_control_plane_paths_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._new_repo(Path(tmp))
            _git(repo, "checkout", "-b", "patched")
            (repo / "AGENTS.md").write_text("fork rules\n")
            (repo / ".github/workflows/upstream-monitor.yml").parent.mkdir(parents=True)
            (repo / ".github/workflows/upstream-monitor.yml").write_text("fork workflow\n")
            (repo / "scripts").mkdir()
            (repo / "scripts/upstream_monitor.py").write_text("fork helper\n")
            (repo / "scripts/sync_release_metadata.sh").write_text("fork metadata\n")
            self._commit(repo, "fork control plane")
            _git(repo, "checkout", "-b", "upstream", "main")
            (repo / "AGENTS.md").write_text("upstream rules\n")
            (repo / ".github/workflows").mkdir(parents=True)
            (repo / ".github/workflows/upstream-monitor.yml").write_text("upstream workflow\n")
            (repo / ".github/workflows/new-upstream.yml").write_text("new upstream workflow\n")
            (repo / "scripts").mkdir()
            (repo / "scripts/upstream_monitor.py").write_text("upstream helper\n")
            (repo / "scripts/sync_release_metadata.sh").write_text("upstream metadata\n")
            (repo / "runtime.txt").write_text("upstream runtime\n")
            self._commit(repo, "upstream control plane changes")

            result = merge_candidate(repo, "upstream", "patched")

            self.assertEqual(
                result.preserved,
                [
                    ".github/workflows/new-upstream.yml",
                    ".github/workflows/upstream-monitor.yml",
                    "AGENTS.md",
                    "scripts/sync_release_metadata.sh",
                    "scripts/upstream_monitor.py",
                ],
            )
            self.assertEqual((repo / "AGENTS.md").read_text(), "fork rules\n")
            self.assertEqual(
                (repo / ".github/workflows/upstream-monitor.yml").read_text(),
                "fork workflow\n",
            )
            self.assertEqual((repo / "scripts/upstream_monitor.py").read_text(), "fork helper\n")
            self.assertEqual((repo / "scripts/sync_release_metadata.sh").read_text(), "fork metadata\n")
            self.assertFalse((repo / ".github/workflows/new-upstream.yml").exists())
            self.assertIn("runtime.txt", result.changed_paths)

    def test_only_fork_owned_changes_do_not_need_a_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._new_repo(Path(tmp))
            _git(repo, "checkout", "-b", "patched")
            (repo / "README.md").write_text("fork README\nbase footer\n")
            self._commit(repo, "fork README")
            _git(repo, "checkout", "-b", "upstream", "main")
            (repo / "README.md").write_text("base README\nupstream footer\n")
            self._commit(repo, "upstream README")

            result = merge_candidate(repo, "upstream", "patched")

            self.assertFalse(result.candidate_needed)
            self.assertEqual(result.changed_paths, [])
            self.assertEqual(result.preserved, ["README.md"])

    def test_unsafe_conflict_fails_closed_but_owned_conflict_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._new_repo(Path(tmp))
            _git(repo, "checkout", "-b", "patched")
            (repo / "README.md").write_text("fork README\n")
            (repo / "runtime.txt").write_text("fork runtime\n")
            self._commit(repo, "fork changes")
            _git(repo, "checkout", "-b", "upstream", "main")
            (repo / "README.md").write_text("upstream README\n")
            (repo / "runtime.txt").write_text("upstream runtime\n")
            self._commit(repo, "upstream changes")

            result = merge_candidate(repo, "upstream", "patched")

            self.assertEqual(result.status, "conflict")
            self.assertEqual(result.conflicts, ["runtime.txt"])
            self.assertEqual(result.preserved, ["README.md"])
            self.assertEqual(_git(repo, "status", "--porcelain"), "")

    def test_already_integrated_upstream_has_no_candidate(self):
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

    def test_paginated_pull_request_normalization_preserves_identity_fields(self):
        pages = [[{
            "number": 7,
            "html_url": "https://example.invalid/pr/7",
            "state": "open",
            "head": {"ref": "automation/upstream-x", "sha": "candidate", "repo": {"full_name": "fork/repo"}},
            "base": {"ref": "patched"},
        }], []]

        normalized = normalize_pull_requests(pages)

        self.assertEqual(normalized[0]["state"], "OPEN")
        self.assertEqual(normalized[0]["headRepository"]["nameWithOwner"], "fork/repo")
        self.assertEqual(normalized[0]["baseRefName"], "patched")

    def test_paginated_issue_normalization_excludes_pull_requests(self):
        pages = [[
            {"number": 1, "title": "issue", "body": "body", "state": "open", "html_url": "issue-url"},
            {"number": 2, "title": "pr", "body": "", "state": "open", "pull_request": {}, "html_url": "pr-url"},
        ], [{"number": 3, "title": "closed", "body": None, "state": "closed"}]]

        normalized = normalize_issues(pages)

        self.assertEqual([issue["number"] for issue in normalized], [1, 3])
        self.assertEqual(normalized[1]["body"], "")

    def test_issue_create_reconciles_full_marker_after_ambiguous_create(self):
        marker = issue_marker("no-actionable-delta", "d" * 40)
        with patch("scripts.upstream_monitor.run_gh", side_effect=RuntimeError("timeout")):
            with patch(
                "scripts.upstream_monitor.list_issues",
                return_value=[{"number": 12, "title": "old", "body": marker}],
            ):
                self.assertEqual(
                    create_issue_with_reconcile("fork/repo", "new title", marker + "\nbody"),
                    "12",
                )

    def test_workflow_makes_date_gate_the_first_lightweight_job(self):
        workflow = WORKFLOW.read_text()
        date_start = workflow.index("  date_gate:")
        fixture_start = workflow.index("  fixture_tests:")
        date_block = workflow[date_start:workflow.index("  probe:", date_start)]
        fixture_block = workflow[fixture_start:workflow.index("  probe:", fixture_start)]
        probe_block = workflow[workflow.index("  probe:"):workflow.index("  candidate_validation:")]

        self.assertLess(date_start, fixture_start)
        self.assertNotIn("needs: fixture_tests", date_block)
        self.assertIn("needs: date_gate", fixture_block)
        self.assertIn("fetch-depth: 1", date_block)
        self.assertIn("sparse-checkout:", date_block)
        self.assertIn("anchor:", date_block)
        self.assertIn("forced:", date_block)
        self.assertIn("timezone:", date_block)
        self.assertIn("needs: [date_gate, fixture_tests]", probe_block)

    def test_recover_is_read_only_after_write_paths_finish(self):
        workflow = WORKFLOW.read_text()
        recover = workflow[workflow.index("  recover:"):]
        notify = workflow[workflow.index("  notify:"):workflow.index("  recover:")]
        self.assertIn("contents: read", recover)
        self.assertNotIn("contents: write", recover)
        self.assertIn("persist-credentials: false", recover)
        self.assertNotIn("persist-credentials: true", recover)
        self.assertIn("contents: read", notify)
        self.assertIn("persist-credentials: false", notify)

    def test_schedule_gate_uses_event_cron_and_runner_time(self):
        workflow = WORKFLOW.read_text()
        date_gate = workflow[workflow.index("  date_gate:"):workflow.index("  fixture_tests:")]
        self.assertIn("github.event.schedule", date_gate)
        self.assertIn("github.event_name", date_gate)
        self.assertIn("--schedule", date_gate)
        self.assertIn("--now", date_gate)

    def test_no_actionable_recheck_is_stable_and_main_ahead_is_actionable(self):
        workflow = WORKFLOW.read_text()
        probe = workflow[workflow.index("  probe:"):workflow.index("  candidate_validation:")]
        self.assertIn('"$trusted_helper" probe-state', probe)
        self.assertIn("--preview-candidate-needed", probe)
        self.assertIn("needs.probe.outputs.state == 'actionable-main-ahead'", workflow)

    def test_workflow_binds_validated_tree_before_pr_creation(self):
        workflow = WORKFLOW.read_text()
        self.assertIn("validated_tree", workflow)
        self.assertIn("VALIDATED_TREE", workflow)
        self.assertIn("validated-tree-mismatch", workflow)
        self.assertIn("candidate tree", workflow)
        self.assertIn("candidate-tree:", workflow)

    def test_candidate_jobs_continue_using_a_trusted_helper_copy(self):
        workflow = WORKFLOW.read_text()
        for job in (
            "  probe:",
            "  candidate_validation:",
            "  write_candidate:",
            "  repair_candidate_pr:",
            "  notify:",
            "  recover:",
        ):
            start = workflow.index(job)
            match = re.search(r"\n  [A-Za-z0-9_-]+:", workflow[start + len(job):])
            next_job = -1 if match is None else start + len(job) + match.start()
            block = workflow[start:] if next_job == -1 else workflow[start:next_job]
            self.assertIn('cp scripts/upstream_monitor.py "$trusted_helper"', block, job)
            self.assertIn('python3 "$trusted_helper"', block, job)

    def test_tree_mismatch_and_no_actionable_reason_are_executable_contracts(self):
        self.assertTrue(tree_matches("tree", "tree"))
        self.assertFalse(tree_matches("tree-a", "tree-b"))
        self.assertEqual(
            notification_reason(
                fixture_result="success",
                date_gate_result="success",
                probe_state="no-actionable-delta",
                validation="pass",
                validation_result="success",
                write_result="success",
                repair_result="skipped",
            ),
            "no-actionable-delta",
        )
        self.assertEqual(
            notification_reason(
                fixture_result="skipped",
                date_gate_result="failure",
                probe_state="",
                validation="",
                validation_result="skipped",
                write_result="skipped",
                repair_result="skipped",
            ),
            "date-gate-failure",
        )

    def test_workflow_consolidates_github_api_plumbing_in_helper(self):
        workflow = WORKFLOW.read_text()
        self.assertNotIn("list_open_prs()", workflow)
        self.assertNotIn("list_all_prs()", workflow)
        self.assertNotIn("list_open_issues()", workflow)
        self.assertNotIn("list_issue_comments()", workflow)
        self.assertNotIn("issue_has_marker()", workflow)
        self.assertNotIn("create_issue_with_reconcile()", workflow)
        self.assertIn('"$trusted_helper" list-prs', workflow)
        self.assertIn('"$trusted_helper" list-issues', workflow)
        self.assertIn('"$trusted_helper" create-pr', workflow)
        self.assertIn('"$trusted_helper" issue-comment', workflow)
        self.assertIn('"$trusted_helper" issue-close', workflow)
        self.assertIn('"$trusted_helper" find-issue', workflow)

    def test_no_actionable_updates_have_information_notification_path(self):
        workflow = WORKFLOW.read_text()
        self.assertIn("information-only", workflow)
        self.assertIn("upstream 已更新", workflow)
        self.assertIn("main 已同步", workflow)
        self.assertIn("无需 Merge/发版", workflow)
        self.assertIn("no-actionable-delta", workflow)

    def test_issue_markers_use_full_upstream_identity(self):
        upstream_sha = "b" * 40
        marker = issue_marker("no-actionable-delta", upstream_sha)
        self.assertEqual(marker, f"<!-- tvbox-upstream-monitor:no-actionable-delta:{upstream_sha} -->")
        self.assertEqual(marker_status("body " + marker, [], marker), 0)
        self.assertEqual(marker_status("body", [{"body": marker}], marker), 0)
        self.assertEqual(marker_status("body", [], marker), 1)

    def test_issue_write_reconcile_checks_after_each_ambiguous_attempt(self):
        from scripts.upstream_monitor import comment_issue_idempotent

        with patch("scripts.upstream_monitor.remote_issue_marker_status", side_effect=[1, 0]) as marker:
            with patch("scripts.upstream_monitor.run_gh", side_effect=RuntimeError("timeout")) as run:
                comment_issue_idempotent("fork/repo", 7, "body", "marker")

        self.assertEqual(marker.call_count, 2)
        self.assertEqual(run.call_count, 1)

    def test_recovery_matches_full_sha_marker_not_short_title(self):
        upstream_sha = "c" * 40
        marker = issue_marker("candidate-conflict", upstream_sha)
        issues = [
            {
                "number": 41,
                "title": "[upstream-monitor] candidate-conflict cccccccccccc",
                "body": marker,
            },
            {
                "number": 42,
                "title": "[upstream-monitor] candidate-conflict ccccccc",
                "body": "<!-- tvbox-upstream-monitor:candidate-conflict:ccccccc -->",
            },
        ]
        self.assertEqual(recoverable_issue_numbers(issues, upstream_sha), [41])

        global_marker = issue_marker("probe-error", "global")
        self.assertEqual(
            recoverable_issue_numbers(
                [{
                    "number": 43,
                    "title": "[upstream-monitor] probe-error global",
                    "body": global_marker,
                }],
                upstream_sha,
            ),
            [43],
        )

    def test_gh_runner_uses_argument_list_without_shell_interpolation(self):
        completed = subprocess.CompletedProcess(["gh"], 0, stdout="[]", stderr="")
        with patch("scripts.upstream_monitor.subprocess.run", return_value=completed) as run:
            self.assertEqual(run_gh(["api", "repos/fork/repo/issues"]), "[]")

        command = run.call_args.args[0]
        self.assertEqual(command, ["gh", "api", "repos/fork/repo/issues"])
        self.assertNotIn("shell", run.call_args.kwargs)

    @staticmethod
    def _new_repo(parent):
        repo = parent / "repo"
        repo.mkdir()
        _git(repo, "init", "-b", "main")
        _git(repo, "config", "user.email", "fixture@example.invalid")
        _git(repo, "config", "user.name", "U1 Fixture")
        (repo / "README.md").write_text("base README\n")
        (repo / "update.json").write_text('{"base":true}\n')
        U1aContractTests._commit(repo, "base")
        return repo

    @staticmethod
    def _commit(repo, message):
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", message)


if __name__ == "__main__":
    unittest.main(verbosity=2)
