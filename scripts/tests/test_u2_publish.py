import hashlib
import json
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.u2_publish import (
    expected_asset_set,
    reconcile_draft_assets,
    reconcile_draft_decision,
    immutable_verified,
    verify_release_assets,
    verify_remote_metadata,
    monotonic_metadata_next,
    verify_delivery_url,
    build_update_json,
    extract_signed_apk,
    incident_key,
    incident_satisfied,
    RELEASE_TAG_RE,
)

ROOT = Path(__file__).parents[2]

VERSION = "2.1.27.1"
TAG = f"v{VERSION}"
TARGET = "a" * 40
APK_DIGEST = "b" * 64
UPDATE_DIGEST = "c" * 64
APK_NAME = f"TVBox-Mobile-v{VERSION}.apk"


def _draft(assets, is_draft=True, tag=TAG, tag_target_sha=TARGET, target_commitish=TARGET):
    return {
        "tagName": tag,
        "targetCommitish": target_commitish,
        "tagTargetSha": tag_target_sha,
        "isDraft": is_draft,
        "assets": assets,
    }


def _asset(name, digest):
    return {"name": name, "digest": digest}


class U2PublishContractTests(unittest.TestCase):
    def test_expected_asset_set_is_exact_version_contract(self):
        self.assertEqual(
            expected_asset_set("2.1.27.1"),
            {"TVBox-Mobile-v2.1.27.1.apk", "update.json"},
        )
        with self.assertRaises(ValueError):
            expected_asset_set("v2.1.27.1")
        with self.assertRaises(ValueError):
            expected_asset_set("2.1.27")

    def test_reconcile_draft_assets_fails_closed_on_any_deviation(self):
        digests = {APK_NAME: APK_DIGEST, "update.json": UPDATE_DIGEST}
        draft = {"tag_name": TAG, "assets": [
            _asset(APK_NAME, APK_DIGEST),
            _asset("update.json", UPDATE_DIGEST),
        ]}
        self.assertEqual(reconcile_draft_assets(draft, VERSION, digests), "exact")
        missing = {"tag_name": TAG, "assets": draft["assets"][:1]}
        self.assertEqual(reconcile_draft_assets(missing, VERSION, digests), "incomplete")
        extra = {"tag_name": TAG, "assets": draft["assets"] + [_asset("stale.txt", "d" * 64)]}
        self.assertEqual(reconcile_draft_assets(extra, VERSION, digests), "unexpected-asset")
        wrong = {"tag_name": TAG, "assets": [
            _asset(APK_NAME, "f" * 64),
            _asset("update.json", UPDATE_DIGEST),
        ]}
        self.assertEqual(reconcile_draft_assets(wrong, VERSION, digests), "digest-mismatch")
        self.assertEqual(reconcile_draft_assets({}, VERSION, digests), "incomplete")

    def test_reconcile_decision_exact_reuse(self):
        draft = _draft([_asset(APK_NAME, f"sha256:{APK_DIGEST}"), _asset("update.json", f"sha256:{UPDATE_DIGEST}")])
        self.assertEqual(
            reconcile_draft_decision(draft, VERSION, TAG, TARGET, APK_DIGEST, UPDATE_DIGEST),
            "exact-reuse",
        )

    def test_reconcile_decision_repair_missing_any_expected_asset(self):
        missing_apk = _draft([_asset("update.json", f"sha256:{UPDATE_DIGEST}")])
        self.assertEqual(
            reconcile_draft_decision(missing_apk, VERSION, TAG, TARGET, APK_DIGEST, UPDATE_DIGEST),
            "repair-missing",
        )
        missing_update = _draft([_asset(APK_NAME, f"sha256:{APK_DIGEST}")])
        self.assertEqual(
            reconcile_draft_decision(missing_update, VERSION, TAG, TARGET, APK_DIGEST, UPDATE_DIGEST),
            "repair-missing",
        )
        empty_draft = _draft([])
        self.assertEqual(
            reconcile_draft_decision(empty_draft, VERSION, TAG, TARGET, APK_DIGEST, UPDATE_DIGEST),
            "repair-missing",
        )

    def test_reconcile_decision_rejects_bad_identity(self):
        wrong_tag = _draft([_asset(APK_NAME, APK_DIGEST), _asset("update.json", UPDATE_DIGEST)], tag="v2.1.26.1")
        self.assertEqual(
            reconcile_draft_decision(wrong_tag, VERSION, TAG, TARGET, APK_DIGEST, UPDATE_DIGEST),
            "reject-identity",
        )
        wrong_sha = _draft([_asset(APK_NAME, APK_DIGEST), _asset("update.json", UPDATE_DIGEST)], tag_target_sha="f" * 40)
        self.assertEqual(
            reconcile_draft_decision(wrong_sha, VERSION, TAG, TARGET, APK_DIGEST, UPDATE_DIGEST),
            "reject-identity",
        )
        branch_target = _draft(
            [_asset(APK_NAME, APK_DIGEST), _asset("update.json", UPDATE_DIGEST)],
            tag_target_sha=TARGET,
            target_commitish="main",
        )
        self.assertEqual(
            reconcile_draft_decision(branch_target, VERSION, TAG, TARGET, APK_DIGEST, UPDATE_DIGEST),
            "reject-identity",
        )

    def test_reconcile_decision_rejects_not_draft(self):
        published = _draft([_asset(APK_NAME, APK_DIGEST), _asset("update.json", UPDATE_DIGEST)], is_draft=False)
        self.assertEqual(
            reconcile_draft_decision(published, VERSION, TAG, TARGET, APK_DIGEST, UPDATE_DIGEST),
            "reject-not-draft",
        )
        missing_flag = _draft([_asset(APK_NAME, APK_DIGEST), _asset("update.json", UPDATE_DIGEST)])
        missing_flag.pop("isDraft", None)
        self.assertEqual(
            reconcile_draft_decision(missing_flag, VERSION, TAG, TARGET, APK_DIGEST, UPDATE_DIGEST),
            "reject-not-draft",
        )

    def test_reconcile_decision_rejects_wrong_or_extra_assets(self):
        wrong_apk = _draft([_asset(APK_NAME, "f" * 64), _asset("update.json", UPDATE_DIGEST)])
        self.assertEqual(
            reconcile_draft_decision(wrong_apk, VERSION, TAG, TARGET, APK_DIGEST, UPDATE_DIGEST),
            "reject-digest-mismatch",
        )
        wrong_update = _draft([_asset(APK_NAME, APK_DIGEST), _asset("update.json", "f" * 64)])
        self.assertEqual(
            reconcile_draft_decision(wrong_update, VERSION, TAG, TARGET, APK_DIGEST, UPDATE_DIGEST),
            "reject-digest-mismatch",
        )
        extra = _draft([_asset(APK_NAME, APK_DIGEST), _asset("update.json", UPDATE_DIGEST), _asset("stale.txt", "d" * 64)])
        self.assertEqual(
            reconcile_draft_decision(extra, VERSION, TAG, TARGET, APK_DIGEST, UPDATE_DIGEST),
            "reject-extra-asset",
        )
        malformed = _draft([_asset(APK_NAME, "zz"), _asset("update.json", UPDATE_DIGEST)])
        self.assertEqual(
            reconcile_draft_decision(malformed, VERSION, TAG, TARGET, APK_DIGEST, UPDATE_DIGEST),
            "reject-digest-mismatch",
        )

    def test_reconcile_decision_rejects_empty_update_digest(self):
        draft = _draft([_asset(APK_NAME, APK_DIGEST), _asset("update.json", UPDATE_DIGEST)])
        with self.assertRaises(ValueError):
            reconcile_draft_decision(draft, VERSION, TAG, TARGET, APK_DIGEST, "")

    def test_reconcile_decision_requires_standard_tag_unless_allowed(self):
        canary_tag = "u2-canary-123-attempt1"
        draft = _draft([_asset(APK_NAME, f"sha256:{APK_DIGEST}"), _asset("update.json", f"sha256:{UPDATE_DIGEST}")], tag=canary_tag)
        # Production path (default) must reject the nonstandard tag.
        self.assertEqual(
            reconcile_draft_decision(draft, VERSION, canary_tag, TARGET, APK_DIGEST, UPDATE_DIGEST),
            "reject-version",
        )
        # Harness path (explicit opt-in) allows it and still checks identity.
        self.assertEqual(
            reconcile_draft_decision(draft, VERSION, canary_tag, TARGET, APK_DIGEST, UPDATE_DIGEST,
                                     allow_nonstandard_tag=True),
            "exact-reuse",
        )

    def test_immutable_verified_requires_exact_state(self):
        tag = TAG
        target = TARGET
        base = {"immutable": True, "tag": tag, "target": target, "asset_count": 2}
        self.assertTrue(immutable_verified(base, tag, target))
        self.assertFalse(immutable_verified({**base, "immutable": False}, tag, target))
        self.assertFalse(immutable_verified({**base, "tag": "v2.1.27.2"}, tag, target))
        self.assertFalse(immutable_verified({**base, "target": "f" * 40}, tag, target))
        self.assertFalse(immutable_verified({**base, "asset_count": 3}, tag, target))
        self.assertFalse(immutable_verified(base, "v2.1.27.2", target))
        self.assertFalse(immutable_verified(base, tag, "f" * 40))

    def test_verify_release_assets_checks_api_digests_and_download_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / APK_NAME).write_bytes(b"apk")
            (out / "update.json").write_bytes(b"update")
            apk_local = hashlib.sha256(b"apk").hexdigest()
            update_local = hashlib.sha256(b"update").hexdigest()
            release = {"assets": [
                _asset(APK_NAME, f"sha256:{apk_local}"),
                _asset("update.json", f"sha256:{update_local}"),
            ]}
            result = verify_release_assets(release, VERSION, {APK_NAME: apk_local, "update.json": update_local}, tmp)
            self.assertTrue(result["verified"])
            self.assertEqual(set(result["checked"]), {APK_NAME, "update.json"})

            # API digest mismatch
            bad_api = {"assets": [_asset(APK_NAME, f"sha256:{'f' * 64}"), _asset("update.json", f"sha256:{update_local}")]}
            self.assertFalse(verify_release_assets(bad_api, VERSION, {APK_NAME: apk_local, "update.json": update_local}, tmp)["verified"])

            # Downloaded bytes mismatch
            (out / APK_NAME).write_bytes(b"different-bytes")
            self.assertFalse(verify_release_assets(release, VERSION, {APK_NAME: apk_local, "update.json": update_local}, tmp)["verified"])

            # Missing asset set
            missing = {"assets": [_asset(APK_NAME, f"sha256:{apk_local}")]}
            self.assertFalse(verify_release_assets(missing, VERSION, {APK_NAME: apk_local, "update.json": update_local}, tmp)["verified"])

            # Missing digest field
            nodigest = {"assets": [_asset(APK_NAME, ""), _asset("update.json", f"sha256:{update_local}")]}
            self.assertFalse(verify_release_assets(nodigest, VERSION, {APK_NAME: apk_local, "update.json": update_local}, tmp)["verified"])

    def test_verify_remote_metadata_is_byte_exact(self):
        url = "https://gh.xxooo.cf/https://github.com/slashinchi/TVBoxOS-Mobile/releases/download/v2.1.27.1/TVBox-Mobile-v2.1.27.1.apk"
        canonical = (json.dumps(build_update_json(VERSION, url), sort_keys=True) + "\n").encode()
        self.assertTrue(verify_remote_metadata(canonical, VERSION, url)["verified"])
        self.assertFalse(verify_remote_metadata(b"not json", VERSION, url)["verified"])
        self.assertFalse(verify_remote_metadata(canonical.replace(b"2.1.27.1", b"2.1.26.1"), VERSION, url)["verified"])
        self.assertFalse(verify_remote_metadata(canonical + b"\n", VERSION, url)["verified"])

    def test_monotonic_metadata_never_rolls_back(self):
        current = {"version": "2.1.26.1", "apk_url": "https://example.invalid/old"}
        newer = {"version": "2.1.27.1", "apk_url": "https://example.invalid/new"}
        self.assertEqual(monotonic_metadata_next(current, newer), newer)
        self.assertEqual(monotonic_metadata_next(current, current), current)
        self.assertEqual(monotonic_metadata_next(newer, current), newer)

    def test_verify_delivery_url_binds_proxy_bytes_to_exact_sha(self):
        self.assertTrue(verify_delivery_url(
            url="https://example.invalid/apk",
            expected_sha256="a" * 64,
            fetched_sha256="a" * 64,
        ))
        self.assertFalse(verify_delivery_url(
            url="https://example.invalid/apk",
            expected_sha256="a" * 64,
            fetched_sha256="f" * 64,
        ))

    def test_incident_key_is_identity_bound(self):
        key = incident_key("manual-local", TARGET, VERSION, APK_DIGEST)
        self.assertEqual(key, f"manual-local:{TARGET}:{VERSION}:{APK_DIGEST}")
        with self.assertRaises(ValueError):
            incident_key("BAD", TARGET, VERSION, APK_DIGEST)
        with self.assertRaises(ValueError):
            incident_key("manual-local", "short", VERSION, APK_DIGEST)
        with self.assertRaises(ValueError):
            incident_key("manual-local", TARGET, "2.1.27", APK_DIGEST)
        with self.assertRaises(ValueError):
            incident_key("manual-local", TARGET, VERSION, "zz")

    def test_incident_satisfied_closes_only_when_condition_met(self):
        incident = {
            "kind": "release-delivery",
            "release_tag": TAG,
            "release_target_sha": TARGET,
            "version": VERSION,
            "debt": APK_DIGEST,
        }
        self.assertTrue(incident_satisfied(incident, TAG, TARGET, VERSION, APK_DIGEST, True))
        self.assertFalse(incident_satisfied(incident, TAG, TARGET, VERSION, APK_DIGEST, False))
        self.assertFalse(incident_satisfied(incident, "v2.1.26.1", TARGET, VERSION, APK_DIGEST, True))
        other = {"kind": "stale-rc", "release_tag": TAG, "release_target_sha": TARGET, "version": VERSION, "debt": APK_DIGEST}
        self.assertTrue(incident_satisfied(other, TAG, TARGET, VERSION, APK_DIGEST, None))

    def test_release_tag_re_is_strict(self):
        self.assertTrue(RELEASE_TAG_RE.fullmatch("v2.1.26.1"))
        self.assertTrue(RELEASE_TAG_RE.fullmatch("v2.1.27.10"))
        self.assertFalse(RELEASE_TAG_RE.fullmatch("2.1.26.1"))
        self.assertFalse(RELEASE_TAG_RE.fullmatch("v2.1.26"))
        self.assertFalse(RELEASE_TAG_RE.fullmatch("v2.1.26.1.1"))

    def test_build_update_json_cli_and_extract_signed_apk(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            update_out = tmp_path / "update.json"
            result = subprocess.run(
                [
                    "python3", "scripts/u2_publish.py", "build-update-json",
                    "--version", VERSION,
                    "--apk-url", "https://gh.xxooo.cf/slashinchi/TVBoxOS-Mobile/releases/download/v2.1.27.1/TVBox-Mobile-v2.1.27.1.apk",
                    "--output", str(update_out),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(update_out.read_text())
            self.assertEqual(payload["version"], VERSION)
            zip_path = tmp_path / "artifact.zip"
            with zipfile.ZipFile(zip_path, "w") as z:
                z.writestr("signed-output/signed.apk", b"apk-bytes")
            out_dir = tmp_path / "extracted"
            out_dir.mkdir()
            signed = subprocess.run(
                [
                    "python3", "scripts/u2_publish.py", "extract-signed-apk",
                    "--zip", str(zip_path),
                    "--output-dir", str(out_dir),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
            self.assertEqual(signed.returncode, 0, signed.stderr)
            self.assertTrue(Path(signed.stdout.strip()).is_file())

    def test_reconcile_draft_cli(self):
        def run(draft_json, version=VERSION, update_digest=UPDATE_DIGEST):
            return subprocess.run(
                [
                    "python3", "scripts/u2_publish.py", "reconcile-draft",
                    "--draft", draft_json,
                    "--version", version,
                    "--expected-tag", TAG,
                    "--expected-target-sha", TARGET,
                    "--apk-digest", APK_DIGEST,
                    "--update-digest", update_digest,
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
        good = json.dumps(_draft([_asset(APK_NAME, f"sha256:{APK_DIGEST}"), _asset("update.json", f"sha256:{UPDATE_DIGEST}")]))
        self.assertEqual(json.loads(run(good).stdout)["decision"], "exact-reuse")
        self.assertEqual(json.loads(run(good).stdout)["reuse"], True)
        published = json.loads(good)
        published["isDraft"] = False
        self.assertEqual(json.loads(run(json.dumps(published)).stdout)["decision"], "reject-not-draft")
        wrong_tag = json.dumps(_draft([], tag="v2.1.26.1"))
        self.assertEqual(json.loads(run(wrong_tag).stdout)["decision"], "reject-identity")
        missing_apk = json.dumps(_draft([_asset("update.json", f"sha256:{UPDATE_DIGEST}")]))
        self.assertEqual(json.loads(run(missing_apk).stdout)["decision"], "repair-missing")
        self.assertEqual(json.loads(run(missing_apk).stdout)["reuse"], False)
        extra_asset = json.dumps(_draft([
            _asset(APK_NAME, f"sha256:{APK_DIGEST}"),
            _asset("update.json", f"sha256:{UPDATE_DIGEST}"),
            _asset("stale.txt", "d" * 64),
        ]))
        self.assertEqual(json.loads(run(extra_asset).stdout)["decision"], "reject-extra-asset")
        empty_update = subprocess.run(
            [
                "python3", "scripts/u2_publish.py", "reconcile-draft",
                "--draft", good,
                "--version", VERSION,
                "--expected-tag", TAG,
                "--expected-target-sha", TARGET,
                "--apk-digest", APK_DIGEST,
                "--update-digest", "",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        self.assertNotEqual(empty_update.returncode, 0)

    def test_verify_release_assets_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            apk_bytes = b"cli-apk"
            update_bytes = b"cli-update"
            (out / APK_NAME).write_bytes(apk_bytes)
            (out / "update.json").write_bytes(update_bytes)
            apk_local = hashlib.sha256(apk_bytes).hexdigest()
            update_local = hashlib.sha256(update_bytes).hexdigest()
            release = json.dumps({"assets": [_asset(APK_NAME, f"sha256:{apk_local}"), _asset("update.json", f"sha256:{update_local}")]})
            result = subprocess.run(
                [
                    "python3", "scripts/u2_publish.py", "verify-release-assets",
                    "--release", release,
                    "--version", VERSION,
                    "--apk-digest", apk_local,
                    "--update-digest", update_local,
                    "--download-dir", tmp,
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(json.loads(result.stdout)["verified"])

    def test_verify_remote_metadata_cli_and_incident_key_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            url = "https://gh.xxooo.cf/slashinchi/TVBoxOS-Mobile/releases/download/v2.1.27.1/TVBox-Mobile-v2.1.27.1.apk"
            meta = Path(tmp) / "update.json"
            meta.write_text(json.dumps(build_update_json(VERSION, url), sort_keys=True) + "\n")
            result = subprocess.run(
                [
                    "python3", "scripts/u2_publish.py", "verify-remote-metadata",
                    "--metadata-file", str(meta),
                    "--expected-version", VERSION,
                    "--expected-apk-url", url,
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(json.loads(result.stdout)["verified"])
            key = subprocess.run(
                [
                    "python3", "scripts/u2_publish.py", "incident-key",
                    "--mode", "manual-local",
                    "--source-sha", TARGET,
                    "--version", VERSION,
                    "--debt", APK_DIGEST,
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
            self.assertEqual(key.returncode, 0, key.stderr)
            self.assertEqual(json.loads(key.stdout)["key"], f"manual-local:{TARGET}:{VERSION}:{APK_DIGEST}")

    def test_monotonic_compare_cli(self):
        def run(cur, cand):
            return subprocess.run(
                [
                    "python3", "scripts/u2_publish.py", "monotonic-compare",
                    "--current-version", cur,
                    "--candidate-version", cand,
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
        self.assertEqual(json.loads(run("2.1.26.1", "2.1.27.1").stdout)["newer"], True)
        self.assertEqual(json.loads(run("2.1.27.1", "2.1.26.1").stdout)["newer"], False)
        self.assertEqual(json.loads(run("2.1.27.1", "2.1.27.1").stdout)["newer"], True)
        self.assertNotEqual(run("2.1.27", "2.1.27.1").returncode, 0)
        empty_current = run("", "2.1.27.1")
        self.assertEqual(empty_current.returncode, 0, empty_current.stderr)
        self.assertEqual(json.loads(empty_current.stdout)["newer"], True)
        self.assertNotEqual(run("2.1.26.1", "").returncode, 0)
        self.assertNotEqual(run("2.1.26.1", "bad").returncode, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
