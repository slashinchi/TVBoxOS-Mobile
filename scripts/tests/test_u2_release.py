import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts import u2_release as u2_release_module
from scripts.u2_release import (
    build_provenance_marker,
    build_release_trailers,
    build_approval_marker,
    parse_approval_marker,
    approval_matches_release,
    candidate_branch_name,
    classify_release_paths,
    canonical_release_baseline,
    cumulative_release_debt,
    debt_manifest,
    derive_integrated_upstream_sha,
    fingerprint_manifest,
    normalize_version_overlay,
    parse_app_version,
    parse_provenance_marker,
    plan_version,
    post_promotion_state,
    prep_commit_spec,
    qualify_u1_merge,
    reconcile_prep,
)


ROOT = Path(__file__).parents[2]
RC_WORKFLOW = ROOT / ".github/workflows/rc-pipeline.yml"
BUILD_WORKFLOW = ROOT / ".github/workflows/build.yml"
CONTROL_WORKFLOW = ROOT / ".github/workflows/rc-control.yml"
DIAGNOSTIC_WORKFLOW = ROOT / ".github/workflows/u2-apk-diagnostic.yml"
CANARY_HARNESS_WORKFLOW = ROOT / ".github/workflows/u2-canary-harness.yml"


class U2ReleaseContractTests(unittest.TestCase):
    def test_apk_diagnostic_is_secret_free_and_reproducible(self):
        self.assertTrue(DIAGNOSTIC_WORKFLOW.is_file())
        workflow = DIAGNOSTIC_WORKFLOW.read_text()
        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("runs-on: ubuntu-24.04", workflow)
        self.assertIn("contents: read", workflow)
        self.assertIn("actions: read", workflow)
        self.assertNotIn("environment:", workflow)
        self.assertIn("33027782081", workflow)
        self.assertIn("artifact-ids:", workflow)
        self.assertIn("apksigcopier extract", workflow)
        self.assertIn("apksigcopier copy", workflow)
        self.assertIn("apksigner verify", workflow)
        self.assertIn("zipalign", workflow)
        self.assertIn("sha256sum", workflow)
        self.assertIn("central directory", workflow)
        self.assertIn("APK Signing Block", workflow)
        self.assertGreaterEqual(workflow.count("set +e"), 5)
        self.assertIn("for entry_key, entry_value in value.items()", workflow)
        self.assertIn("for field, field_value in entry_value.items()", workflow)
        self.assertIn('public_image(original)["entries"]', workflow)
        self.assertIn("diagnostic/reconstructed", workflow)
        self.assertNotIn("path: diagnostic\n", workflow)

    def test_parse_app_version_requires_one_active_pair(self):
        text = "versionCode 236\nversionName '2.1.26'\n"
        self.assertEqual(parse_app_version(text), ("2.1.26", 236))
        with self.assertRaises(ValueError):
            parse_app_version("versionCode 236\nversionName '2.1.26'\nversionName '2.1.27'\n")
        with self.assertRaises(ValueError):
            parse_app_version("// versionCode 236\nversionName '2.1.26'\n")

    def test_normalize_version_overlay_preserves_patched_values_and_upstream_changes(self):
        base = "versionCode 236\nversionName '2.1.26'\nkeep=base\n"
        ours = "versionCode 23601\nversionName '2.1.26.1'\nkeep=base\n"
        theirs = "versionCode 237\nversionName '2.1.27'\nkeep=upstream\nnew=upstream\n"

        merged, upstream_version = normalize_version_overlay(base, ours, theirs)

        self.assertEqual(upstream_version, ("2.1.27", 237))
        self.assertIn("versionCode 23601", merged)
        self.assertIn("versionName '2.1.26.1'", merged)
        self.assertIn("keep=upstream", merged)
        self.assertIn("new=upstream", merged)

    def test_provenance_marker_round_trips_exact_fields(self):
        marker = build_provenance_marker(
            "a" * 40,
            "b" * 40,
            "c" * 40,
            "d" * 40,
            "2.1.27",
            237,
        )
        self.assertEqual(
            parse_provenance_marker(marker),
            {
                "upstream": "a" * 40,
                "candidate": "b" * 40,
                "tree": "c" * 40,
                "forkMain": "d" * 40,
                "upstreamVersion": "2.1.27",
                "upstreamCode": "237",
            },
        )
        with self.assertRaises(ValueError):
            parse_provenance_marker(marker.replace("tree=" + "c" * 40, "tree=short"))
        with self.assertRaises(ValueError):
            parse_provenance_marker(marker.replace(" forkMain=" + "d" * 40, ""))

    def test_strict_u1_merge_requires_pr_lineage_and_replay(self):
        upstream = "a" * 40
        candidate = "b" * 40
        tree = "c" * 40
        before = "d" * 40
        after = "e" * 40
        marker = build_provenance_marker(upstream, candidate, tree, upstream, "2.1.27", 237)
        pr = {
            "number": 7,
            "state": "closed",
            "merged_at": "2026-08-28T00:00:00Z",
            "base": "patched",
            "merged_by": "slashinchi",
            "author": "github-actions[bot]",
            "head_repository": "slashinchi/TVBoxOS-Mobile",
            "head": candidate_branch_name(upstream),
            "head_sha": candidate,
            "merge_commit_sha": after,
        }
        replay = {
            "status": "clean",
            "candidate_needed": True,
            "before": before,
            "source_after": after,
            "source_parents": [before, candidate],
            "candidate": candidate,
            "candidate_parents": [before, upstream],
            "upstream": upstream,
            "upstream_repository": "kukuqi666/TVBoxOS-Mobile",
            "upstream_ref": "refs/heads/main",
            "fork_main": upstream,
            "marker_fork_main": upstream,
            "fork_main_is_ancestor": True,
            "marker_tree": tree,
            "candidate_tree": tree,
            "rebuilt_tree": tree,
            "source_tree": tree,
        }

        qualified = qualify_u1_merge(
            before=before,
            after=after,
            parents=[before, candidate],
            push_actor="slashinchi",
            pr=pr,
            repository="slashinchi/TVBoxOS-Mobile",
            upstream_sha=upstream,
            marker=marker,
            candidate_tree=tree,
            upstream_is_ancestor=True,
            upstream_version="2.1.27",
            upstream_code=237,
            replay=replay,
        )

        self.assertTrue(qualified["qualified"])
        wrong_marker = build_provenance_marker(upstream, candidate, tree, "f" * 40, "2.1.27", 237)
        wrong = qualify_u1_merge(
            before=before,
            after=after,
            parents=[before, candidate],
            push_actor="slashinchi",
            pr=pr,
            repository="slashinchi/TVBoxOS-Mobile",
            upstream_sha=upstream,
            marker=wrong_marker,
            candidate_tree=tree,
            upstream_is_ancestor=True,
            upstream_version="2.1.27",
            upstream_code=237,
            replay=replay,
        )
        self.assertEqual(wrong["reason"], "provenance-fork-main-mismatch")
        pr["author"] = "human"
        self.assertEqual(
            qualify_u1_merge(
                before=before,
                after=after,
                parents=[before, candidate],
                push_actor="slashinchi",
                pr=pr,
                repository="slashinchi/TVBoxOS-Mobile",
                upstream_sha=upstream,
                marker=marker,
                candidate_tree=tree,
                upstream_is_ancestor=True,
                upstream_version="2.1.27",
                upstream_code=237,
                replay=replay,
            )["reason"],
            "associated-pr-mismatch",
        )

    def _replay_evidence(self):
        return {
            "status": "clean",
            "candidate_needed": True,
            "before": "a" * 40,
            "source_after": "b" * 40,
            "source_parents": ["a" * 40, "c" * 40],
            "candidate": "c" * 40,
            "candidate_parents": ["a" * 40, "d" * 40],
            "upstream": "d" * 40,
            "upstream_repository": "kukuqi666/TVBoxOS-Mobile",
            "upstream_ref": "refs/heads/main",
            "fork_main": "e" * 40,
            "marker_fork_main": "e" * 40,
            "fork_main_is_ancestor": True,
            "marker_tree": "f" * 40,
            "candidate_tree": "f" * 40,
            "rebuilt_tree": "f" * 40,
            "source_tree": "f" * 40,
        }

    def _assert_replay_rejected(self, evidence, reason):
        validator = getattr(u2_release_module, "validate_replay_evidence", None)
        self.assertIsNotNone(validator)
        self.assertEqual(
            validator(
                evidence,
                "kukuqi666/TVBoxOS-Mobile",
                "refs/heads/main",
            )["reason"],
            reason,
        )

    def test_strict_replay_requires_direct_parent_and_four_tree_proof(self):
        valid = self._replay_evidence()
        validator = getattr(u2_release_module, "validate_replay_evidence", None)
        self.assertIsNotNone(validator)
        self.assertTrue(
            validator(valid, "kukuqi666/TVBoxOS-Mobile", "refs/heads/main")["qualified"]
        )

        invalid = dict(valid, source_parents=[valid["before"], "1" * 40])
        self._assert_replay_rejected(invalid, "replay-source-parent-mismatch")
        invalid = dict(valid, candidate_parents=[valid["before"], "2" * 40])
        self._assert_replay_rejected(invalid, "replay-candidate-parent-mismatch")
        invalid = dict(valid, upstream_repository="attacker.example/repo")
        self._assert_replay_rejected(invalid, "replay-upstream-source-mismatch")
        invalid = dict(valid, upstream_ref="refs/heads/feature")
        self._assert_replay_rejected(invalid, "replay-upstream-source-mismatch")
        invalid = dict(valid, rebuilt_tree="3" * 40)
        self._assert_replay_rejected(invalid, "replay-tree-mismatch")
        invalid = dict(valid, fork_main_is_ancestor=False)
        self._assert_replay_rejected(invalid, "replay-fork-main-not-ancestor")
        invalid = dict(valid, candidate_needed=False)
        self._assert_replay_rejected(invalid, "replay-candidate-not-built")
        invalid = dict(valid, marker_fork_main="0" * 40)
        self._assert_replay_rejected(invalid, "replay-fork-main-mismatch")

        marker = build_provenance_marker(
            valid["upstream"], valid["candidate"], valid["marker_tree"], "0" * 40, "2.1.27", 237
        )
        pr = {
            "number": 7,
            "state": "closed",
            "merged_at": "2026-08-28T00:00:00Z",
            "base": "patched",
            "merged_by": "slashinchi",
            "author": "github-actions[bot]",
            "head_repository": "slashinchi/TVBoxOS-Mobile",
            "head": candidate_branch_name(valid["upstream"]),
            "head_sha": valid["candidate"],
            "merge_commit_sha": valid["source_after"],
        }
        result = qualify_u1_merge(
            before=valid["before"],
            after=valid["source_after"],
            parents=valid["source_parents"],
            push_actor="slashinchi",
            pr=pr,
            repository="slashinchi/TVBoxOS-Mobile",
            upstream_sha=valid["upstream"],
            marker=marker,
            candidate_tree=valid["marker_tree"],
            upstream_is_ancestor=True,
            upstream_version="2.1.27",
            upstream_code=237,
            replay=valid,
        )
        self.assertEqual(result["reason"], "provenance-fork-main-mismatch")

    def test_strict_qualifier_rejects_legacy_replay_tuple(self):
        evidence = self._replay_evidence()
        marker = build_provenance_marker(
            evidence["upstream"], evidence["candidate"], evidence["marker_tree"], evidence["upstream"], "2.1.27", 237
        )
        pr = {
            "number": 7,
            "state": "closed",
            "merged_at": "2026-08-28T00:00:00Z",
            "base": "patched",
            "merged_by": "slashinchi",
            "author": "github-actions[bot]",
            "head_repository": "slashinchi/TVBoxOS-Mobile",
            "head": candidate_branch_name(evidence["upstream"]),
            "head_sha": evidence["candidate"],
            "merge_commit_sha": evidence["source_after"],
        }
        result = qualify_u1_merge(
            before=evidence["before"],
            after=evidence["source_after"],
            parents=evidence["source_parents"],
            push_actor="slashinchi",
            pr=pr,
            repository="slashinchi/TVBoxOS-Mobile",
            upstream_sha=evidence["upstream"],
            marker=marker,
            candidate_tree=evidence["marker_tree"],
            upstream_is_ancestor=True,
            upstream_version="2.1.27",
            upstream_code=237,
            replay=("clean", evidence["marker_tree"], evidence["marker_tree"]),
        )
        self.assertEqual(result["reason"], "replay-evidence-required")

    def test_u1_marker_version_must_match_fixed_upstream_object(self):
        evidence = self._replay_evidence()
        marker = build_provenance_marker(
            evidence["upstream"], evidence["candidate"], evidence["marker_tree"], evidence["upstream"], "99.99.99", 9999
        )
        pr = {
            "number": 7,
            "state": "closed",
            "merged_at": "2026-08-28T00:00:00Z",
            "base": "patched",
            "merged_by": "slashinchi",
            "author": "github-actions[bot]",
            "head_repository": "slashinchi/TVBoxOS-Mobile",
            "head": candidate_branch_name(evidence["upstream"]),
            "head_sha": evidence["candidate"],
            "merge_commit_sha": evidence["source_after"],
        }
        result = qualify_u1_merge(
            before=evidence["before"],
            after=evidence["source_after"],
            parents=evidence["source_parents"],
            push_actor="slashinchi",
            pr=pr,
            repository="slashinchi/TVBoxOS-Mobile",
            upstream_sha=evidence["upstream"],
            marker=marker,
            candidate_tree=evidence["marker_tree"],
            upstream_is_ancestor=True,
            upstream_version="2.1.27",
            upstream_code=237,
            replay=evidence,
        )
        self.assertEqual(result["reason"], "provenance-version-mismatch")

    def test_manual_integrated_upstream_and_canonical_release_baseline_fail_closed(self):
        sha = "a" * 40
        self.assertEqual(derive_integrated_upstream_sha([sha], {sha}, {sha}), sha)
        with self.assertRaises(ValueError):
            derive_integrated_upstream_sha([sha, "b" * 40], {sha, "b" * 40}, {sha, "b" * 40})
        with self.assertRaises(ValueError):
            canonical_release_baseline(["malformed-ledger-entry"])
        release = {
            "tag": "v2.1.26.1",
            "target": "c" * 40,
            "versionName": "2.1.26.1",
            "versionCode": 23601,
            "assetSha256": "d" * 64,
            "signerSha256": "e" * 64,
            "verified": True,
            "tag_ancestor": True,
        }
        self.assertEqual(canonical_release_baseline([release])['tag'], "v2.1.26.1")
        with self.assertRaises(ValueError):
            canonical_release_baseline([release], update_version="2.1.27.1")
        with self.assertRaises(ValueError):
            canonical_release_baseline([release], update_version="2.1.26")
        self.assertEqual(
            canonical_release_baseline([release], update_version="2.1.26", delivery_hold=True)['tag'],
            "v2.1.26.1",
        )
        newer = dict(
            release,
            tag="v2.1.27.1",
            target="f" * 40,
            versionName="2.1.27.1",
            versionCode=23701,
            assetSha256="a" * 64,
        )
        with self.assertRaises(ValueError):
            canonical_release_baseline([newer, release])
        for version_code in (23601.0, "23601", True):
            with self.subTest(version_code=version_code):
                with self.assertRaises(ValueError):
                    canonical_release_baseline([dict(release, versionCode=version_code)])

    def test_canonical_release_baseline_matches_strict_ledger_shapes_and_production_legacy(self):
        production = json.loads((ROOT / "gradle/verified-releases.json").read_text())
        baseline = canonical_release_baseline(production)
        self.assertEqual(baseline["tag"], "v2.1.26.1")

        complete = dict(
            production[0],
            tag="v2.1.27.1",
            versionName="2.1.27.1",
            versionCode=23701,
            target="a" * 40,
            updateSha256="b" * 64,
            sourceSha="c" * 40,
            debt="d" * 64,
            runId="123456",
            runAttempt="1",
        )
        self.assertEqual(canonical_release_baseline([complete])["tag"], "v2.1.27.1")

        with self.assertRaises(ValueError):
            canonical_release_baseline([dict(production[0], unexpected="field")])
        duplicate_target = dict(
            production[0],
            tag="v2.1.27.1",
            versionName="2.1.27.1",
            versionCode=23701,
        )
        with self.assertRaises(ValueError):
            canonical_release_baseline([production[0], duplicate_target])
        with self.assertRaises(ValueError):
            canonical_release_baseline([dict(complete, updateSha256="invalid")])
        legacy_after_complete = dict(
            production[0],
            tag="v2.1.28.1",
            versionName="2.1.28.1",
            versionCode=23801,
            target="e" * 40,
        )
        with self.assertRaises(ValueError):
            canonical_release_baseline([complete, legacy_after_complete])

    def test_delivery_hold_is_identity_bound_not_boolean(self):
        release = {
            "tag": "v2.1.26.1",
            "target": "c" * 40,
            "versionName": "2.1.26.1",
            "versionCode": 23601,
            "assetSha256": "d" * 64,
            "signerSha256": "e" * 64,
            "verified": True,
            "tag_ancestor": True,
        }
        from scripts.u2_release import hold_covers_lag, HOLD_RELEASE_TAG_RE

        hold = {"release_tag": "v2.1.26.1", "release_target": "c" * 40, "issue": 3}
        self.assertTrue(hold_covers_lag(hold, release, lag_version="2.1.26"))
        other = {"release_tag": "v2.1.27.1", "release_target": "f" * 40, "issue": 4}
        self.assertFalse(hold_covers_lag(other, release, lag_version="2.1.26"))
        with self.assertRaises(ValueError):
            hold_covers_lag({"release_tag": "nope", "release_target": "c" * 40, "issue": 3}, release, "2.1.26")
        self.assertTrue(HOLD_RELEASE_TAG_RE.fullmatch("v2.1.26.1"))
        self.assertFalse(HOLD_RELEASE_TAG_RE.fullmatch("v2.1.26"))
        self.assertFalse(HOLD_RELEASE_TAG_RE.fullmatch("nope"))

    def test_prep_reconcile_and_post_promotion_are_identity_bound(self):
        parent = "a" * 40
        debt = "b" * 64
        trailers = build_release_trailers(parent, "manual-local", "c" * 40, "2.1.27.1", debt, version_code=23701)
        spec = prep_commit_spec(parent, ["app/build.gradle"], trailers, "2.1.27.1", 23701, debt)
        expected = {**spec, "mode": "manual-local", "upstream": "c" * 40}
        self.assertEqual(reconcile_prep(expected, expected)["action"], "reuse")
        changed = {**expected, "debt": "f" * 64}
        self.assertEqual(reconcile_prep(changed, expected)["action"], "fail")
        self.assertEqual(post_promotion_state(parent, parent, False, "published"), "published-at-release")
        self.assertEqual(post_promotion_state("d" * 40, parent, True, "published"), "published-recovery-forward")
        self.assertEqual(post_promotion_state("d" * 40, parent, False, "pending"), "pre-promotion-stale")
        self.assertEqual(post_promotion_state(parent, parent, False, "draft"), "draft-recovery-continue")
        self.assertEqual(post_promotion_state("d" * 40, parent, True, "draft"), "draft-recovery-continue")
        self.assertEqual(post_promotion_state("d" * 40, parent, False, "draft"), "draft-stale")

    def test_debt_manifest_includes_mode_type_oid_and_tombstone(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            self._git(repo, "init", "-b", "main")
            self._git(repo, "config", "user.name", "U2 test")
            self._git(repo, "config", "user.email", "u2@example.invalid")
            (repo / "runtime.txt").write_text("one\n")
            (repo / "docs.md").write_text("docs\n")
            self._git(repo, "add", ".")
            self._git(repo, "commit", "-m", "base")
            baseline = self._git(repo, "rev-parse", "HEAD")
            (repo / "runtime.txt").write_text("two\n")
            (repo / "docs.md").unlink()
            (repo / "link").symlink_to("runtime.txt")
            self._git(repo, "add", "-A")
            self._git(repo, "commit", "-m", "release debt")
            current = self._git(repo, "rev-parse", "HEAD")

            entries = debt_manifest(repo, baseline, current, exclusions={"docs.md"})
            encoded = json.dumps(entries, sort_keys=True)

            self.assertIn("runtime.txt", encoded)
            self.assertIn("link", encoded)
            self.assertNotIn("docs.md", encoded)
            self.assertTrue(all("mode" in item and "type" in item and "oid" in item for item in entries))
            self.assertEqual(len(fingerprint_manifest(entries)), 64)
            debt = cumulative_release_debt(repo, baseline, current, exclusions={"docs.md"})
            self.assertEqual(debt["classification"], "unknown/high-risk")
            self.assertEqual(debt["fingerprint"], fingerprint_manifest(entries))

    def test_debt_manifest_exclusions_support_control_plane_prefixes(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            self._git(repo, "init", "-b", "main")
            self._git(repo, "config", "user.name", "U2 test")
            self._git(repo, "config", "user.email", "u2@example.invalid")
            (repo / "scripts").mkdir()
            (repo / "scripts/helper.py").write_text("one\n")
            (repo / "runtime.txt").write_text("one\n")
            self._git(repo, "add", ".")
            self._git(repo, "commit", "-m", "base")
            baseline = self._git(repo, "rev-parse", "HEAD")
            (repo / "scripts/helper.py").write_text("two\n")
            (repo / "runtime.txt").write_text("two\n")
            self._git(repo, "add", ".")
            self._git(repo, "commit", "-m", "change")
            current = self._git(repo, "rev-parse", "HEAD")

            entries = debt_manifest(repo, baseline, current, exclusions={"scripts/"})

            self.assertEqual([item["path"] for item in entries], ["runtime.txt"])

    def test_release_path_classification_checks_gradle_before_app_runtime(self):
        self.assertEqual(classify_release_paths(["app/build.gradle"]), "build/release-sensitive")
        self.assertEqual(classify_release_paths(["app/src/main/Foo.kt"]), "runtime/high-risk")
        self.assertEqual(classify_release_paths(["docs/release.md"]), "docs-only")
        self.assertEqual(classify_release_paths([".github/workflows/u2.yml"]), "build/release-sensitive")

    def test_plan_version_is_monotonic_and_bounded(self):
        planned = plan_version(
            "2.1.27",
            237,
            published=[("2.1.26.1", 23601), ("2.1.27.1", 23701)],
        )
        self.assertEqual(planned, {"versionName": "2.1.27.2", "versionCode": 23702, "revision": 2})
        with self.assertRaises(ValueError):
            plan_version("2.1.25", 235, published=[("2.1.26.1", 23601)])

    def test_canonical_runtime_dependencies_select_sorted_gavs(self):
        text = """releaseRuntimeClasspath - Runtime classpath of source set 'main'.
+--- com.example:zeta:1.0
|    +--- com.example:alpha:1.0 -> 1.1
|    +--- com.example:alpha:1.1
\\--- com.example:zeta:1.0
"""
        result = subprocess.run(
            [
                "python3",
                "scripts/u2_release.py",
                "canonical-runtime-dependencies",
                "--file",
                "/dev/stdin",
                "--configuration",
                "releaseRuntimeClasspath",
            ],
            cwd=ROOT,
            input=text,
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout),
            {
                "components": [
                    {"group": "com.example", "module": "alpha", "version": "1.1"},
                    {"group": "com.example", "module": "zeta", "version": "1.0"},
                ],
                "configuration": "releaseRuntimeClasspath",
                "schema": "tvbox-runtime-dependencies-v1",
            },
        )

    def test_release_trailers_are_parseable_and_mode_aware(self):
        trailers = build_release_trailers(
            source_sha="a" * 40,
            mode="manual-local",
            upstream_sha="b" * 40,
            version_name="2.1.27.1",
            debt="c" * 64,
            pr_number=None,
        )
        self.assertIn("TVBox-U2-Mode: manual-local", trailers)
        self.assertNotIn("TVBox-U2-PR:", trailers)

    def test_approval_marker_is_exact_and_bound_to_run_attempt(self):
        marker = build_approval_marker(
            release_sha="a" * 40,
            debt="b" * 64,
            version="2.1.27.1",
            apk_sha="c" * 64,
            run="123456",
            attempt=1,
        )
        self.assertEqual(
            parse_approval_marker(marker),
            {
                "release": "a" * 40,
                "debt": "b" * 64,
                "version": "2.1.27.1",
                "apk": "c" * 64,
                "run": "123456",
                "attempt": "1",
            },
        )
        with self.assertRaises(ValueError):
            parse_approval_marker(marker.replace("run=123456", "run=short"))
        with self.assertRaises(ValueError):
            parse_approval_marker(marker.replace("attempt=1", "attempt="))
        with self.assertRaises(ValueError):
            build_approval_marker("a" * 39, "b" * 64, "2.1.27.1", "c" * 64, "123456", 1)

    def test_approval_marker_embedded_in_prose_or_fences_still_parses(self):
        marker = build_approval_marker(
            release_sha="a" * 40,
            debt="b" * 64,
            version="2.1.27.1",
            apk_sha="c" * 64,
            run="123456",
            attempt=1,
        )
        self.assertEqual(parse_approval_marker(f"Approved.\n\n{marker}")["run"], "123456")
        self.assertEqual(parse_approval_marker(f"```text\n{marker}\n```")["attempt"], "1")
        self.assertEqual(parse_approval_marker(f"  {marker}  \nnotes")["version"], "2.1.27.1")
        # a malformed marker (not matching the exact grammar) still fails
        with self.assertRaises(ValueError):
            parse_approval_marker(f"Approved {marker.replace('run=123456', 'run=short')}")

    def test_approval_matches_only_identical_release_identity(self):
        marker = build_approval_marker(
            release_sha="a" * 40,
            debt="b" * 64,
            version="2.1.27.1",
            apk_sha="c" * 64,
            run="123456",
            attempt=1,
        )
        release = {
            "release_sha": "a" * 40,
            "debt": "b" * 64,
            "version": "2.1.27.1",
            "apk_sha": "c" * 64,
            "run": "123456",
            "attempt": 1,
        }
        self.assertTrue(approval_matches_release(marker, release))
        for field in ("debt", "apk_sha", "release_sha", "version"):
            changed = dict(release)
            if field == "debt":
                changed["debt"] = "f" * 64
            elif field == "apk_sha":
                changed["apk_sha"] = "f" * 64
            elif field == "release_sha":
                changed["release_sha"] = "f" * 40
            else:
                changed["version"] = "2.1.27.2"
            self.assertFalse(approval_matches_release(marker, changed))
        self.assertFalse(approval_matches_release(marker, {**release, "attempt": 2}))
        self.assertFalse(approval_matches_release(marker, {**release, "run": "999999"}))

    def test_rc_workflow_is_reusable_and_separates_trust_domains(self):
        workflow = RC_WORKFLOW.read_text()
        self.assertIn("workflow_call:", workflow)
        self.assertNotIn("workflow_dispatch:", workflow)
        self.assertIn("build_unsigned:", workflow)
        self.assertIn("prepare_sign_input:", workflow)
        self.assertIn("sign_exact:", workflow)
        self.assertIn("verify_signed:", workflow)
        self.assertIn("attest_signed:", workflow)
        self.assertIn("environment: release-signing", workflow)
        builder = workflow[workflow.index("  build_unsigned:"):workflow.index("  prepare_sign_input:")]
        preflight = workflow[workflow.index("  prepare_sign_input:"):workflow.index("  sign_exact:")]
        signer = workflow[workflow.index("  sign_exact:"):workflow.index("  verify_signed:")]
        verifier = workflow[workflow.index("  verify_signed:"):workflow.index("  attest_signed:")]
        attestor = workflow[workflow.index("  attest_signed:"):]
        self.assertNotIn("release-signing", builder)
        self.assertNotIn("secrets.", builder)
        self.assertNotIn("actions/checkout", signer)
        self.assertNotIn("./gradlew", signer)
        self.assertNotIn("id-token: write", signer)
        self.assertNotIn("attestations: write", signer)
        self.assertNotIn("release-signing", preflight)
        self.assertNotIn("secrets.", preflight)
        self.assertNotIn("id-token: write", preflight)
        self.assertNotIn("attestations: write", preflight)
        self.assertNotIn("sudo apt-get", preflight)
        self.assertNotIn("setup-java", preflight)
        self.assertNotIn("ANDROID_HOME", preflight)
        self.assertLess(signer.index("Validate sign input and rehash actual APK before secret window"), signer.index("Sign exact APK with the only secret-bearing step"))
        self.assertIn("sha256sum \"$root/unsigned.apk\"", signer)
        self.assertIn("TVBOX_KEY_PASSWORD: ${{ secrets.TVBOX_KEY_PASSWORD }}", signer)
        self.assertNotIn("release-signing", verifier)
        self.assertNotIn("secrets.", verifier)
        self.assertNotIn("id-token: write", verifier)
        self.assertNotIn("attestations: write", verifier)
        self.assertNotIn("actions/checkout", attestor)
        self.assertNotIn("sudo apt-get", attestor)
        self.assertNotIn("./gradlew", attestor)
        self.assertNotIn("secrets.", attestor)
        self.assertNotIn("release-signing", attestor)
        self.assertIn("id-token: write", attestor)
        self.assertIn("attestations: write", attestor)
        self.assertIn("verify_signed.outputs.signed_sha256", attestor)

    def test_rc_control_workflow_is_dispatch_gated_and_sha_locked(self):
        self.assertTrue(CONTROL_WORKFLOW.is_file())
        workflow = CONTROL_WORKFLOW.read_text()
        self.assertIn("workflow_dispatch:", workflow)
        self.assertNotIn("workflow_call:", workflow)
        self.assertIn("refs/tags/rc-control-v1", workflow)
        self.assertIn("github.actor == 'slashinchi'", workflow)
        self.assertIn("refs/heads/patched", workflow)
        self.assertNotIn("release-signing", workflow)
        self.assertNotIn("${{ secrets", workflow)
        self.assertIn("uses: ./.github/workflows/rc-pipeline.yml", workflow)
        resolve = self._job_block(workflow, "resolve")
        self.assertIn("actions/github-script", resolve)
        self.assertIn("getCommit", resolve)
        self.assertIn("hex", resolve)
        call = self._job_block(workflow, "call_rc_pipeline")
        self.assertIn("secrets: inherit", call)
        self.assertIn("needs.resolve.outputs.patched_sha", call)
        self.assertIn("source_sha: ${{ needs.resolve.outputs.patched_sha }}", call)
        self.assertIn("release_sha: ${{ needs.resolve.outputs.patched_sha }}", call)
        self.assertIn("mode: manual-local", call)
        outer = workflow[: workflow.index("jobs:")]
        self.assertIn("contents: read", outer)
        self.assertNotIn("id-token: write", outer)
        self.assertNotIn("attestations: write", outer)

    def test_build_workflow_has_no_signing_entry_and_no_tag_publisher(self):
        workflow = BUILD_WORKFLOW.read_text()
        self.assertNotIn("build-signed-rc", workflow)
        self.assertNotIn("publish-github-release", workflow)
        self.assertNotIn("release-signing", workflow)
        self.assertNotIn("rc-pipeline", workflow)
        self.assertNotIn('tags: ["v*"]', workflow)
        self.assertNotIn("workflow_dispatch", workflow)
        self.assertIn("build-apk:", workflow)

    def test_gradle_actions_path_is_https_only_and_jitpack_filtered(self):
        build = (ROOT / "build.gradle").read_text()
        actions_blocks = re.findall(
            r'if \(System\.getenv\("GITHUB_ACTIONS"\) == "true"\) \{(.*?)\n\s*\} else \{',
            build,
            re.DOTALL,
        )
        self.assertEqual(len(actions_blocks), 2)
        for block in actions_blocks:
            self.assertNotIn("maven.aliyun.com", block)
            self.assertNotIn("4thline.org", block)
            self.assertIn('url "https://jitpack.io"', block)
            self.assertIn('includeGroupByRegex "com\\\\.github\\\\..*"', block)

    def test_actions_use_only_the_local_pinned_legacy_bridge(self):
        build = (ROOT / "build.gradle").read_text()
        self.assertIn('TVBOX_LEGACY_REPO', build)
        self.assertIn('url = uri(tvboxLegacyRepo)', build)
        self.assertIn('mavenPom()', build)
        self.assertIn('artifact()', build)
        for coordinate in (
            'includeVersion("com.kingja.loadsir", "loadsir", "1.3.8")',
            'includeVersion("com.lzy.net", "okgo", "3.0.4")',
            'includeVersion("com.owen", "tv-recyclerview", "3.0.0")',
            'includeVersion("com.hyman", "flowlayout-lib", "1.1.2")',
        ):
            self.assertIn(coordinate, build)
        for path in (
            ROOT / ".github/workflows/build.yml",
            ROOT / ".github/workflows/rc-pipeline.yml",
            ROOT / ".github/workflows/upstream-monitor.yml",
        ):
            workflow = path.read_text()
            if path == RC_WORKFLOW:
                self.assertIn("scripts/u2_build_evidence.sh", workflow)
            else:
                self.assertIn("scripts/legacy_staging.py stage", workflow)
                self.assertIn("gradle/legacy-dependencies.lock.json", workflow)
            self.assertNotIn("maven.aliyun.com", workflow)

    def test_rc_pipeline_attests_v2_build_inputs_and_pins_signer_jdk(self):
        workflow = RC_WORKFLOW.read_text()
        self.assertIn('schema:"tvbox-release-identity-v2"', workflow)
        self.assertIn("runtime_components_sha256", workflow)
        self.assertIn("legacy_manifest_sha256", workflow)
        self.assertIn("apksigner_version", workflow)
        self.assertIn("zipalign_version", workflow)
        self.assertIn("tvbox-release-identity/v2", workflow)
        signer = workflow[workflow.index("  sign_exact:"):workflow.index("  verify_signed:")]
        self.assertIn("actions/setup-java@b6effb05e454b25005698d916606bdc6ffcbf961", signer)
        self.assertIn("java-version: '17.0.20+8'", signer)
        self.assertNotIn("cache:", signer)

    def test_rc_builder_uses_a_fresh_cache_disabled_gradle_home(self):
        workflow = RC_WORKFLOW.read_text()
        recipe = (ROOT / "scripts/u2_build_evidence.sh").read_text()
        self.assertIn('export GRADLE_USER_HOME="$RUNNER_TEMP/tvbox-gradle"', recipe)
        for helper in ("legacy_staging.py", "u2_release.py", "native_compat.py"):
            self.assertIn(f'"$control_scripts/{helper}"', recipe)
        self.assertNotIn("python3 scripts/legacy_staging.py", recipe)
        self.assertNotIn("python3 scripts/u2_release.py", recipe)
        self.assertNotIn("python3 scripts/native_compat.py", recipe)
        self.assertIn("U2_BUILDER_REEXEC", recipe)
        self.assertIn("verify_trusted_helpers", recipe)
        builder = workflow[workflow.index("  build_unsigned:"):workflow.index("  prepare_sign_input:")]
        self.assertIn("scripts/u2_build_evidence.sh", builder)
        self.assertNotIn("cache: gradle", builder)
        self.assertNotIn("setup-gradle", builder)

    def test_rc_builder_reexecs_from_immutable_helper_snapshot_after_gradle(self):
        recipe = (ROOT / "scripts/u2_build_evidence.sh").read_text()
        self.assertIn("U2_BUILDER_PHASE", recipe)
        self.assertIn("U2_TRUSTED_RECIPE_B64", recipe)
        initial_stage = recipe[recipe.index('if [[ "$reexec" == "0" ]]'):recipe.index("control_scripts=")]
        self.assertIn('U2_TRUSTED_RECIPE_B64="$trusted_recipe_b64"', initial_stage)
        self.assertIn("U2_BUILDER_PHASE=post-build", recipe)
        self.assertIn("base64 --decode", recipe)
        self.assertIn("chmod -R a-w,u+w", recipe)
        self.assertIn('bash "$post_build_root/scripts/u2_build_evidence.sh" "$@"', recipe)

    def test_rc_builder_reexec_is_bound_and_dependencies_cannot_mutate_evidence(self):
        recipe = (ROOT / "scripts/u2_build_evidence.sh").read_text()
        self.assertNotIn('CONTROL_WORKFLOW_SOURCE_ROOT:-', recipe)
        self.assertIn('case "$reexec" in', recipe)
        self.assertIn("run_assemble_and_reexec", recipe)
        self.assertIn("run_dependencies_and_reexec", recipe)
        self.assertIn("U2_SKIP_DEPENDENCIES", recipe)
        self.assertIn("U2_STATE_RAW_DEPENDENCY_SHA", recipe)
        self.assertIn("U2_STATE_ASSEMBLE_APK_SHA", recipe)
        self.assertIn("legacy manifest changed during build", recipe)
        self.assertLess(
            recipe.index("./gradlew :app:assembleRelease"),
            recipe.index('run_assemble_and_reexec "$@"'),
        )
        self.assertLess(
            recipe.index("./gradlew :app:dependencies"),
            recipe.index('run_dependencies_and_reexec "$@"'),
        )
        self.assertIn('[[ "$apk_after_dependencies" == "$apk_before_dependencies" &&', recipe)
        self.assertIn('"$source_apk_after_dependencies" == "$source_apk_before_dependencies"', recipe)
        self.assertIn("write_identity", recipe)

    def test_rc_artifact_contracts_are_flat_and_exact(self):
        workflow = RC_WORKFLOW.read_text()
        self.assertIn("tvbox-u2-build-evidence-", workflow)
        self.assertIn("tvbox-u2-sign-input-", workflow)
        self.assertIn("tvbox-u2-signed-output-", workflow)
        self.assertIn("tvbox-u2-attest-input-", workflow)
        builder = workflow[workflow.index("  build_unsigned:"):workflow.index("  prepare_sign_input:")]
        recipe = (ROOT / "scripts/u2_build_evidence.sh").read_text()
        self.assertIn("build/evidence", builder)
        self.assertIn("legacy-dependencies.lock.json", recipe)
        self.assertIn("build-identity.json", recipe)
        self.assertNotIn("tvbox-u2-unsigned-", builder)
        self.assertIn("-delete", recipe)
        self.assertIn("exactly 6 files", recipe)
        preflight = workflow[workflow.index("  prepare_sign_input:"):workflow.index("  sign_exact:")]
        self.assertIn("expected_files=", preflight)
        self.assertIn("sha256sum \"$root/unsigned.apk\"", preflight)
        self.assertIn("actual_count", preflight)
        self.assertIn("sign-input", preflight)
        signer = workflow[workflow.index("  sign_exact:"):workflow.index("  verify_signed:")]
        self.assertIn("signer-result.json", signer)
        self.assertNotIn("builder-release-identity.txt", signer)
        signer_upload = signer[signer.index("      - name: Upload exact signed output"):]
        self.assertNotIn("signer-output.txt", signer_upload)
        verifier = workflow[workflow.index("  verify_signed:"):workflow.index("  attest_signed:")]
        self.assertIn("control-workflow/scripts/apk_equivalence.py", verifier)
        self.assertIn("tvbox-apk-equivalence-v1", verifier)
        self.assertIn("release-identity-predicate.json", verifier)
        self.assertIn("tvbox-u2-attest-input-", verifier)
        self.assertIn("exactly 2 files", verifier)
        attestor = workflow[workflow.index("  attest_signed:"):]
        self.assertIn("attest-input", attestor)
        self.assertNotIn("Write final release identity predicate", attestor)
        self.assertNotIn("release-identity.txt", attestor)

    def test_rc_attestor_has_no_checkout_or_scripts(self):
        workflow = RC_WORKFLOW.read_text()
        attestor = workflow[workflow.index("  attest_signed:"):]
        self.assertNotIn("actions/checkout", attestor)
        self.assertNotIn("scripts/native_compat.py", attestor)
        self.assertNotIn("scripts/u2_release.py", attestor)
        self.assertNotIn("sudo apt-get", attestor)
        self.assertNotIn("apksigcopier", attestor)
        self.assertIn("subject-path: ${{ runner.temp }}/attest-input/signed.apk", attestor)
        self.assertIn("actions/attest@1e69f48acb82d1966a394da916b4c1698aa569d6 # v4", attestor)
        self.assertNotIn("attest-build-provenance@", attestor)

    def test_rc_verifier_uses_strict_raw_equivalence_and_owns_attest_input(self):
        workflow = RC_WORKFLOW.read_text()
        verifier = workflow[workflow.index("  verify_signed:"):workflow.index("  attest_signed:")]
        attestor = workflow[workflow.index("  attest_signed:"):]
        self.assertNotIn("apksigcopier", verifier)
        self.assertNotIn("sudo apt-get", verifier)
        self.assertIn("python3 control-workflow/scripts/apk_equivalence.py", verifier)
        self.assertIn("attest_input_artifact_id:", verifier)
        self.assertIn("Upload verifier-produced attest input", verifier)
        self.assertIn("EXPECTED_SIGNER_SHA256", verifier)
        self.assertIn("verifier signer fingerprint mismatch", verifier)
        self.assertIn("path: ${{ runner.temp }}/attest-input", verifier)
        self.assertIn("needs: verify_signed", attestor)
        self.assertIn("artifact-ids: ${{ needs.verify_signed.outputs.attest_input_artifact_id }}", attestor)
        self.assertIn("Validate attest input file set", attestor)
        self.assertIn("signed.apk release-identity-predicate.json", attestor)
        self.assertNotIn("build-evidence", attestor)
        self.assertNotIn("signed-output", attestor)

    def test_rc_reproducibility_gate_binds_primary_and_repro_before_signing(self):
        workflow = RC_WORKFLOW.read_text()
        recipe = (ROOT / "scripts/u2_build_evidence.sh").read_text()
        primary = self._job_block(workflow, "build_unsigned")
        repro = self._job_block(workflow, "build_repro")
        compare = self._job_block(workflow, "compare_reproducibility")
        prepare = self._job_block(workflow, "prepare_sign_input")
        signer = self._job_block(workflow, "sign_exact")
        verifier = self._job_block(workflow, "verify_signed")

        self.assertIn("bash \"$CONTROL_WORKFLOW_ROOT/scripts/u2_build_evidence.sh\" primary", primary)
        self.assertIn("bash \"$CONTROL_WORKFLOW_ROOT/scripts/u2_build_evidence.sh\" repro", repro)
        self.assertIn("BUILDER_ROLE", primary)
        for field in (
            "builder_recipe_sha256",
            "java_binary_sha256",
            "apksigner_sha256",
            "aapt2_sha256",
            "zipalign_sha256",
            "llvm_readelf_sha256",
        ):
            self.assertIn(field, workflow)
        self.assertIn('apksigner_tool_version="34.0.0"', recipe)
        self.assertIn('aapt2_tool_version="34.0.0"', recipe)
        self.assertIn('zipalign_tool_version="35.0.0"', recipe)
        self.assertIn("needs: [build_unsigned, build_repro]", compare)
        self.assertIn('python3 "$CONTROL_WORKFLOW_ROOT/scripts/reproducibility.py" compare', compare)
        self.assertIn("primary-artifact-id", compare)
        self.assertIn("repro-artifact-id", compare)
        self.assertIn("primary-artifact-digest", compare)
        self.assertIn("repro-artifact-digest", compare)
        self.assertIn("repro-comparison", compare)
        self.assertIn("EXPECTED_RELEASE_SHA", compare)
        self.assertIn("needs: [build_unsigned, compare_reproducibility]", prepare)
        self.assertIn("primary_artifact_id", prepare)
        self.assertIn("primary_artifact_digest", prepare)
        self.assertIn("reproducibility_report_artifact_digest", prepare)
        self.assertIn("runner_image_drift", workflow)
        self.assertIn("needs: [prepare_sign_input, compare_reproducibility]", signer)
        self.assertIn("EXPECTED_COMPARISON_REPORT_SHA256", signer)
        self.assertIn("EXPECTED_PRIMARY_ARTIFACT_DIGEST", signer)
        self.assertIn("job.workflow_sha", verifier)
        self.assertIn("reproducibility-report.json", verifier)
        self.assertIn("compare_reproducibility.outputs.report_artifact_id", verifier)
        self.assertIn("EXPECTED_SIGNED_OUTPUT_ARTIFACT_DIGEST", verifier)
        self.assertIn("signed_artifact_digest", verifier)

        attestor = self._job_block(workflow, "attest_signed")
        self.assertIn("EXPECTED_REPRODUCIBILITY_REPORT_ARTIFACT_DIGEST", attestor)
        self.assertIn("signed_artifact_digest", attestor)

    def test_rc_reproducibility_evidence_is_separate_from_production_contracts(self):
        workflow = RC_WORKFLOW.read_text()
        compare = self._job_block(workflow, "compare_reproducibility")
        self.assertIn("tvbox-u2-repro-build-evidence-", workflow)
        self.assertIn("tvbox-u2-repro-comparison-", workflow)
        self.assertIn("reproducibility-report.json", compare)
        self.assertIn("-eq 1", compare)
        self.assertIn("--primary-artifact-id", compare)

    def test_whole_repo_has_exactly_one_release_signing_consumer(self):
        consumers = []
        for path in (ROOT / ".github/workflows").glob("*.yml"):
            text = path.read_text()
            if "environment: release-signing" not in text:
                continue
            for line_no, line in enumerate(text.splitlines(), 1):
                if "environment: release-signing" in line:
                    consumers.append(f"{path.name}:{line_no}")
        self.assertEqual(consumers, ["rc-pipeline.yml:490"])

    def test_u2_publish_is_the_only_release_write_workflow(self):
        workflow = (ROOT / ".github/workflows/u2-release.yml").read_text()
        self.assertIn("TVBOX_U2_ENABLED", workflow)
        self.assertIn("TVBOX_RELEASE_TOKEN", workflow)
        self.assertIn("release-production", workflow)
        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("push:", workflow)
        for path in (ROOT / ".github/workflows").glob("*.yml"):
            text = path.read_text()
            if path.name in {"u2-release.yml", "rc-pipeline.yml"}:
                continue
            self.assertNotIn("TVBOX_RELEASE_TOKEN", text, path.name)
            self.assertNotIn("release-production", text, path.name)
        for path in (ROOT / ".github/workflows").glob("*.yml"):
            text = path.read_text()
            if path.name == "u2-release.yml":
                self.assertIn("gh release", text)
            else:
                self.assertNotIn("gh release", text, path.name)
        # Whole-repo write enumeration: release writes (contents:write / git push)
        # must live only in u2-release.yml (prep ref + publish) or in the
        # separately authorized U1 upstream-mirror workflow (upstream-monitor.yml,
        # whose write jobs only fast-forward main / push candidate branches).
        for path in (ROOT / ".github/workflows").glob("*.yml"):
            text = path.read_text()
            if path.name == "u2-release.yml":
                self.assertIn("contents: write", text)
                continue
            if path.name == "upstream-monitor.yml":
                continue
            self.assertNotIn("git push", text, path.name)
            self.assertNotIn("contents: write", text, path.name)
        qualify = (ROOT / "scripts/u2_qualify.sh").read_text()
        self.assertIn("release-debt", qualify)
        self.assertIn("verified-releases.json", qualify)
        self.assertIn("docs-only", qualify)
        self.assertIn("NOOP", qualify)

    @staticmethod
    def _job_block(workflow, job_id):
        match = re.search(
            rf"(?ms)^  {re.escape(job_id)}:\n.*?(?=^  [A-Za-z0-9_-]+:|\Z)",
            workflow,
        )
        if not match:
            raise AssertionError(f"missing workflow job: {job_id}")
        return match.group(0)

    @staticmethod
    def _yaml_tree(text):
        """Minimal indentation-based YAML block parser (pure stdlib).

        Returns nested dicts/lists for the subset used by GitHub workflow
        structure assertions (jobs, steps, needs, permissions, environment,
        concurrency, run blocks). No external dependencies.
        """
        import collections
        lines = text.splitlines()

        def parse_block(idx, indent):
            node = collections.OrderedDict()
            while idx < len(lines):
                line = lines[idx]
                if not line.strip() or line.lstrip().startswith("#"):
                    idx += 1
                    continue
                cur_indent = len(line) - len(line.lstrip(" "))
                if cur_indent < indent:
                    break
                if cur_indent > indent:
                    raise AssertionError(f"unexpected indent {cur_indent} > {indent}: {line!r}")
                stripped = line.strip()
                if stripped.startswith("- "):
                    seq = node.setdefault("__seq__", [])
                    body = stripped[2:]
                    nxt = lines[idx + 1] if idx + 1 < len(lines) else ""
                    child_indent = len(nxt) - len(nxt.lstrip(" ")) if nxt.strip() else -1
                    has_children = child_indent > cur_indent
                    if ":" in body:
                        key, _, value = body.partition(":")
                        value = value.strip()
                        item = {key: value} if value else {}
                        if has_children:
                            child, idx = parse_block(idx + 1, cur_indent + 2)
                            if isinstance(child, collections.OrderedDict):
                                item.update(child)
                            else:
                                item[key] = child
                        else:
                            idx += 1
                        seq.append(item)
                    else:
                        seq.append(body)
                        idx += 1
                    continue
                key, sep, value = stripped.partition(":")
                if not sep:
                    raise AssertionError(f"expected key: value, got {stripped!r}")
                value = value.strip()
                if value in ("|", ">", "|-", ">-"):
                    # Literal/folded block scalar: capture following indented lines.
                    buf = []
                    idx += 1
                    block_indent = None
                    while idx < len(lines):
                        line = lines[idx]
                        if not line.strip():
                            buf.append("")
                            idx += 1
                            continue
                        line_indent = len(line) - len(line.lstrip(" "))
                        if block_indent is None:
                            block_indent = line_indent
                        if line_indent < block_indent:
                            break
                        buf.append(line[block_indent:] if line_indent >= block_indent else "")
                        idx += 1
                    node[key] = "\n".join(buf)
                    continue
                if value:
                    node[key] = value
                    idx += 1
                    continue
                child, idx = parse_block(idx + 1, cur_indent + 2)
                node[key] = child
            return node, idx

        def normalize(node):
            if isinstance(node, collections.OrderedDict):
                if "__seq__" in node and len(node) == 1:
                    return node["__seq__"]
                return {k: normalize(v) for k, v in node.items()}
            if isinstance(node, list):
                return [normalize(item) for item in node]
            return node

        tree, _ = parse_block(0, 0)
        return normalize(tree)

    def test_rc_identity_creates_evidence_directory_before_writing(self):
        recipe = (ROOT / "scripts/u2_build_evidence.sh").read_text()
        self.assertIn("mkdir -p build/evidence", recipe)

    def test_rc_native_compatibility_uses_canonical_report_and_attested_debt(self):
        workflow = RC_WORKFLOW.read_text()
        native = (ROOT / "scripts/native_compat.py").read_text()
        self.assertIn("scripts/native_compat.py", workflow)
        self.assertIn("native-compat.json", workflow)
        self.assertIn("native_compat_report_sha256", workflow)
        self.assertIn("native_compat_status", workflow)
        self.assertIn("MIN_16K_ALIGNMENT = 0x4000", native)
        self.assertIn("libconscrypt_jni.so", workflow)
        self.assertIn("libquickjs-android-wrapper.so", workflow)
        self.assertIn("librtmp-jni.so", workflow)
        verifier = workflow[workflow.index("  verify_signed:"):workflow.index("  attest_signed:")]
        self.assertIn('.native_compat_status == "clean" and .native_incompatible_count == 0', verifier)
        self.assertIn('"known-debt"', verifier)

    def test_gradle_wrapper_is_pinned_to_official_8_7_artifacts(self):
        properties = (ROOT / "gradle/wrapper/gradle-wrapper.properties").read_text()
        self.assertIn("gradle-8.7-bin.zip", properties)
        self.assertIn("distributionSha256Sum=544c35d6bd849ae8a5ed0bcea39ba677dc40f49df7d1835561582da2009b961d", properties)
        wrapper_sha = subprocess.run(
            ["shasum", "-a", "256", str(ROOT / "gradle/wrapper/gradle-wrapper.jar")],
            check=True,
            text=True,
            capture_output=True,
        ).stdout.split()[0]
        self.assertEqual(wrapper_sha, "cb0da6751c2b753a16ac168bb354870ebb1e162e9083f116729cec9c781156b8")

    def test_fork_owned_workflow_actions_are_full_sha_pinned(self):
        for path in (ROOT / ".github/workflows").glob("*.yml"):
            for line in path.read_text().splitlines():
                if "uses:" not in line or "./.github/" in line:
                    continue
                self.assertRegex(line, r"uses: [^@]+@[0-9a-f]{40}(?:\s+# .+)?$", str(path))

    def test_u2_single_environment_publish_topology(self):
        """Parsed-YAML structural contract: exactly one job references
        release-production; rc_summary has no environment and prints the exact
        marker; no canary bypass remains."""
        workflow = (ROOT / ".github/workflows/u2-release.yml").read_text()
        tree = self._yaml_tree(workflow)
        jobs = tree["jobs"]
        self.assertIsInstance(jobs, dict)
        self.assertIn("rc_summary", jobs)
        self.assertIn("publish", jobs)
        self.assertNotIn("approval", jobs)
        self.assertNotIn("canary_publish", jobs)
        # Exactly one environment consumer: publish.
        env_jobs = [name for name, job in jobs.items()
                    if isinstance(job, dict) and job.get("environment")]
        self.assertEqual(env_jobs, ["publish"], f"release-production consumers: {env_jobs}")
        self.assertNotIn("environment", jobs["rc_summary"])
        # rc_summary must print the exact marker to the run log.
        rc_steps = jobs["rc_summary"].get("steps") or []
        rc_text = "\n".join(str(s) for s in rc_steps)
        self.assertIn("TVBOX_RELEASE_APPROVE_V2", rc_text)
        self.assertIn("EXPECTED_MARKER", rc_text)
        self.assertNotIn("secrets.TVBOX_RELEASE_TOKEN", rc_text)
        # The approval prompt must match the actual gate semantics (older
        # attempt markers are tolerated as history; exactly one current marker
        # required; non-slashinchi actor fails closed). It must not claim any
        # non-marker comment is rejected outright, and must say exactly one
        # current marker is required (not "at least one").
        self.assertNotIn("Any other comment is rejected", rc_text)
        self.assertNotIn("At least one", rc_text)
        self.assertIn("exactly 1 matching marker is required for the current run/attempt", rc_text)
        self.assertIn("prior attempt approvals are tolerated", rc_text)
        # No persistent canary bypass.
        self.assertNotIn("canary_mode", workflow)
        self.assertNotIn("TVBOX_CANARY_INJECT", workflow)
        # gate must not force qualified=true.
        gate_steps = jobs["gate"].get("steps") or []
        gate_text = "\n".join(str(s) for s in gate_steps)
        self.assertNotIn("qualified=true", gate_text)
        # publish owns job-level concurrency with queue: max.
        publish_concurrency = jobs["publish"].get("concurrency") or {}
        self.assertEqual(publish_concurrency.get("group"), "tvbox-u2-publish")
        self.assertEqual(publish_concurrency.get("cancel-in-progress"), "false")
        self.assertEqual(publish_concurrency.get("queue"), "max")
        # rc_summary and publish ordering: publish needs rc_summary.
        publish_needs = jobs["publish"].get("needs")
        self.assertIn("rc_summary", str(publish_needs))

    def test_u2_publish_chain_is_wired_with_helpers_and_concurrency(self):
        workflow = (ROOT / ".github/workflows/u2-release.yml").read_text()
        tree = self._yaml_tree(workflow)
        publish = tree["jobs"]["publish"]
        steps = publish["steps"]
        step_text = "\n".join(str(s) for s in steps)
        self.assertIn("Promote patched to exact release SHA (CAS)", step_text)
        self.assertIn('$RELEASE_SHA:refs/heads/patched', step_text)
        self.assertIn("actions/artifacts/${{ needs.build_rc.outputs.signed_artifact_id }}/zip", step_text)
        self.assertIn("extract-signed-apk", step_text)
        self.assertIn("gh release create", step_text)
        self.assertIn("--draft", step_text)
        self.assertIn("reconcile-draft", step_text)
        self.assertIn("--expected-target-sha", step_text)
        self.assertIn("--update-digest", step_text)
        self.assertIn("Attach missing assets only (no clobber)", step_text)
        # The upload step itself must never use --clobber; downloads may.
        attach_step = next(s for s in steps if "Attach missing assets" in str(s))
        self.assertNotIn("--clobber", str(attach_step))
        self.assertIn("Verify both assets before publish (API digest + download bytes)", step_text)
        self.assertIn("verify-release-assets", step_text)
        self.assertIn('gh release edit "$tag" --repo slashinchi/TVBoxOS-Mobile --draft=false', step_text)
        self.assertNotIn("gh release publish", step_text)
        self.assertIn('gh release verify "$tag"', step_text)
        self.assertIn("verify-asset", step_text)
        self.assertIn("gh release download \"$tag\"", step_text)
        self.assertIn("refs/tags/${tag}^{commit}", step_text)
        self.assertIn("immutable:.immutable", step_text)
        self.assertIn("monotonic-compare", step_text)
        self.assertIn("verify-remote-metadata", step_text)
        self.assertIn("release-delivery", step_text)
        self.assertIn("incident-key", step_text)
        # The delivery incident step must authenticate gh for issue reads/writes:
        # only TOKEN (a non-gh env var) would leave `gh issue list/create`
        # unauthenticated and the incident would never be opened.
        delivery_step = next(s for s in steps if "Delivery check against proxy URL" in str(s))
        delivery_text = str(delivery_step)
        self.assertIn("GH_TOKEN", delivery_text)
        self.assertIn("github.token", delivery_text)
        self.assertIn("TOKEN", delivery_text)
        self.assertIn("u2-prep-", step_text)
        self.assertIn("concurrency", publish)
        self.assertEqual(publish["concurrency"]["group"], "tvbox-u2-publish")
        self.assertEqual(publish["concurrency"]["queue"], "max")
        self.assertIn("Source PR", step_text)
        self.assertIn("Upstream SHA", step_text)
        # approval-marker verification must live inside publish.
        self.assertIn("Verify exact approval marker from current-run review history", step_text)
        self.assertIn("approval-matches", step_text)
        self.assertIn("actions/runs/${RUN_ID}/approvals", step_text)
        approval_step = next(s for s in steps if "Verify exact approval marker" in str(s))
        self.assertNotIn("break", str(approval_step))
        # prep and qualify structural checks.
        prep = tree["jobs"]["prep"]
        prep_text = "\n".join(str(s) for s in (prep.get("steps") or []))
        self.assertIn("plan-prep", prep_text)
        self.assertIn("write-prep-version", prep_text)
        self.assertIn("u2-prep-", prep_text)
        self.assertNotIn("replacing with fresh prep", prep_text)
        self.assertIn("refusing to delete or replace a divergent prep", prep_text)
        qualify = tree["jobs"]["qualify"]
        qualify_text = "\n".join(str(s) for s in (qualify.get("steps") or []))
        self.assertIn("qualify-u1", qualify_text)
        self.assertIn("parse-provenance-marker", qualify_text)
        # watch_approval identity-bound.
        watch = tree["jobs"]["watch_approval"]
        watch_text = "\n".join(str(s) for s in (watch.get("steps") or []))
        self.assertIn("incident-key", watch_text)
        self.assertIn("human-blocked", watch_text)

    def test_u2_publish_chain_fails_closed_on_unreusable_draft(self):
        workflow = (ROOT / ".github/workflows/u2-release.yml").read_text()
        tree = self._yaml_tree(workflow)
        publish = tree["jobs"]["publish"]
        steps = publish["steps"]
        step_text = "\n".join(str(s) for s in steps)
        self.assertIn("reconcile-draft", step_text)
        self.assertIn("cannot be safely reused", step_text)
        self.assertIn("repair-missing", step_text)
        self.assertIn("exact-reuse", step_text)
        self.assertIn("no clobber", step_text)
        attach_step = next(s for s in steps if "Attach missing assets" in str(s))
        self.assertNotIn("--clobber", str(attach_step))

    def test_u2_publish_chain_supports_published_recovery_and_preflight_gates(self):
        workflow = (ROOT / ".github/workflows/u2-release.yml").read_text()
        tree = self._yaml_tree(workflow)
        publish = tree["jobs"]["publish"]
        steps = publish["steps"]
        step_text = "\n".join(str(s) for s in steps)
        # Published (non-draft) recovery: the create/reconcile step classifies
        # an existing published Release via released-identity and continues
        # ONLY on verify-published; any other decision (incl. missing assets,
        # which are unrecoverable on an immutable Release) fails closed.
        self.assertIn("released-identity", step_text)
        self.assertIn("verify-published", step_text)
        self.assertIn("conflicting public identity or unrecoverable missing assets fail closed", step_text)
        self.assertNotIn("repair-published-missing", step_text)
        # Attestation verification in publish must pin the exact signing
        # workflow identity (rc-pipeline.yml on patched) for BOTH predicate
        # types, so a signature from any other workflow/ref never passes.
        # The OIDC cert SAN is the full URI (verified from U2a attestation
        # evidence); an exact regex on that full form is required and a short
        # --cert-identity string would never match.
        attest_step = next(s for s in steps if "Verify attestations for the exact signed RC" in str(s))
        attest_text = str(attest_step)
        self.assertIn("--predicate-type https://slsa.dev/provenance/v1", attest_text)
        self.assertIn("--predicate-type https://slashinchi.github.io/TVBoxOS-Mobile/tvbox-release-identity/v2", attest_text)
        # str() of the parsed step is a dict repr, so each literal backslash
        # in the regex appears doubled; assert on that repr form.
        san_regex = r'^https://github\\.com/slashinchi/TVBoxOS-Mobile/\\.github/workflows/rc-pipeline\\.yml@refs/heads/patched$'
        self.assertIn(san_regex, attest_text)
        self.assertEqual(attest_text.count(san_regex), 2)
        # Publish step must skip already-published releases (retry recovery)
        # and must use the real gh draft-publication mechanism
        # (gh release edit --draft=false; `gh release publish` does not exist).
        publish_step = next(s for s in steps if "Publish verified draft" in str(s))
        publish_text = str(publish_step)
        self.assertIn("already published; skipping publish", publish_text)
        self.assertIn('gh release edit "$tag" --repo slashinchi/TVBoxOS-Mobile --draft=false', publish_text)
        self.assertNotIn("gh release publish", publish_text)
        # Promote recovery must require the formal TAG OBJECT, never a draft
        # (drafts have no git tag ref; gh release view succeeds for drafts).
        promote_step = next(s for s in steps if "Promote patched to exact release SHA" in str(s))
        promote_text = str(promote_step)
        self.assertIn("refs/tags/${tag}^{}", promote_text)
        self.assertIn("tag target commit", promote_text)
        self.assertIn("resolve_tag_target", promote_text)
        self.assertNotIn('gh release view "$tag"', promote_text)
        # Metadata reconciliation must fail closed when the remote baseline
        # cannot be read (never treat an empty current as "may advance").
        metadata_step = next(s for s in steps if "Reconcile root update.json" in str(s))
        metadata_text = str(metadata_step)
        self.assertIn("cannot read current patched/update.json from remote", metadata_text)
        self.assertIn("refusing to proceed on an unknown baseline", metadata_text)
        self.assertIn("no readable version", metadata_text)
        # Metadata push must survive a concurrent patched push (TOCTOU): it
        # rebuilds the single update.json commit on the new remote HEAD.
        self.assertIn("patched moved during publish", metadata_text)
        self.assertIn("rebuilding update.json commit on remote HEAD", metadata_text)
        # Approval gate: every approved review must be slashinchi, and exactly
        # one record must carry the current-attempt marker (re-run history from
        # older attempts is tolerated, so retry recovery is not blocked).
        approval_step = next(s for s in steps if "Verify exact approval marker" in str(s))
        approval_text = str(approval_step)
        self.assertIn("actor is not slashinchi", approval_text)
        # The actor stream must be NUL-delimited and the jq fallback must be
        # parenthesized: `// ""` binds looser than `+`, so the un-parenthesized
        # form `.[].user.login // "" + "\u0000"` emits no NUL and `read -d ''`
        # never executes the loop body (actor check silently skipped).
        # str() of the parsed step is a dict repr, so the NUL literal appears
        # escaped: assert on the parentheses + operator instead of the escape.
        self.assertIn('.[] | (.user.login // "") + "', approval_text)
        self.assertIn("actor_ok", approval_text)
        # The comment stream must use `jq -j` so the NUL separator is the only
        # delimiter: `jq -r` appends a trailing newline after every NUL, making
        # the next comment start with "\n" (only tolerated today by the Python
        # marker parser's .strip()). These two tokens MUST live on the SAME jq
        # command line: separate cross-section asserts would still pass if the
        # comment stream regressed to `jq -r`, because the actor stream already
        # contains `jq -j -r` (a false-positive coverage blind spot).
        comment_lines = [
            line for line in approval_step["run"].splitlines()
            if ".[].comment // " in line
        ]
        self.assertEqual(len(comment_lines), 1, approval_text)
        self.assertIn("jq -j -r ", comment_lines[0])
        self.assertIn("gsub(", comment_lines[0])
        self.assertIn("expected exactly one approval marker matching this run/attempt", approval_text)
        self.assertNotIn("expected exactly one release-production approval, found", approval_text)
        # Immutable-releases preflight before any mutation.
        revalidate_step = next(s for s in steps if "Revalidate release identity" in str(s))
        self.assertIn("immutable-releases", str(revalidate_step))
        self.assertIn("immutable releases are not enabled", str(revalidate_step))
        # Independent APK signer/package/version verification.
        self.assertIn("Independently verify APK signer/package/version", step_text)
        self.assertIn("apksigner", step_text)
        self.assertIn("aapt2", step_text)
        self.assertIn("publish signer fingerprint mismatch", step_text)
        self.assertIn("publish APK package mismatch", step_text)
        self.assertIn("publish APK versionName mismatch", step_text)
        # Metadata step must skip a no-op identical commit on retry recovery.
        metadata_step = next(s for s in steps if "Reconcile root update.json" in str(s))
        self.assertIn("already identical", str(metadata_step))
        # The release-view JSON fields must stay within gh's documented set
        # (tag_target_sha is not a supported --json field and would make
        # reconcile unreachable; the shell variable of the same name is fine).
        for view in ("Create or reconcile draft", "Verify both assets before publish"):
            view_step = next(s for s in steps if view in str(s))
            view_run = str(view_step).replace("\\n", "\n")
            json_line = next(l for l in view_run.splitlines() if "--json" in l)
            self.assertNotIn("tag_target_sha", json_line)
        # The tag-ref API call must NOT use --silent (gh api --silent swallows
        # ALL stdout including --jq results on success) and must guard on the
        # exit code so a 404 error body is never captured into the identity
        # fallback (gh api prints the error body to stdout even on exit 1).
        draft_step = next(s for s in steps if "Create or reconcile draft" in str(s))
        draft_run = str(draft_step).replace("\\n", "\n")
        self.assertNotIn("--silent", draft_run)
        self.assertIn("tag_target_sha=$(resolve_tag_target", draft_run)
        self.assertIn("object.type", draft_run)
        self.assertIn("refs/tags/${tag}^{}", draft_run)

    def test_u2_metadata_reconciliation_is_bounded_two_file_normal_cas(self):
        workflow = (ROOT / ".github/workflows/u2-release.yml").read_text()
        tree = self._yaml_tree(workflow)
        publish = tree["jobs"]["publish"]
        steps = publish["steps"]
        metadata_step = next(
            s for s in steps if "Reconcile verified release metadata" in str(s)
        )
        metadata_text = str(metadata_step)
        for token in (
            "gradle/verified-releases.json",
            "reconcile-verified-releases",
            "verify_verified_releases",
            "verify-remote-metadata",
            "current-canonical-update.json",
            "keys | sort",
            "git fetch --no-tags origin",
            "refs/heads/patched",
            "non-fast-forward",
            "retry exhaustion",
            "git add update.json gradle/verified-releases.json",
        ):
            self.assertIn(token, metadata_text, token)
        self.assertIn("for attempt in 1 2 3", metadata_text)
        self.assertNotIn("git push --atomic", metadata_text)
        self.assertNotIn("git push --force", metadata_text)
        self.assertNotIn("git push -f", metadata_text)

    def test_u2_metadata_preflight_precedes_all_formal_release_mutations(self):
        workflow = (ROOT / ".github/workflows/u2-release.yml").read_text()
        tree = self._yaml_tree(workflow)
        steps = tree["jobs"]["publish"]["steps"]
        names = [step.get("name", "") for step in steps]
        preflight_index = names.index("Preflight verified release metadata")
        promote_index = names.index("Promote patched to exact release SHA (CAS)")
        mutation_indexes = [
            names.index("Create or reconcile draft Release with exact identity"),
            names.index("Attach missing assets only (no clobber)"),
            names.index("Publish verified draft"),
        ]
        self.assertLess(preflight_index, promote_index)
        self.assertLess(promote_index, min(mutation_indexes))
        preflight = str(steps[preflight_index])
        for token in (
            "update.json",
            "gradle/verified-releases.json",
            "reconcile-verified-release-metadata",
            "current-update",
            "current-ledger",
        ):
            self.assertIn(token, preflight, token)

    def test_u2_promote_is_locked_to_the_preflight_live_patched_sha(self):
        workflow = (ROOT / ".github/workflows/u2-release.yml").read_text()
        tree = self._yaml_tree(workflow)
        steps = tree["jobs"]["publish"]["steps"]
        preflight = next(s for s in steps if s.get("name") == "Preflight verified release metadata")
        self.assertEqual(preflight.get("id"), "preflight")
        preflight_text = str(preflight)
        self.assertIn('echo "remote_head_before=$remote_head_before" >> "$GITHUB_OUTPUT"', preflight_text)

        promote = next(s for s in steps if s.get("name") == "Promote patched to exact release SHA (CAS)")
        promote_text = promote["run"]
        self.assertIn("steps.preflight.outputs.remote_head_before", str(promote))
        live_read = promote_text.index("git ls-remote")
        current_decision = promote_text.index('if [[ "$current" == "$RELEASE_SHA" ]]')
        recovery_decision = promote_text.index('git merge-base --is-ancestor "$RELEASE_SHA" "$current"')
        self.assertLess(live_read, min(current_decision, recovery_decision))
        self.assertIn('[[ "$live_remote_sha" == "$preflight_sha" ]]', promote_text)
        self.assertIn('[[ "$current" == "$preflight_sha" ]]', promote_text)
        self.assertIn("refusing to continue", promote_text)

    def test_u2_metadata_retry_uses_porcelain_status_and_remote_sha_not_log_grep(self):
        workflow = (ROOT / ".github/workflows/u2-release.yml").read_text()
        tree = self._yaml_tree(workflow)
        publish = tree["jobs"]["publish"]
        metadata_step = next(
            step for step in publish["steps"]
            if step.get("name") == "Reconcile verified release metadata with bounded normal CAS"
        )
        metadata_text = str(metadata_step)
        for token in (
            "git push --porcelain",
            "git ls-remote",
            "remote_head_before",
            "remote_head_after",
            "push_is_non_fast_forward",
            "awk",
        ):
            self.assertIn(token, metadata_text, token)
        self.assertNotIn("grep -Eq", metadata_text)

    def test_strict_json_parser_is_used_for_release_ledger_cli_input(self):
        duplicate = '{"tag":"v2.1.26.1","tag":"v2.1.26.1"}'
        with self.assertRaises(ValueError):
            u2_release_module.strict_json_loads(duplicate)
        with tempfile.NamedTemporaryFile(mode="w+", suffix=".json") as file:
            file.write(duplicate)
            file.flush()
            result = subprocess.run(
                ["python3", "scripts/u2_release.py", "canonical-release-baseline", "--file", file.name],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
        self.assertNotEqual(result.returncode, 0)

    def test_metadata_postpublish_reuses_shared_pair_preflight_and_persisted_entry(self):
        workflow = (ROOT / ".github/workflows/u2-release.yml").read_text()
        tree = self._yaml_tree(workflow)
        metadata_step = next(
            step for step in tree["jobs"]["publish"]["steps"]
            if step.get("name") == "Reconcile verified release metadata with bounded normal CAS"
        )
        metadata_text = str(metadata_step)
        self.assertIn("reconcile-verified-release-metadata", metadata_text)
        self.assertIn("persisted_verified_release_entry", metadata_text)
        self.assertIn("metadata_ledger", metadata_text)

    def test_metadata_postpublish_readback_requires_stable_branch_snapshot_and_fresh_retry(self):
        workflow = (ROOT / ".github/workflows/u2-release.yml").read_text()
        tree = self._yaml_tree(workflow)
        metadata_step = next(
            step for step in tree["jobs"]["publish"]["steps"]
            if step.get("name") == "Reconcile verified release metadata with bounded normal CAS"
        )
        metadata_text = str(metadata_step)
        for token in (
            "readback_head_before",
            "readback_head_after",
            "patched moved during metadata readback",
            "fresh fetch and remote read",
            "continue",
        ):
            self.assertIn(token, metadata_text, token)
        self.assertIn("if verify_remote_blobs", metadata_text)

    def test_release_and_tag_reads_allow_only_explicit_404_fallback(self):
        workflow = (ROOT / ".github/workflows/u2-release.yml").read_text()
        tree = self._yaml_tree(workflow)
        promote_step = next(
            step for step in tree["jobs"]["publish"]["steps"]
            if step.get("name") == "Promote patched to exact release SHA (CAS)"
        )
        self.assertIn("classify-release-read", str(promote_step))
        release_step = next(
            step for step in tree["jobs"]["publish"]["steps"]
            if step.get("name") == "Create or reconcile draft Release with exact identity"
        )
        release_text = str(release_step)
        self.assertIn("classify-release-read", release_text)
        self.assertIn("release_http_status", release_text)
        self.assertIn("release_read_action", release_text)
        self.assertNotIn("gh release view \"$tag\" --repo slashinchi/TVBoxOS-Mobile \\\n            --json tagName,targetCommitish,isDraft,assets \\\n            --jq '.' 2>/dev/null || echo \"\"", release_text)
        self.assertIn("tag_read_action", release_text)
        self.assertIn("tag_http_status", release_text)

    def test_auto_qualification_requires_real_trusted_replay_evidence(self):
        workflow = (ROOT / ".github/workflows/u2-release.yml").read_text()
        qualify = workflow[workflow.index("  qualify:"):workflow.index("  prep:")]
        qualify_script = (ROOT / "scripts/u2_qualify.sh").read_text()
        for token in (
            'git show "$PUSH_BEFORE:scripts/u2_release.py"',
            'git show "$PUSH_BEFORE:scripts/upstream_monitor.py"',
            'git show "$PUSH_BEFORE:scripts/u2_qualify.sh"',
            'refs/remotes/upstream/main',
            'refs/remotes/origin/main',
            'git worktree add --detach',
            'source_parents',
            'candidate_parents',
            'replay_file',
            '--replay-file',
            '--upstream-version',
            '--upstream-code',
            'marker_fork_main',
        ):
            self.assertIn(token, qualify, token)
        self.assertIn('git show "$SOURCE_SHA:scripts/u2_release.py"', qualify)
        self.assertIn('git show "$SOURCE_SHA:scripts/upstream_monitor.py"', qualify)
        self.assertIn('git show "$SOURCE_SHA:scripts/u2_qualify.sh"', qualify)
        self.assertIn('bash "$trusted_root/scripts/u2_qualify.sh"', qualify)
        self.assertIn("head -1 || true", qualify)
        self.assertNotIn("--replay-status", qualify)
        self.assertNotIn("--replay-tree", qualify)
        self.assertNotIn("--replay-actual-tree", qualify)
        self.assertIn("U2_REPO_ROOT", qualify_script)
        self.assertIn("U2_RELEASE_HELPER", qualify_script)

    def test_manual_dispatch_does_not_depend_on_push_event_shas(self):
        workflow = (ROOT / ".github/workflows/u2-release.yml").read_text()
        qualify = workflow[workflow.index("  qualify:"):workflow.index("  prep:")]
        self.assertIn('if [[ "$MODE" == "auto-upstream" ]]; then', qualify)
        self.assertIn('git show "$SOURCE_SHA:scripts/u2_release.py"', qualify)
        self.assertIn('git show "$SOURCE_SHA:scripts/upstream_monitor.py"', qualify)
        auto_section = qualify[qualify.index('if [[ "$MODE" == "auto-upstream" ]]; then'):]
        self.assertIn('[[ -n "$PUSH_BEFORE" && -n "$PUSH_AFTER" ]]', auto_section)

    def test_release_debt_cli_computes_canonical_baseline_and_fingerprint(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            self._git(repo, "init", "-b", "main")
            self._git(repo, "config", "user.name", "U2 test")
            self._git(repo, "config", "user.email", "u2@example.invalid")
            (repo / "runtime.txt").write_text("one\n")
            (repo / "app").mkdir()
            (repo / "app/build.gradle").write_text("versionCode 23601\nversionName '2.1.26.1'\n")
            self._git(repo, "add", ".")
            self._git(repo, "commit", "-m", "release v2.1.26.1")
            baseline = self._git(repo, "rev-parse", "HEAD")
            (repo / "runtime.txt").write_text("two\n")
            self._git(repo, "add", "-A")
            self._git(repo, "commit", "-m", "runtime change")
            current = self._git(repo, "rev-parse", "HEAD")
            releases = [{
                "tag": "v2.1.26.1",
                "target": baseline,
                "versionName": "2.1.26.1",
                "versionCode": 23601,
                "assetSha256": "d" * 64,
                "signerSha256": "e" * 64,
                "verified": True,
                "tag_ancestor": True,
            }]
            releases_file = repo / "releases.json"
            releases_file.write_text(json.dumps(releases))
            result = subprocess.run(
                [
                    "python3", "scripts/u2_release.py", "release-debt",
                    "--repo", str(repo),
                    "--releases-file", str(releases_file),
                    "--current", current,
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            parsed = json.loads(result.stdout)
            self.assertEqual(parsed["baseline"]["tag"], "v2.1.26.1")
            self.assertEqual(parsed["baseline"]["target"], baseline)
            self.assertEqual(parsed["classification"], "unknown/high-risk")
            self.assertEqual(len(parsed["fingerprint"]), 64)
            self.assertEqual(parsed["path_count"], 1)

    def test_qualify_u1_cli_accepts_valid_merge_and_rejects_bad_parents(self):
        upstream = "a" * 40
        candidate = "b" * 40
        tree = "c" * 40
        before = "d" * 40
        after = "e" * 40
        marker = build_provenance_marker(upstream, candidate, tree, upstream, "2.1.27", 237)
        pr = json.dumps({
            "number": 7,
            "state": "closed",
            "merged_at": "2026-08-28T00:00:00Z",
            "base": "patched",
            "merged_by": "slashinchi",
            "author": "github-actions[bot]",
            "head_repository": "slashinchi/TVBoxOS-Mobile",
            "head": candidate_branch_name(upstream),
            "head_sha": candidate,
            "merge_commit_sha": after,
        })
        replay = {
            "status": "clean",
            "candidate_needed": True,
            "before": before,
            "source_after": after,
            "source_parents": [before, candidate],
            "candidate": candidate,
            "candidate_parents": [before, upstream],
            "upstream": upstream,
            "upstream_repository": "kukuqi666/TVBoxOS-Mobile",
            "upstream_ref": "refs/heads/main",
            "fork_main": upstream,
            "marker_fork_main": upstream,
            "fork_main_is_ancestor": True,
            "marker_tree": tree,
            "candidate_tree": tree,
            "rebuilt_tree": tree,
            "source_tree": tree,
        }
        with tempfile.TemporaryDirectory() as tmp:
            replay_path = Path(tmp) / "replay.json"
            replay_path.write_text(json.dumps(replay))
            base = [
                "python3", "scripts/u2_release.py", "qualify-u1",
                "--before", before,
                "--after", after,
                "--parents", before, candidate,
                "--actor", "slashinchi",
                "--pr", pr,
                "--repository", "slashinchi/TVBoxOS-Mobile",
                "--upstream", upstream,
                "--marker", marker,
                "--candidate-tree", tree,
                "--upstream-ancestor", "true",
                "--upstream-version", "2.1.27",
                "--upstream-code", "237",
                "--replay-file", str(replay_path),
            ]
            ok = subprocess.run(base, cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(ok.returncode, 0, ok.stderr)
            self.assertEqual(json.loads(ok.stdout)["qualified"], True)
            bad = subprocess.run(
                base + ["--parents", before, "f" * 40],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
            self.assertEqual(bad.returncode, 0, bad.stderr)
            self.assertEqual(json.loads(bad.stdout)["reason"], "merge-parent-mismatch")

    def test_qualify_u1_cli_accepts_structured_replay_file(self):
        upstream = "a" * 40
        candidate = "b" * 40
        tree = "c" * 40
        before = "d" * 40
        after = "e" * 40
        marker = build_provenance_marker(upstream, candidate, tree, upstream, "2.1.27", 237)
        pr = json.dumps({
            "number": 7,
            "state": "closed",
            "merged_at": "2026-08-28T00:00:00Z",
            "base": "patched",
            "merged_by": "slashinchi",
            "author": "github-actions[bot]",
            "head_repository": "slashinchi/TVBoxOS-Mobile",
            "head": candidate_branch_name(upstream),
            "head_sha": candidate,
            "merge_commit_sha": after,
        })
        replay = {
            "status": "clean",
            "candidate_needed": True,
            "before": before,
            "source_after": after,
            "source_parents": [before, candidate],
            "candidate": candidate,
            "candidate_parents": [before, upstream],
            "upstream": upstream,
            "upstream_repository": "kukuqi666/TVBoxOS-Mobile",
            "upstream_ref": "refs/heads/main",
            "fork_main": upstream,
            "marker_fork_main": upstream,
            "fork_main_is_ancestor": True,
            "marker_tree": tree,
            "candidate_tree": tree,
            "rebuilt_tree": tree,
            "source_tree": tree,
        }
        with tempfile.TemporaryDirectory() as tmp:
            replay_path = Path(tmp) / "replay.json"
            replay_path.write_text(json.dumps(replay))
            result = subprocess.run(
                [
                    "python3", "scripts/u2_release.py", "qualify-u1",
                    "--before", before,
                    "--after", after,
                    "--parents", before, candidate,
                    "--actor", "slashinchi",
                    "--pr", pr,
                    "--repository", "slashinchi/TVBoxOS-Mobile",
                    "--upstream", upstream,
                    "--marker", marker,
                    "--candidate-tree", tree,
                    "--upstream-ancestor", "true",
                    "--upstream-version", "2.1.27",
                    "--upstream-code", "237",
                    "--replay-file", str(replay_path),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["qualified"])

    def test_plan_prep_cli_derives_version_and_trailers(self):
        published = [["2.1.26.1", 23601], ["2.1.27.1", 23701]]
        with tempfile.NamedTemporaryFile("w+", suffix=".json", delete=False) as f:
            json.dump(published, f)
            published_path = f.name
        source = "a" * 40
        debt = "b" * 64
        result = subprocess.run(
            [
                "python3", "scripts/u2_release.py", "plan-prep",
                "--upstream-name", "2.1.27",
                "--upstream-code", "237",
                "--published-file", published_path,
                "--source", source,
                "--mode", "auto-upstream",
                "--upstream", "c" * 40,
                "--debt", debt,
                "--pr", "7",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        import os
        os.unlink(published_path)
        self.assertEqual(result.returncode, 0, result.stderr)
        parsed = json.loads(result.stdout)
        self.assertEqual(parsed["versionName"], "2.1.27.2")
        self.assertEqual(parsed["versionCode"], 23702)
        self.assertIn(f"TVBox-U2-Source: {source}", parsed["trailers"])
        self.assertIn(f"TVBox-U2-Debt: {debt}", parsed["trailers"])
        self.assertEqual(parsed["spec"]["parent"], source)

    def test_plan_prep_cli_accepts_canonical_release_dicts(self):
        published = [
            {"tag": "v2.1.26.1", "versionName": "2.1.26.1", "versionCode": 23601, "verified": True},
            {"tag": "v2.1.27.1", "versionName": "2.1.27.1", "versionCode": 23701, "verified": True},
        ]
        with tempfile.NamedTemporaryFile("w+", suffix=".json", delete=False) as f:
            json.dump(published, f)
            published_path = f.name
        result = subprocess.run(
            [
                "python3", "scripts/u2_release.py", "plan-prep",
                "--upstream-name", "2.1.27",
                "--upstream-code", "237",
                "--published-file", published_path,
                "--source", "a" * 40,
                "--mode", "auto-upstream",
                "--upstream", "c" * 40,
                "--debt", "b" * 64,
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        import os
        os.unlink(published_path)
        self.assertEqual(result.returncode, 0, result.stderr)
        parsed = json.loads(result.stdout)
        self.assertEqual(parsed["versionName"], "2.1.27.2")
        self.assertEqual(parsed["versionCode"], 23702)

    def test_write_prep_version_rewrites_only_version_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "build.gradle"
            path.write_text(
                "apply plugin: 'com.android.application'\n"
                "versionCode 23601\n"
                "versionName '2.1.26.1'\n"
                "compileSdkVersion 35\n"
            )
            result = subprocess.run(
                [
                    "python3", "scripts/u2_release.py", "write-prep-version",
                    "--file", str(path),
                    "--version-name", "2.1.27.1",
                    "--version-code", "23701",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["versionName"], "2.1.27.1")
            text = path.read_text()
            self.assertIn("versionCode 23701", text)
            self.assertIn("versionName '2.1.27.1'", text)
            self.assertIn("compileSdkVersion 35", text)
            self.assertNotIn("versionCode 23601", text)

    @staticmethod
    def _git(repo, *args):
        return subprocess.run(
            ["git", "-C", str(repo), *args],
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()

    def test_qualify_noop_mode_stops_before_build(self):
        script = ROOT / "scripts/u2_qualify.sh"
        head = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()
        with tempfile.NamedTemporaryFile(mode="w+", suffix=".txt") as output:
            env = {
                **os.environ,
                "SOURCE_SHA": head,
                "MODE": "auto-upstream",
                "NOOP": "true",
                "GITHUB_OUTPUT": output.name,
            }
            result = subprocess.run(
                ["bash", str(script)],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            output.seek(0)
            written = output.read()
            self.assertIn("noop=true", written)
            self.assertIn("qualified=false", written)

    def test_u2_manual_dispatch_has_explicit_intent_and_live_sha_lock(self):
        workflow = (ROOT / ".github/workflows/u2-release.yml").read_text()
        tree = self._yaml_tree(workflow)
        dispatch = tree["on"]["workflow_dispatch"]
        self.assertIn("inputs", dispatch)
        inputs = dispatch["inputs"]
        self.assertEqual(inputs["intent"]["type"], "choice")
        self.assertTrue(inputs["intent"]["required"] == "true")
        self.assertEqual(
            inputs["intent"]["options"],
            ["release", "recover", "noop-smoke"],
        )
        self.assertEqual(inputs["expected_sha"]["type"], "string")
        self.assertTrue(inputs["expected_sha"]["required"] == "true")

        gate = self._job_block(workflow, "gate")
        gate_run = gate[gate.index("run: |") :]
        for token in (
            "INPUT_INTENT",
            "EXPECTED_SHA",
            '[[ "$ACTOR" == "slashinchi" ]]',
            '[[ "$REF" == "refs/heads/patched" ]]',
            '[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]]',
            "git ls-remote",
            "live_patched",
            '[[ "$live_patched" == "$EXPECTED_SHA" ]]',
            '[[ "$GITHUB_SHA" == "$EXPECTED_SHA" ]]',
            'echo "intent=$INPUT_INTENT"',
        ):
            self.assertIn(token, gate_run, token)

        manual = gate_run[gate_run.index('elif [[ "$EVENT" == "workflow_dispatch" ]]') :]
        manual = manual[: manual.index("else")]
        self.assertNotIn("PUSH_BEFORE", manual)
        self.assertNotIn("PUSH_AFTER", manual)
        self.assertIn('echo "source_sha=$EXPECTED_SHA"', gate_run)

    def test_u2_canary_harness_is_dispatch_only_and_locks_one_live_patched_sha(self):
        self.assertTrue(CANARY_HARNESS_WORKFLOW.is_file())
        workflow = CANARY_HARNESS_WORKFLOW.read_text()
        tree = self._yaml_tree(workflow)
        self.assertEqual(set(tree["on"]), {"workflow_dispatch"})
        dispatch = tree["on"]["workflow_dispatch"]
        inputs = dispatch["inputs"]
        self.assertEqual(inputs["expected_sha"]["type"], "string")
        self.assertEqual(inputs["expected_sha"]["required"], "true")
        self.assertEqual(inputs["failure_injection"]["type"], "choice")
        self.assertEqual(
            inputs["failure_injection"]["options"],
            ["none", "digest-mismatch", "signer-mismatch", "attestation-identity-mismatch"],
        )

        gate = self._job_block(workflow, "gate")
        gate_run = gate[gate.index("run: |") :]
        for token in (
            '[[ "$EVENT" == "workflow_dispatch" ]]',
            '[[ "$ACTOR" == "slashinchi" ]]',
            '[[ "$REF" == "refs/heads/patched" ]]',
            'assert_full_sha "$EXPECTED_SHA"',
            "git ls-remote",
            'refs/heads/patched',
            '[[ "$live_patched" == "$EXPECTED_SHA" ]]',
            '[[ "$GITHUB_SHA" == "$EXPECTED_SHA" ]]',
            '[[ "$U2_ENABLED" == "false" ]]',
            'case "$FAILURE_INJECTION" in',
            'canary_namespace "$RUN_ID" "$RUN_ATTEMPT"',
        ):
            self.assertIn(token, gate_run, token)
        self.assertNotIn("github.event_name !=", gate_run)

    def test_u2_canary_harness_namespace_and_cleanup_are_exact_run_owned(self):
        workflow = CANARY_HARNESS_WORKFLOW.read_text()
        tree = self._yaml_tree(workflow)
        self.assertIn("gate", tree["jobs"])
        cleanup = tree["jobs"]["cleanup"]
        self.assertEqual(cleanup["if"], "always()")
        cleanup_text = self._job_block(workflow, "cleanup")
        for token in (
            'u2-canary-%s-attempt-%s',
            'GITHUB_RUN_ID',
            'GITHUB_RUN_ATTEMPT',
            'actions/runs/${GITHUB_RUN_ID}/artifacts',
            'actions/artifacts/${artifact_id}',
            '--method DELETE',
            'workflow_run.id',
            '"$actual_name" == "$expected_name"',
        ):
            self.assertIn(token, cleanup_text, token)
        self.assertIn("canary_namespace }}-verification", workflow)
        self.assertIn("$RUNNER_TEMP/$CANARY_NAMESPACE", workflow)
        self.assertNotIn("*", cleanup_text.replace("${CANARY_NAMESPACE}-verification", ""))

        for forbidden in (
            "gh release",
            "gh api .*releases",
            "git push",
            "git update-ref",
            "refs/tags/",
            "contents: write",
            "TVBOX_RELEASE_TOKEN",
            "release-production",
            "update.json",
            "rulesets",
            "policies",
            "--cleanup-tag",
        ):
            self.assertNotIn(forbidden, workflow, forbidden)

    def test_u2_canary_harness_calls_same_rc_pipeline_with_exact_identity(self):
        workflow = CANARY_HARNESS_WORKFLOW.read_text()
        tree = self._yaml_tree(workflow)
        build = tree["jobs"]["build_rc"]
        self.assertEqual(build["uses"], "./.github/workflows/rc-pipeline.yml")
        self.assertIn("needs", build)
        self.assertEqual(build["with"]["release_sha"], "${{ needs.gate.outputs.expected_sha }}")
        self.assertEqual(build["with"]["source_sha"], "${{ needs.gate.outputs.expected_sha }}")
        self.assertEqual(build["with"]["mode"], "manual-local")
        for field in (
            "upstream_sha",
            "upstream_version",
            "upstream_code",
            "expected_version_name",
            "expected_version_code",
            "release_debt",
            "candidate_pr",
            "provenance_marker",
        ):
            self.assertIn(field, build["with"], field)
            self.assertEqual(str(build["with"][field]).strip("'\""), "")
        self.assertNotIn("secrets", build)
        self.assertNotIn("environment", build)
        self.assertEqual(build["permissions"]["actions"], "read")
        self.assertEqual(build["permissions"]["id-token"], "write")
        self.assertEqual(build["permissions"]["attestations"], "write")

        verify = tree["jobs"]["verify"]
        verify_text = self._job_block(workflow, "verify")
        self.assertEqual(verify["permissions"]["actions"], "read")
        self.assertEqual(verify["permissions"]["attestations"], "read")
        for token in (
            "actions/download-artifact@",
            "actions/upload-artifact@",
            "signed_artifact_id",
            "signed_sha256",
            "signer_sha256",
            "apksigner",
            "signer-result.json",
            "gh attestation verify",
            "https://slsa.dev/provenance/v1",
            "https://slashinchi.github.io/TVBoxOS-Mobile/tvbox-release-identity/v2",
            r"^https://github\.com/slashinchi/TVBoxOS-Mobile/\.github/workflows/rc-pipeline\.yml@refs/heads/patched$",
            "verification.json",
        ):
            self.assertIn(token, verify_text, token)
        self.assertEqual(verify_text.count("--cert-identity-regex"), 2)
        self.assertNotIn("secrets.", verify_text)
        self.assertNotIn("TVBOX_KEY", verify_text)

    def test_u2_canary_gate_script_accepts_only_safe_inputs_and_builds_namespace(self):
        workflow = CANARY_HARNESS_WORKFLOW.read_text()
        gate = self._job_block(workflow, "gate")
        gate_run = gate[gate.index("run: |") :]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            fake_git = fake_bin / "git"
            expected = "a" * 40
            fake_git.write_text(
                "#!/usr/bin/env bash\n"
                "if [[ \"${1:-}\" == \"ls-remote\" ]]; then\n"
                f"  printf '%s\\trefs/heads/patched\\n' '{expected}'\n"
                "  exit 0\n"
                "fi\n"
                "exit 99\n"
            )
            fake_git.chmod(0o755)
            output = root / "github-output"
            env = {
                **os.environ,
                "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                "GITHUB_OUTPUT": str(output),
                "EVENT": "workflow_dispatch",
                "ACTOR": "slashinchi",
                "REF": "refs/heads/patched",
                "EXPECTED_SHA": expected,
                "GITHUB_SHA": expected,
                "U2_ENABLED": "false",
                "FAILURE_INJECTION": "none",
                "RUN_ID": "12345",
                "RUN_ATTEMPT": "2",
                "GITHUB_SERVER_URL": "https://github.com",
                "GITHUB_REPOSITORY": "slashinchi/TVBoxOS-Mobile",
            }
            result = subprocess.run(
                ["bash", "-c", gate_run],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            written = output.read_text()
            self.assertIn("expected_sha=" + expected, written)
            self.assertIn("canary_namespace=u2-canary-12345-attempt-2", written)

            for field, value in (("ACTOR", "intruder"), ("REF", "refs/heads/main"), ("U2_ENABLED", "true")):
                output.write_text("")
                env[field] = value
                result = subprocess.run(
                    ["bash", "-c", gate_run],
                    cwd=ROOT,
                    env=env,
                    text=True,
                    capture_output=True,
                )
                self.assertNotEqual(result.returncode, 0, field)
                env[field] = {"ACTOR": "slashinchi", "REF": "refs/heads/patched", "U2_ENABLED": "false"}[field]

            invalid_cases = (
                ("EVENT", "push"),
                ("EXPECTED_SHA", "short"),
                ("GITHUB_SHA", "b" * 40),
                ("FAILURE_INJECTION", "unapproved"),
            )
            for field, value in invalid_cases:
                with self.subTest(field=field):
                    output.write_text("")
                    env[field] = value
                    result = subprocess.run(
                        ["bash", "-c", gate_run],
                        cwd=ROOT,
                        env=env,
                        text=True,
                        capture_output=True,
                    )
                    self.assertNotEqual(result.returncode, 0, field)
                    env[field] = {
                        "EVENT": "workflow_dispatch",
                        "EXPECTED_SHA": expected,
                        "GITHUB_SHA": expected,
                        "FAILURE_INJECTION": "none",
                    }[field]

    def test_u2_intent_is_mutually_exclusive_and_cross_job_identity_is_explicit(self):
        workflow = (ROOT / ".github/workflows/u2-release.yml").read_text()
        tree = self._yaml_tree(workflow)
        jobs = tree["jobs"]
        gate = jobs["gate"]
        gate_outputs = gate["outputs"]
        self.assertIn("intent", gate_outputs)
        self.assertIn("noop", gate_outputs)
        gate_run = self._job_block(workflow, "gate")
        self.assertIn('case "$INPUT_INTENT" in', gate_run)
        for intent in ("release", "recover", "noop-smoke"):
            self.assertIn(intent, gate_run)
        self.assertIn("intent=$INPUT_INTENT", gate_run)

        for job_id in ("qualify", "prep"):
            self.assertIn("intent", jobs[job_id]["outputs"], job_id)
            self.assertIn("noop", jobs[job_id]["outputs"], job_id)
            self.assertIn("INTENT", self._job_block(workflow, job_id), job_id)

        summary = jobs["rc_summary"]
        self.assertIn("INTENT", summary["outputs"])
        self.assertIn("NOOP", summary["outputs"])
        summary_text = self._job_block(workflow, "rc_summary")
        self.assertIn("needs.qualify.outputs.intent", summary_text)
        self.assertIn("needs.qualify.outputs.noop", summary_text)

        watch = self._job_block(workflow, "watch_approval")
        self.assertIn("needs.rc_summary.outputs.INTENT", watch)
        self.assertIn("needs.rc_summary.outputs.NOOP", watch)

        publish = jobs["publish"]
        self.assertIn("outputs", publish)
        self.assertIn("intent", publish["outputs"])
        self.assertIn("noop", publish["outputs"])
        publish_text = self._job_block(workflow, "publish")
        self.assertIn("needs.rc_summary.outputs.INTENT", publish_text)
        self.assertIn("needs.rc_summary.outputs.NOOP", publish_text)

    def test_u2_noop_smoke_has_a_read_only_dependency_barrier(self):
        workflow = (ROOT / ".github/workflows/u2-release.yml").read_text()
        tree = self._yaml_tree(workflow)
        jobs = tree["jobs"]
        for job_id in ("prep", "build_rc", "rc_summary", "watch_approval", "publish"):
            condition = str(jobs[job_id].get("if", ""))
            self.assertIn("needs.qualify.outputs.noop != 'true'", condition, job_id)
            self.assertIn("needs.qualify.outputs.intent != 'noop-smoke'", condition, job_id)

        qualify = self._job_block(workflow, "qualify")
        for token in (
            'INTENT: ${{ needs.gate.outputs.intent }}',
            'if [[ "$INTENT" == "noop-smoke" ]]',
            'NOOP=true',
            'INTENT" == "noop-smoke"',
            "baseline",
            'bash "$trusted_root/scripts/u2_qualify.sh"',
        ):
            self.assertIn(token, qualify, token)
        self.assertIn("return 0", qualify)
        watcher = qualify[qualify.index("watch_debt()") : qualify.index("# Strict U1 qualification")]
        self.assertIn('[[ "$INTENT" == "noop-smoke" || "$NOOP" == "true" ]]', watcher)
        debt_watcher = self._job_block(workflow, "debt_watcher")
        self.assertIn("gh issue create", debt_watcher)

        for job_id in ("prep", "build_rc", "publish"):
            text = self._job_block(workflow, job_id)
            self.assertNotIn('if: always()', text)

    def test_u2_promote_revalidates_live_baseline_and_version_collision(self):
        workflow = (ROOT / ".github/workflows/u2-release.yml").read_text()
        tree = self._yaml_tree(workflow)
        publish_steps = tree["jobs"]["publish"]["steps"]
        names = [step.get("name", "") for step in publish_steps]
        preflight_index = names.index("Preflight verified release metadata")
        promote_index = names.index("Promote patched to exact release SHA (CAS)")
        self.assertLess(preflight_index, promote_index)

        preflight = publish_steps[preflight_index]
        self.assertIn("baseline_tag", str(preflight))
        self.assertIn("baseline_target", str(preflight))
        self.assertIn("current_version", str(preflight))
        self.assertIn("current_update_digest", str(preflight))
        self.assertIn("current_ledger_digest", str(preflight))

        promote = publish_steps[promote_index]
        promote_text = promote["run"]
        for token in (
            "PREFLIGHT_BASELINE_TAG",
            "PREFLIGHT_BASELINE_TARGET",
            "PREFLIGHT_CURRENT_VERSION",
            "PREFLIGHT_UPDATE_DIGEST",
            "PREFLIGHT_LEDGER_DIGEST",
            "canonical-release-baseline",
            "parse-update-metadata",
            "monotonic-compare",
            "version collision",
            "current update.json",
            "current verified-releases.json",
        ):
            self.assertIn(token, promote_text, token)
        live_read = promote_text.index("git ls-remote")
        decision = promote_text.index('if [[ "$current" == "$RELEASE_SHA" ]]')
        self.assertLess(live_read, decision)
        self.assertIn("refusing to continue", promote_text)

    def test_u2_freezes_release_identity_after_first_operation_and_reuses_it(self):
        workflow = (ROOT / ".github/workflows/u2-release.yml").read_text()
        tree = self._yaml_tree(workflow)
        steps = tree["jobs"]["publish"]["steps"]
        names = [step.get("name", "") for step in steps]
        create_index = names.index("Create or reconcile draft Release with exact identity")
        self.assertIn("Freeze Release identity after first draft/asset operation", names)
        freeze_index = names.index("Freeze Release identity after first draft/asset operation")
        attach_index = names.index("Attach missing assets only (no clobber)")
        revalidate_index = names.index("Revalidate frozen Release identity after asset operation")
        verify_index = names.index("Verify both assets before publish (API digest + download bytes)")
        publish_index = names.index("Publish verified draft")
        self.assertLess(create_index, freeze_index)
        self.assertLess(freeze_index, attach_index)
        self.assertLess(attach_index, revalidate_index)
        self.assertLess(revalidate_index, verify_index)
        self.assertLess(verify_index, publish_index)

        freeze = str(steps[freeze_index])
        for token in (
            "gh release view",
            "git/ref/tags",
            "tag_target_sha",
            "targetCommitish",
            "EXPECTED_VERSION",
            "EXPECTED_APK",
            "update_digest",
            "exact target",
            "asset",
            "GITHUB_OUTPUT",
        ):
            self.assertIn(token, freeze, token)
        self.assertIn("frozen_tag", freeze)
        self.assertIn("frozen_target_sha", freeze)

        revalidate = str(steps[revalidate_index])
        for token in (
            "gh release view",
            "git/ref/tags",
            "FROZEN_TAG",
            "FROZEN_TARGET_SHA",
            "FROZEN_VERSION",
            "FROZEN_APK_DIGEST",
            "FROZEN_UPDATE_DIGEST",
            "exactly 2 assets",
            "fail closed",
        ):
            self.assertIn(token, revalidate, token)

        later_steps = steps[attach_index:]
        later_text = "\n".join(str(step) for step in later_steps)
        for token in (
            "steps.freeze.outputs.frozen_tag",
            "steps.freeze.outputs.frozen_target_sha",
            "steps.freeze.outputs.frozen_version",
            "steps.freeze.outputs.frozen_apk_digest",
            "steps.freeze.outputs.frozen_update_digest",
        ):
            self.assertIn(token, later_text, token)

    def test_u2_publish_forbids_publish_command_upload_clobber_tag_movement_and_second_build(self):
        workflow = (ROOT / ".github/workflows/u2-release.yml").read_text()
        tree = self._yaml_tree(workflow)
        steps = tree["jobs"]["publish"]["steps"]
        run_text = "\n".join(step.get("run", "") for step in steps)
        self.assertNotIn("gh release publish", run_text)
        attach = next(step for step in steps if step.get("name") == "Attach missing assets only (no clobber)")
        self.assertIn("gh release upload", attach.get("run", ""))
        self.assertNotIn("--clobber", attach.get("run", ""))
        self.assertNotIn("./gradlew", run_text)
        self.assertNotIn("assembleRelease", run_text)
        self.assertNotIn("git tag -f", run_text)
        self.assertNotIn("git update-ref", run_text)
        push_lines = [
            line
            for step in steps
            for line in step.get("run", "").splitlines()
            if "git push" in line
        ]
        self.assertNotIn("refs/tags/", "\n".join(push_lines))
        self.assertEqual(run_text.count("actions/artifacts/${{ needs.build_rc.outputs.signed_artifact_id }}/zip"), 1)

    def test_u2_manual_source_identity_is_used_for_all_read_only_checkouts(self):
        workflow = (ROOT / ".github/workflows/u2-release.yml").read_text()
        tree = self._yaml_tree(workflow)
        jobs = tree["jobs"]

        qualify_checkout = jobs["qualify"]["steps"][0]["with"]["ref"]
        watch_checkout = jobs["watch_approval"]["steps"][0]["with"]["ref"]
        publish_checkout = jobs["publish"]["steps"][0]["with"]["ref"]
        self.assertEqual(qualify_checkout, "${{ needs.gate.outputs.source_sha }}")
        self.assertEqual(watch_checkout, "${{ needs.rc_summary.outputs.RELEASE_SHA }}")
        self.assertEqual(publish_checkout, "${{ needs.rc_summary.outputs.RELEASE_SHA }}")
        for ref in (qualify_checkout, watch_checkout, publish_checkout):
            self.assertNotEqual(ref, "refs/heads/patched")

    def test_u2_disabled_noop_smoke_gate_is_executable_and_enters_read_only_path(self):
        workflow = (ROOT / ".github/workflows/u2-release.yml").read_text()
        gate_run = self._yaml_tree(workflow)["jobs"]["gate"]["steps"][0]["run"]
        expected = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            fake_git = fake_bin / "git"
            fake_git.write_text(
                "#!/usr/bin/env bash\n"
                "if [[ \"$1\" == \"ls-remote\" ]]; then\n"
                f"  printf '%s\\trefs/heads/patched\\n' '{expected}'\n"
                "  exit 0\n"
                "fi\n"
                "exec /usr/bin/git \"$@\"\n"
            )
            fake_git.chmod(0o755)
            output = root / "github-output"
            env = {
                **os.environ,
                "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                "GITHUB_OUTPUT": str(output),
                "U2_ENABLED": "false",
                "NOOP_CONFIG": "false",
                "EVENT": "workflow_dispatch",
                "ACTOR": "slashinchi",
                "REF": "refs/heads/patched",
                "INPUT_INTENT": "noop-smoke",
                "EXPECTED_SHA": expected,
                "GITHUB_SHA": expected,
                "REPO": "slashinchi/TVBoxOS-Mobile",
            }
            result = subprocess.run(
                ["bash", "-c", gate_run],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            output_text = output.read_text()
            self.assertIn("enabled=true", output_text)
            self.assertIn("mode=manual-noop", output_text)
            self.assertIn("source_sha=" + expected, output_text)
            self.assertIn("intent=noop-smoke", output_text)
            self.assertIn("noop=true", output_text)
            for intent in ("release", "recover"):
                output.write_text("")
                env["INPUT_INTENT"] = intent
                result = subprocess.run(
                    ["bash", "-c", gate_run],
                    cwd=ROOT,
                    env=env,
                    text=True,
                    capture_output=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("enabled=false", output.read_text())

    def test_u2_recovery_forward_requires_recover_intent_and_peeled_tag_target(self):
        workflow = (ROOT / ".github/workflows/u2-release.yml").read_text()
        tree = self._yaml_tree(workflow)
        publish = tree["jobs"]["publish"]
        promote = next(
            step for step in publish["steps"]
            if step.get("name") == "Promote patched to exact release SHA (CAS)"
        )
        promote_text = str(promote)
        promote_run = promote["run"]
        self.assertIn("INTENT", promote["env"])
        self.assertEqual(promote["env"]["INTENT"], "${{ needs.rc_summary.outputs.INTENT }}")
        self.assertIn('elif [[ "$INTENT" == "recover" ]] && git merge-base --is-ancestor', promote_run)
        self.assertNotRegex(promote_run, r"elif git merge-base --is-ancestor")
        local_baseline = promote_run.index('git fetch --no-tags origin "+refs/heads/patched:refs/heads/patched"')
        current_read = promote_run.index('current=$(git rev-parse refs/heads/patched)')
        self.assertLess(local_baseline, current_read)
        self.assertIn("refs/tags/${tag}^{}", promote_run)
        self.assertIn("peeled", promote_text)
        self.assertIn('"$tag_target_sha" == "$RELEASE_SHA"', promote_run)

        for step_name in (
            "Create or reconcile draft Release with exact identity",
            "Freeze Release identity after first draft/asset operation",
            "Revalidate frozen Release identity after asset operation",
            "Publish verified draft",
        ):
            step = next(step for step in publish["steps"] if step.get("name") == step_name)
            text = str(step)
            self.assertIn("peeled", text, step_name)
            self.assertRegex(text, r"refs/tags/\$\{(?:tag|FROZEN_TAG)\}\^\{\}", step_name)
        create = next(
            step for step in publish["steps"]
            if step.get("name") == "Create or reconcile draft Release with exact identity"
        )
        self.assertLess(
            create["run"].index("refs/tags/${tag}^{}"),
            create["run"].index('gh release create "$tag"'),
        )

    def test_u2_noop_has_a_separate_issue_watcher_and_no_issue_permission_on_qualify(self):
        workflow = (ROOT / ".github/workflows/u2-release.yml").read_text()
        tree = self._yaml_tree(workflow)
        jobs = tree["jobs"]
        self.assertNotIn("issues", jobs["qualify"]["permissions"])
        self.assertNotIn("gh issue", self._job_block(workflow, "qualify"))
        self.assertIn("debt_watcher", jobs)

        watcher = jobs["debt_watcher"]
        watcher_if = str(watcher["if"])
        for token in (
            "needs.gate.outputs.intent != 'noop-smoke'",
            "needs.gate.outputs.noop != 'true'",
            "needs.gate.outputs.mode == 'auto-upstream'",
        ):
            self.assertIn(token, watcher_if, token)
        watcher_text = self._job_block(workflow, "debt_watcher")
        self.assertIn("gh issue create", watcher_text)
        self.assertIn("gh issue list", watcher_text)
        self.assertEqual(
            watcher["steps"][0]["with"]["ref"],
            "${{ needs.qualify.outputs.source_sha }}",
        )

        for job_id in ("prep", "build_rc", "rc_summary", "watch_approval", "publish"):
            condition = str(jobs[job_id].get("if", ""))
            self.assertIn("noop", condition, job_id)
            self.assertIn("noop-smoke", condition, job_id)

    def _run_tag_target_resolver(self, output, object_type, status=0):
        workflow = (ROOT / ".github/workflows/u2-release.yml").read_text()
        tree = self._yaml_tree(workflow)
        promote = next(
            step for step in tree["jobs"]["publish"]["steps"]
            if step.get("name") == "Promote patched to exact release SHA (CAS)"
        )
        match = re.search(
            r"(?ms)^[ \t]*resolve_tag_target\(\) \{\n.*?^[ \t]*}\n",
            promote["run"],
        )
        self.assertIsNotNone(match, "typed tag resolver is missing from promote")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            fake_git = fake_bin / "git"
            fake_git.write_text(
                "#!/usr/bin/env bash\n"
                "if [[ \"${1:-}\" == \"ls-remote\" ]]; then\n"
                "  printf '%s' \"${TAG_OUTPUT-}\"\n"
                "  exit \"${TAG_STATUS:-0}\"\n"
                "fi\n"
                "exit 99\n"
            )
            fake_git.chmod(0o755)
            env = {
                **os.environ,
                "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                "TAG_OUTPUT": output,
                "TAG_OBJECT_TYPE": object_type,
                "TAG_STATUS": str(status),
            }
            return subprocess.run(
                [
                    "bash", "-c",
                    match.group(0)
                    + '\nresolve_tag_target "remote" "vtest" "$TAG_OBJECT_TYPE"\n',
                ],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
            )

    def test_u2_tag_resolver_uses_peeled_commit_for_annotated_tag(self):
        tag_object = "a" * 40
        commit = "b" * 40
        output = (
            f"{tag_object}\trefs/tags/vtest\n"
            f"{commit}\trefs/tags/vtest^{{}}\n"
        )
        result = self._run_tag_target_resolver(output, "tag")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, commit + "\n")

    def test_u2_tag_resolver_accepts_direct_commit_for_lightweight_tag(self):
        commit = "c" * 40
        result = self._run_tag_target_resolver(
            f"{commit}\trefs/tags/vtest\n",
            "commit",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, commit + "\n")

    def test_u2_tag_resolver_rejects_tag_objects_and_malformed_remote_output(self):
        tag_object = "d" * 40
        commit = "e" * 40
        cases = [
            ("tag", f"{tag_object}\trefs/tags/vtest\n"),
            ("commit", ""),
            ("commit", f"{commit}\trefs/tags/vtest\n{tag_object}\trefs/tags/vtest\n"),
            ("commit", f"{commit}\trefs/tags/vtest\n{tag_object}\trefs/tags/other\n"),
            ("commit", f"not-a-sha\trefs/tags/vtest\n"),
            ("unknown", f"{commit}\trefs/tags/vtest\n"),
            (
                "commit",
                f"{commit}\trefs/tags/vtest\n{tag_object}\trefs/tags/vtest^{{}}\n",
            ),
        ]
        for object_type, output in cases:
            with self.subTest(object_type=object_type, output=output):
                result = self._run_tag_target_resolver(output, object_type)
                self.assertNotEqual(result.returncode, 0, result.stdout)

    def test_u2_all_tag_identity_checks_use_typed_peeled_or_direct_resolver(self):
        workflow = (ROOT / ".github/workflows/u2-release.yml").read_text()
        tree = self._yaml_tree(workflow)
        steps = tree["jobs"]["publish"]["steps"]
        names = {
            "Promote patched to exact release SHA (CAS)": '"$tag_target_sha" == "$RELEASE_SHA"',
            "Create or reconcile draft Release with exact identity": '"$tag_target_sha" == "$RELEASE_SHA"',
            "Freeze Release identity after first draft/asset operation": '"$tag_target_sha" == "$RELEASE_SHA"',
            "Revalidate frozen Release identity after asset operation": '"$tag_target_sha" == "$FROZEN_TARGET_SHA"',
            "Publish verified draft": '"$tag_target_sha" == "$FROZEN_TARGET_SHA"',
        }
        resolution_text = []
        for name, target_check in names.items():
            step = next(step for step in steps if step.get("name") == name)
            run = step["run"]
            resolution_text.append(run)
            self.assertIn("resolve_tag_target()", run, name)
            self.assertIn("object.type", run, name)
            self.assertIn("refs/tags/", run, name)
            self.assertIn("^{}", run, name)
            self.assertIn(target_check, run, name)
        all_resolution = "\n".join(resolution_text)
        self.assertNotIn("tag_target_sha=$(git ls-remote", all_resolution)
        self.assertIn('case "$object_type" in', all_resolution)
        self.assertIn("tag)", all_resolution)
        self.assertIn("commit)", all_resolution)


if __name__ == "__main__":
    unittest.main(verbosity=2)
