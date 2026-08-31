import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

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
    fresh_integration_replay,
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
            "2.1.27",
            237,
        )
        self.assertEqual(
            parse_provenance_marker(marker),
            {
                "upstream": "a" * 40,
                "candidate": "b" * 40,
                "tree": "c" * 40,
                "upstreamVersion": "2.1.27",
                "upstreamCode": "237",
            },
        )
        with self.assertRaises(ValueError):
            parse_provenance_marker(marker.replace("tree=" + "c" * 40, "tree=short"))

    def test_strict_u1_merge_requires_pr_lineage_and_replay(self):
        upstream = "a" * 40
        candidate = "b" * 40
        tree = "c" * 40
        before = "d" * 40
        after = "e" * 40
        marker = build_provenance_marker(upstream, candidate, tree, "2.1.27", 237)
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
            replay=("clean", tree, tree),
        )

        self.assertTrue(qualified["qualified"])
        self.assertEqual(fresh_integration_replay("clean", tree, tree)["reason"], "replay-match")
        self.assertEqual(fresh_integration_replay("clean", tree, "f" * 40)["reason"], "replay-tree-mismatch")
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
                replay=("clean", tree, tree),
            )["reason"],
            "associated-pr-mismatch",
        )

    def test_manual_integrated_upstream_and_canonical_release_baseline_fail_closed(self):
        sha = "a" * 40
        self.assertEqual(derive_integrated_upstream_sha([sha], {sha}, {sha}), sha)
        with self.assertRaises(ValueError):
            derive_integrated_upstream_sha([sha, "b" * 40], {sha, "b" * 40}, {sha, "b" * 40})
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
        self.assertIn("git/ref/tags/${tag}", promote_text)
        self.assertIn("tag object $tag exists", promote_text)
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
        tag_ref_line = next(l for l in draft_run.splitlines() if "git/ref/tags" in l)
        self.assertNotIn("--silent", tag_ref_line)
        self.assertIn("if tag_target_sha=$(", tag_ref_line)
        self.assertIn("2>/dev/null); then", tag_ref_line)

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
        marker = build_provenance_marker(upstream, candidate, tree, "2.1.27", 237)
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
            "--replay-status", "clean",
            "--replay-tree", tree,
            "--replay-actual-tree", tree,
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
