import json
import unittest
from pathlib import Path

from scripts.u2_publish import (
    expected_asset_set,
    reconcile_draft_assets,
    immutable_verified,
    monotonic_metadata_next,
    verify_delivery_url,
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
