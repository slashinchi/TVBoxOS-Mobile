import json
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.u2_publish import (
    expected_asset_set,
    reconcile_draft_assets,
    immutable_verified,
    monotonic_metadata_next,
    verify_delivery_url,
    build_update_json,
    extract_signed_apk,
    RELEASE_TAG_RE,
)

ROOT = Path(__file__).parents[2]


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
        digests = {
            "TVBox-Mobile-v2.1.27.1.apk": "a" * 64,
            "update.json": "b" * 64,
        }
        draft = {"tag_name": "v2.1.27.1", "assets": [
            {"name": "TVBox-Mobile-v2.1.27.1.apk", "digest": "a" * 64},
            {"name": "update.json", "digest": "b" * 64},
        ]}
        self.assertEqual(reconcile_draft_assets(draft, "2.1.27.1", digests), "exact")
        missing = {"tag_name": "v2.1.27.1", "assets": draft["assets"][:1]}
        self.assertEqual(reconcile_draft_assets(missing, "2.1.27.1", digests), "incomplete")
        extra = {"tag_name": "v2.1.27.1", "assets": draft["assets"] + [{"name": "stale.txt", "digest": "c" * 64}]}
        self.assertEqual(reconcile_draft_assets(extra, "2.1.27.1", digests), "unexpected-asset")
        wrong = {"tag_name": "v2.1.27.1", "assets": [
            {"name": "TVBox-Mobile-v2.1.27.1.apk", "digest": "f" * 64},
            {"name": "update.json", "digest": "b" * 64},
        ]}
        self.assertEqual(reconcile_draft_assets(wrong, "2.1.27.1", digests), "digest-mismatch")
        self.assertEqual(reconcile_draft_assets({}, "2.1.27.1", digests), "incomplete")

    def test_immutable_verified_requires_exact_state(self):
        tag = "v2.1.27.1"
        target = "a" * 40
        base = {"immutable": True, "tag": tag, "target": target, "asset_count": 2}
        self.assertTrue(immutable_verified(base, tag, target))
        self.assertFalse(immutable_verified({**base, "immutable": False}, tag, target))
        self.assertFalse(immutable_verified({**base, "tag": "v2.1.27.2"}, tag, target))
        self.assertFalse(immutable_verified({**base, "target": "f" * 40}, tag, target))
        self.assertFalse(immutable_verified({**base, "asset_count": 3}, tag, target))
        self.assertFalse(immutable_verified(base, "v2.1.27.2", target))
        self.assertFalse(immutable_verified(base, tag, "f" * 40))

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
                    "--version", "2.1.27.1",
                    "--apk-url", "https://gh.xxooo.cf/slashinchi/TVBoxOS-Mobile/releases/download/v2.1.27.1/TVBox-Mobile-v2.1.27.1.apk",
                    "--output", str(update_out),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(update_out.read_text())
            self.assertEqual(payload["version"], "2.1.27.1")
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
        def run(draft_json, version="2.1.27.1", update_digest=""):
            return subprocess.run(
                [
                    "python3", "scripts/u2_publish.py", "reconcile-draft",
                    "--draft", draft_json,
                    "--version", version,
                    "--expected-tag", f"v{version}",
                    "--expected-target", "a" * 40,
                    "--apk-digest", "b" * 64,
                    "--update-digest", update_digest,
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
        good = json.dumps({
            "tagName": "v2.1.27.1",
            "targetCommitish": "a" * 40,
            "isDraft": True,
            "assets": [
                {"name": "TVBox-Mobile-v2.1.27.1.apk", "digest": f"sha256:{'b' * 64}"},
                {"name": "update.json", "digest": f"sha256:{'c' * 64}"},
            ],
        })
        self.assertEqual(json.loads(run(good).stdout)["reuse"], True)
        published = json.loads(good)
        published["isDraft"] = False
        self.assertEqual(json.loads(run(json.dumps(published)).stdout)["reason"], "not-draft")
        self.assertFalse(json.loads(run(json.dumps(published)).stdout)["reuse"])
        missing_draft_flag = json.loads(good)
        missing_draft_flag.pop("isDraft", None)
        self.assertEqual(json.loads(run(json.dumps(missing_draft_flag)).stdout)["reason"], "not-draft")
        wrong_tag = json.dumps({"tagName": "v2.1.26.1", "targetCommitish": "a" * 40, "isDraft": True, "assets": []})
        self.assertEqual(json.loads(run(wrong_tag).stdout)["reason"], "identity-mismatch")
        missing_asset = json.dumps({
            "tagName": "v2.1.27.1",
            "targetCommitish": "a" * 40,
            "isDraft": True,
            "assets": [{"name": "update.json", "digest": f"sha256:{'c' * 64}"}],
        })
        self.assertEqual(json.loads(run(missing_asset).stdout)["reason"], "incomplete")
        self.assertFalse(json.loads(run(missing_asset).stdout)["reuse"])
        extra_asset = json.dumps({
            "tagName": "v2.1.27.1",
            "targetCommitish": "a" * 40,
            "isDraft": True,
            "assets": [
                {"name": "TVBox-Mobile-v2.1.27.1.apk", "digest": f"sha256:{'b' * 64}"},
                {"name": "update.json", "digest": f"sha256:{'c' * 64}"},
                {"name": "stale.txt", "digest": "d" * 64},
            ],
        })
        self.assertEqual(json.loads(run(extra_asset).stdout)["reason"], "asset-mismatch")

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
