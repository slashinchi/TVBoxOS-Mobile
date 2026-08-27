import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.u2_release import (
    build_provenance_marker,
    build_release_trailers,
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
            "state": "MERGED",
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

    def test_manual_build_wrapper_rejects_arbitrary_target_and_calls_rc_pipeline(self):
        workflow = BUILD_WORKFLOW.read_text()
        self.assertIn("uses: ./.github/workflows/rc-pipeline.yml", workflow)
        self.assertIn("github.actor == 'slashinchi'", workflow)
        self.assertIn("github.ref == 'refs/heads/patched'", workflow)
        self.assertNotIn("github.event.inputs.release_sha", workflow)
        wrapper = workflow[workflow.index("  build-signed-rc:"):workflow.index("  publish-github-release:")]
        self.assertNotIn("actions/checkout", wrapper)
        self.assertNotIn("environment: release-signing", wrapper)

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
        builder = workflow[workflow.index("  build_unsigned:"):workflow.index("  prepare_sign_input:")]
        self.assertIn('export GRADLE_USER_HOME="$RUNNER_TEMP/tvbox-gradle"', builder)
        self.assertNotIn("cache: gradle", builder)
        self.assertNotIn("setup-gradle", builder)

    def test_rc_artifact_contracts_are_flat_and_exact(self):
        workflow = RC_WORKFLOW.read_text()
        self.assertIn("tvbox-u2-build-evidence-", workflow)
        self.assertIn("tvbox-u2-sign-input-", workflow)
        self.assertIn("tvbox-u2-signed-output-", workflow)
        self.assertIn("tvbox-u2-attest-input-", workflow)
        builder = workflow[workflow.index("  build_unsigned:"):workflow.index("  prepare_sign_input:")]
        self.assertIn("build/evidence", builder)
        self.assertIn("legacy-dependencies.lock.json", builder)
        self.assertIn("build-identity.json", builder)
        self.assertNotIn("tvbox-u2-unsigned-", builder)
        self.assertIn("-delete", builder)
        self.assertIn("exactly 6 files", builder)
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
        attestor = workflow[workflow.index("  attest_signed:"):]
        self.assertIn("release-identity-predicate.json", attestor)
        self.assertIn("attest-input", attestor)
        self.assertNotIn("release-identity.txt", attestor)

    def test_rc_attestor_has_no_checkout_or_scripts(self):
        workflow = RC_WORKFLOW.read_text()
        attestor = workflow[workflow.index("  attest_signed:"):]
        self.assertNotIn("actions/checkout", attestor)
        self.assertNotIn("scripts/native_compat.py", attestor)
        self.assertNotIn("scripts/u2_release.py", attestor)
        self.assertNotIn("sudo apt-get", attestor)
        self.assertNotIn("apksigcopier", attestor)
        self.assertIn("subject-path: ${{ runner.temp }}/signed-output/signed.apk", attestor)
        self.assertIn("actions/attest@1e69f48acb82d1966a394da916b4c1698aa569d6 # v4", attestor)
        self.assertNotIn("attest-build-provenance@", attestor)

    def test_rc_identity_creates_evidence_directory_before_writing(self):
        workflow = RC_WORKFLOW.read_text()
        identity = workflow[workflow.index("      - id: identity"):workflow.index("      - id: build")]
        self.assertIn("mkdir -p build/evidence", identity)

    def test_rc_native_compatibility_uses_canonical_report_and_attested_debt(self):
        workflow = RC_WORKFLOW.read_text()
        self.assertIn("scripts/native_compat.py", workflow)
        self.assertIn("native-compat.json", workflow)
        self.assertIn("native_compat_report_sha256", workflow)
        self.assertIn("native_compat_status", workflow)
        self.assertIn("p_align >= 0x4000", workflow)
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

    @staticmethod
    def _git(repo, *args):
        return subprocess.run(
            ["git", "-C", str(repo), *args],
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()


if __name__ == "__main__":
    unittest.main(verbosity=2)
