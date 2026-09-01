import hashlib
import json
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts import u2_publish as u2_publish_module
from scripts.u2_publish import (
    expected_asset_set,
    reconcile_draft_assets,
    reconcile_draft_decision,
    immutable_verified,
    released_identity_decision,
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
SIGNER_DIGEST = "d" * 64
SOURCE_SHA = "e" * 40
DEBT_DIGEST = "f" * 64
RUN_ID = "123456"
RUN_ATTEMPT = "2"


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


def _verified_entry():
    return u2_publish_module.verified_release_entry(
        tag=TAG,
        target=TARGET,
        version_name=VERSION,
        version_code=23701,
        asset_sha256=APK_DIGEST,
        update_sha256=UPDATE_DIGEST,
        signer_sha256=SIGNER_DIGEST,
        source_sha=SOURCE_SHA,
        debt=DEBT_DIGEST,
        run_id=RUN_ID,
        run_attempt=RUN_ATTEMPT,
    )


def _versioned_entry(version, version_code, target, source):
    entry = _verified_entry()
    entry.update({
        "tag": f"v{version}",
        "versionName": version,
        "versionCode": version_code,
        "target": target,
        "sourceSha": source,
    })
    return entry


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

    def test_reconcile_decision_uses_target_commitish_sha_for_drafts(self):
        # Drafts have no tag ref; GitHub stores the exact --target SHA in
        # target_commitish. Without an explicit tagTargetSha the decision must
        # fall back to a full-SHA targetCommitish (branch names stay rejected).
        draft = _draft([_asset(APK_NAME, f"sha256:{APK_DIGEST}"), _asset("update.json", f"sha256:{UPDATE_DIGEST}")])
        draft.pop("tagTargetSha", None)
        self.assertEqual(
            reconcile_draft_decision(draft, VERSION, TAG, TARGET, APK_DIGEST, UPDATE_DIGEST),
            "exact-reuse",
        )
        branch_target = json.loads(json.dumps(draft))
        branch_target["targetCommitish"] = "patched"
        self.assertEqual(
            reconcile_draft_decision(branch_target, VERSION, TAG, TARGET, APK_DIGEST, UPDATE_DIGEST),
            "reject-identity",
        )

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

    def test_released_identity_decision_verify_published(self):
        published = _draft([_asset(APK_NAME, f"sha256:{APK_DIGEST}"), _asset("update.json", f"sha256:{UPDATE_DIGEST}")], is_draft=False)
        self.assertEqual(
            released_identity_decision(published, VERSION, TAG, TARGET, APK_DIGEST, UPDATE_DIGEST),
            "verify-published",
        )

    def test_released_identity_decision_rejects_published_missing_assets(self):
        # A published Release in an immutable repository can never accept new
        # assets; missing assets are unrecoverable and must fail closed.
        missing_update = _draft([_asset(APK_NAME, f"sha256:{APK_DIGEST}")], is_draft=False)
        self.assertEqual(
            released_identity_decision(missing_update, VERSION, TAG, TARGET, APK_DIGEST, UPDATE_DIGEST),
            "reject-published-missing-asset",
        )
        missing_apk = _draft([_asset("update.json", f"sha256:{UPDATE_DIGEST}")], is_draft=False)
        self.assertEqual(
            released_identity_decision(missing_apk, VERSION, TAG, TARGET, APK_DIGEST, UPDATE_DIGEST),
            "reject-published-missing-asset",
        )
        empty_published = _draft([], is_draft=False)
        self.assertEqual(
            released_identity_decision(empty_published, VERSION, TAG, TARGET, APK_DIGEST, UPDATE_DIGEST),
            "reject-published-missing-asset",
        )

    def test_released_identity_decision_rejects_bad_published(self):
        wrong_tag = _draft([_asset(APK_NAME, APK_DIGEST), _asset("update.json", UPDATE_DIGEST)], is_draft=False, tag="v2.1.26.1")
        self.assertEqual(
            released_identity_decision(wrong_tag, VERSION, TAG, TARGET, APK_DIGEST, UPDATE_DIGEST),
            "reject-published-identity",
        )
        wrong_sha = _draft([_asset(APK_NAME, APK_DIGEST), _asset("update.json", UPDATE_DIGEST)], is_draft=False, tag_target_sha="f" * 40)
        self.assertEqual(
            released_identity_decision(wrong_sha, VERSION, TAG, TARGET, APK_DIGEST, UPDATE_DIGEST),
            "reject-published-identity",
        )
        wrong_digest = _draft([_asset(APK_NAME, "f" * 64), _asset("update.json", UPDATE_DIGEST)], is_draft=False)
        self.assertEqual(
            released_identity_decision(wrong_digest, VERSION, TAG, TARGET, APK_DIGEST, UPDATE_DIGEST),
            "reject-published-digest-mismatch",
        )
        extra = _draft([_asset(APK_NAME, APK_DIGEST), _asset("update.json", UPDATE_DIGEST), _asset("stale.txt", "d" * 64)], is_draft=False)
        self.assertEqual(
            released_identity_decision(extra, VERSION, TAG, TARGET, APK_DIGEST, UPDATE_DIGEST),
            "reject-published-extra-asset",
        )
        # A draft must never be classified as published-verify.
        draft = _draft([_asset(APK_NAME, APK_DIGEST), _asset("update.json", UPDATE_DIGEST)], is_draft=True)
        self.assertEqual(
            released_identity_decision(draft, VERSION, TAG, TARGET, APK_DIGEST, UPDATE_DIGEST),
            "reject-published-is-draft",
        )
        with self.assertRaises(ValueError):
            released_identity_decision(
                _draft([_asset(APK_NAME, APK_DIGEST), _asset("update.json", UPDATE_DIGEST)], is_draft=False),
                VERSION, TAG, TARGET, APK_DIGEST, "",
            )

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

    def test_verified_release_entry_contains_complete_identity(self):
        entry = _verified_entry()
        self.assertEqual(
            entry,
            {
                "tag": TAG,
                "target": TARGET,
                "versionName": VERSION,
                "versionCode": 23701,
                "assetSha256": APK_DIGEST,
                "updateSha256": UPDATE_DIGEST,
                "signerSha256": SIGNER_DIGEST,
                "sourceSha": SOURCE_SHA,
                "debt": DEBT_DIGEST,
                "runId": RUN_ID,
                "runAttempt": RUN_ATTEMPT,
                "verified": True,
                "tag_ancestor": True,
            },
        )

        invalid = {
            "target": "short",
            "asset_sha256": "zz",
            "update_sha256": "zz",
            "signer_sha256": "zz",
            "source_sha": "short",
            "debt": "zz",
            "version_name": "2.1.27",
            "version_code": 0,
            "run_id": "0",
            "run_attempt": "0",
        }
        for field, value in invalid.items():
            kwargs = {
                "tag": TAG,
                "target": TARGET,
                "version_name": VERSION,
                "version_code": 23701,
                "asset_sha256": APK_DIGEST,
                "update_sha256": UPDATE_DIGEST,
                "signer_sha256": SIGNER_DIGEST,
                "source_sha": SOURCE_SHA,
                "debt": DEBT_DIGEST,
                "run_id": RUN_ID,
                "run_attempt": RUN_ATTEMPT,
            }
            kwargs[field] = value
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    u2_publish_module.verified_release_entry(**kwargs)
        for field, value in {"tag": 123, "version_name": 123, "target": 123}.items():
            kwargs = {
                "tag": TAG,
                "target": TARGET,
                "version_name": VERSION,
                "version_code": 23701,
                "asset_sha256": APK_DIGEST,
                "update_sha256": UPDATE_DIGEST,
                "signer_sha256": SIGNER_DIGEST,
                "source_sha": SOURCE_SHA,
                "debt": DEBT_DIGEST,
                "run_id": RUN_ID,
                "run_attempt": RUN_ATTEMPT,
            }
            kwargs[field] = value
            with self.subTest(field=field, value_type=type(value).__name__):
                with self.assertRaises(ValueError):
                    u2_publish_module.verified_release_entry(**kwargs)

    def test_verified_release_reconcile_is_idempotent_and_rejects_identity_conflict(self):
        entry = _verified_entry()
        appended = u2_publish_module.reconcile_verified_releases([], entry)
        self.assertEqual(appended["action"], "append")
        self.assertEqual(appended["ledger"], [entry])

        replay = u2_publish_module.reconcile_verified_releases(appended["ledger"], entry)
        self.assertEqual(replay["action"], "exact-reuse")
        self.assertEqual(replay["ledger"], [entry])

        conflict = dict(entry, assetSha256="0" * 64)
        with self.assertRaises(ValueError):
            u2_publish_module.reconcile_verified_releases([entry], conflict)
        same_target = dict(entry, tag="v2.1.28.1", versionName="2.1.28.1", versionCode=23801)
        with self.assertRaises(ValueError):
            u2_publish_module.reconcile_verified_releases([entry], same_target)

    def test_verified_release_reconcile_rejects_existing_ledger_order_regression(self):
        descending = [
            _versioned_entry("2.1.28.1", 23801, "1" * 40, "2" * 40),
            _versioned_entry("2.1.27.1", 23701, "3" * 40, "4" * 40),
        ]
        candidate = _versioned_entry("2.1.29.1", 23901, "5" * 40, "6" * 40)
        with self.assertRaises(ValueError):
            u2_publish_module.reconcile_verified_releases(descending, candidate)

    def test_verified_release_reconcile_rejects_legacy_entry_after_complete_entry(self):
        complete = _verified_entry()
        production_legacy = json.loads(
            (ROOT / "gradle/verified-releases.json").read_text()
        )[0]
        legacy_after = dict(
            production_legacy,
            tag="v2.1.28.1",
            versionName="2.1.28.1",
            versionCode=23801,
            target="1" * 40,
        )
        candidate = _versioned_entry("2.1.29.1", 23901, "2" * 40, "3" * 40)
        with self.assertRaisesRegex(ValueError, "legacy"):
            u2_publish_module.reconcile_verified_releases(
                [complete, legacy_after], candidate
            )

    def test_verified_release_reconcile_recovers_same_release_with_new_run_attempt(self):
        prior = dict(_verified_entry(), runId="123456", runAttempt="1")
        replay = dict(prior, runAttempt="2")
        result = u2_publish_module.reconcile_verified_releases([prior], replay)
        self.assertEqual(result["action"], "exact-reuse")
        self.assertEqual(result["ledger"], [prior])
        with self.assertRaises(ValueError):
            u2_publish_module.reconcile_verified_releases(
                [prior], dict(prior, runId="654321", runAttempt="2")
            )

    def test_verified_release_reconcile_rejects_malformed_or_non_monotonic_ledger(self):
        entry = _verified_entry()
        with self.assertRaises(ValueError):
            u2_publish_module.reconcile_verified_releases({"entries": []}, entry)
        with self.assertRaises(ValueError):
            u2_publish_module.reconcile_verified_releases([{"tag": TAG}], entry)
        malformed_legacy = {
            "tag": "v2.1.26.1",
            "target": TARGET,
            "versionName": "2.1.26.1",
            "versionCode": "23601",
            "assetSha256": APK_DIGEST,
            "signerSha256": SIGNER_DIGEST,
            "verified": True,
            "tag_ancestor": True,
        }
        with self.assertRaises(ValueError):
            u2_publish_module.reconcile_verified_releases([malformed_legacy], entry)
        with self.assertRaises(ValueError):
            u2_publish_module.reconcile_verified_releases([entry, entry], entry)
        conflicting_target = dict(entry, target="0" * 40)
        with self.assertRaises(ValueError):
            u2_publish_module.reconcile_verified_releases([entry, conflicting_target], entry)

        older = dict(entry, tag="v2.1.26.1", versionName="2.1.26.1", versionCode=23601)
        with self.assertRaises(ValueError):
            u2_publish_module.reconcile_verified_releases([entry], older)

        lower_code = dict(entry, tag="v2.1.28.1", versionName="2.1.28.1", versionCode=1)
        with self.assertRaises(ValueError):
            u2_publish_module.reconcile_verified_releases([entry], lower_code)

    def test_verified_release_readback_requires_exact_entry(self):
        entry = _verified_entry()
        canonical = (json.dumps([entry], indent=2, sort_keys=True) + "\n").encode()
        self.assertEqual(
            u2_publish_module.verify_verified_releases(canonical, entry),
            {"verified": True, "reason": ""},
        )
        self.assertFalse(
            u2_publish_module.verify_verified_releases(canonical.replace(SOURCE_SHA.encode(), ("0" * 40).encode()), entry)["verified"]
        )
        self.assertFalse(u2_publish_module.verify_verified_releases(b"not json", entry)["verified"])
        self.assertFalse(
            u2_publish_module.verify_verified_releases(
                (json.dumps([dict(entry, runAttempt="3")], sort_keys=True) + "\n").encode(), entry
            )["verified"]
        )
        duplicate = (
            '{"tag":"v2.1.27.1","tag":"v2.1.27.1",'
            '"target":"' + TARGET + '"}'
        ).encode()
        self.assertFalse(u2_publish_module.verify_verified_releases(duplicate, entry)["verified"])

    def test_verified_release_readback_can_select_the_persisted_replay_entry(self):
        persisted = dict(_verified_entry(), runAttempt="1")
        replay = dict(persisted, runAttempt="2")
        metadata = (json.dumps([persisted], sort_keys=True) + "\n").encode()
        result = u2_publish_module.persisted_verified_release_entry(metadata, replay)
        self.assertTrue(result["verified"])
        self.assertEqual(result["entry"], persisted)
        self.assertFalse(
            u2_publish_module.persisted_verified_release_entry(
                metadata, dict(replay, runId="654321")
            )["verified"]
        )

    def test_strict_json_parser_rejects_duplicate_update_keys(self):
        update = '{"version":"2.1.27.1","version":"2.1.27.1","apk_url":"https://example.invalid/apk"}'
        with self.assertRaises(ValueError):
            u2_publish_module.strict_json_loads(update)
        with self.assertRaises(ValueError):
            u2_publish_module.parse_update_metadata(update.encode())
        self.assertFalse(
            u2_publish_module.verify_remote_metadata(
                update.encode(),
                VERSION,
                "https://example.invalid/apk",
            )["verified"]
        )

    def test_verified_release_metadata_preflight_rejects_duplicate_ledger_and_binds_two_blobs(self):
        current_url = "https://example.invalid/current.apk"
        candidate_url = "https://example.invalid/candidate.apk"
        current_update = json.dumps({"version": "2.1.26.1", "apk_url": current_url}, indent=2).encode()
        candidate_update = (json.dumps({"version": VERSION, "apk_url": candidate_url}, sort_keys=True) + "\n").encode()
        entry = dict(_verified_entry(), updateSha256=hashlib.sha256(candidate_update).hexdigest())
        result = u2_publish_module.reconcile_verified_release_metadata(
            current_update,
            b"[]\n",
            candidate_update,
            entry,
        )
        self.assertEqual(result["action"], "append")
        self.assertEqual(result["ledger"], [entry])

        mismatched_current_ledger = dict(
            _verified_entry(),
            tag="v2.1.27.1",
            versionName="2.1.27.1",
            versionCode=23701,
            target="1" * 40,
            sourceSha="2" * 40,
        )
        with self.assertRaises(ValueError):
            u2_publish_module.reconcile_verified_release_metadata(
                current_update,
                json.dumps([mismatched_current_ledger]).encode(),
                candidate_update,
                entry,
            )

        current_update_digest = hashlib.sha256(current_update).hexdigest()
        complete_current_ledger = dict(
            _verified_entry(),
            tag="v2.1.26.1",
            versionName="2.1.26.1",
            versionCode=23601,
            target="3" * 40,
            sourceSha="4" * 40,
            updateSha256=current_update_digest,
        )
        drifted_current_update = current_update.replace(b"current.apk", b"drifted.apk")
        with self.assertRaises(ValueError):
            u2_publish_module.reconcile_verified_release_metadata(
                drifted_current_update,
                json.dumps([complete_current_ledger]).encode(),
                candidate_update,
                entry,
            )

        duplicate_ledger = b'[{"tag":"v2.1.26.1","tag":"v2.1.26.1"}]'
        with self.assertRaises(ValueError):
            u2_publish_module.reconcile_verified_release_metadata(
                current_update,
                duplicate_ledger,
                candidate_update,
                entry,
            )

        with self.assertRaises(ValueError):
            u2_publish_module.reconcile_verified_release_metadata(
                current_update,
                b"[]\n",
                candidate_update,
                dict(entry, updateSha256="0" * 64),
            )
        with self.assertRaises(ValueError):
            u2_publish_module.reconcile_verified_release_metadata(
                b'{"version":"2.1.27.1","version":"2.1.27.1","apk_url":"https://example.invalid/current.apk"}',
                b"[]\n",
                candidate_update,
                entry,
            )
        for malformed in (
            b'[]',
            b'{"version":123,"apk_url":"https://example.invalid/apk"}',
            b'{"version":"2.1.27.1","apk_url":123}',
        ):
            with self.subTest(malformed=malformed):
                with self.assertRaises(ValueError):
                    u2_publish_module.parse_update_metadata(malformed)

    def test_metadata_cas_harness_retries_only_on_fresh_porcelain_nff(self):
        sha_a = "a" * 40
        sha_b = "b" * 40
        rejected = "To origin\n!\trefs/heads/patched:refs/heads/patched\t[rejected] (non-fast-forward)\nDone"
        accepted = "To origin\n=\trefs/heads/patched:refs/heads/patched\t[up to date]\nDone"
        self.assertEqual(
            u2_publish_module.classify_metadata_push(
                0, accepted, sha_a, sha_a, sha_a, 1, 3
            )["action"],
            "success",
        )
        self.assertEqual(
            u2_publish_module.classify_metadata_push(
                1, rejected, sha_a, sha_a, sha_b, 1, 3
            )["action"],
            "retry",
        )
        self.assertEqual(
            u2_publish_module.classify_metadata_push(
                0, rejected, sha_a, sha_a, sha_b, 1, 3
            )["action"],
            "fail",
        )

        self.assertEqual(
            u2_publish_module.classify_metadata_push(
                1, rejected, sha_a, sha_a, sha_b, 3, 3
            )["action"],
            "retry-exhausted",
        )
        actual_git_rejected = "To origin\n!\tHEAD:refs/heads/patched\t[rejected] (non-fast-forward)\nDone"
        self.assertEqual(
            u2_publish_module.classify_metadata_push(
                1, actual_git_rejected, sha_a, sha_a, sha_b, 1, 3
            )["action"],
            "retry",
        )
        fast_forward = "To origin\n \tHEAD:refs/heads/patched\t" + sha_a + ".." + sha_b + "\nDone"
        self.assertEqual(
            u2_publish_module.classify_metadata_push(
                0, fast_forward, sha_a, sha_a, sha_b, 1, 3
            )["action"],
            "success",
        )
        fetch_first = "To origin\n!\tHEAD:refs/heads/patched\t[rejected] (fetch first)\nDone"
        self.assertEqual(
            u2_publish_module.classify_metadata_push(
                1, fetch_first, sha_a, sha_a, sha_b, 1, 3
            )["action"],
            "retry",
        )
        self.assertEqual(
            u2_publish_module.classify_metadata_push(
                1,
                "!\tHEAD:refs/heads/patched\t[remote rejected] (hook declined)",
                sha_a,
                sha_a,
                sha_b,
                1,
                3,
            )["action"],
            "fail",
        )
        self.assertEqual(
            u2_publish_module.classify_metadata_push(
                1,
                rejected + "\nremote: server hook failure",
                sha_a,
                sha_a,
                sha_b,
                1,
                3,
            )["action"],
            "fail",
        )
        self.assertEqual(
            u2_publish_module.classify_metadata_push(
                1,
                rejected + "\n!\tHEAD:refs/heads/main\t[rejected] (fetch first)",
                sha_a,
                sha_a,
                sha_b,
                1,
                3,
            )["action"],
            "fail",
        )
        self.assertEqual(
            u2_publish_module.classify_metadata_push(
                1,
                "!\tHEAD:refs/heads/main\t[rejected] (fetch first)",
                sha_a,
                sha_a,
                sha_b,
                1,
                3,
            )["action"],
            "fail",
        )
        self.assertEqual(
            u2_publish_module.classify_metadata_push(
                1,
                rejected,
                sha_a,
                sha_a,
                sha_a,
                1,
                3,
            )["action"],
            "fail",
        )
        self.assertEqual(
            u2_publish_module.classify_metadata_push(
                1,
                rejected + "\nunknown: output line",
                sha_a,
                sha_a,
                sha_b,
                1,
                3,
            )["action"],
            "fail",
        )
        self.assertEqual(
            u2_publish_module.classify_metadata_push(
                1,
                rejected + "\nhint: unexpected diagnostic",
                sha_a,
                sha_a,
                sha_b,
                1,
                3,
            )["action"],
            "fail",
        )
        self.assertEqual(
            u2_publish_module.classify_metadata_push(
                0,
                accepted + "\n!\tHEAD:refs/heads/patched\t[remote rejected] (hook declined)",
                sha_a,
                sha_a,
                sha_a,
                1,
                3,
            )["action"],
            "fail",
        )
        self.assertEqual(
            u2_publish_module.classify_metadata_push(
                1, "fatal: authentication failed", sha_a, sha_a, sha_a, 1, 3
            )["action"],
            "fail",
        )

    def test_metadata_push_classifier_accepts_real_git_nff_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            remote = root / "remote.git"
            first = root / "first"
            second = root / "second"

            def run(*args):
                return subprocess.run(args, check=True, text=True, capture_output=True)

            run("git", "init", "--bare", str(remote))
            run("git", "init", "-b", "patched", str(first))
            run("git", "-C", str(first), "config", "user.name", "first")
            run("git", "-C", str(first), "config", "user.email", "first@example.invalid")
            (first / "file").write_text("base\n")
            run("git", "-C", str(first), "add", "file")
            run("git", "-C", str(first), "commit", "-m", "base")
            run("git", "-C", str(first), "remote", "add", "origin", str(remote))
            run("git", "-C", str(first), "push", "origin", "HEAD:refs/heads/patched")
            run("git", "clone", "-b", "patched", str(remote), str(second))
            run("git", "-C", str(second), "config", "user.name", "second")
            run("git", "-C", str(second), "config", "user.email", "second@example.invalid")

            (first / "file").write_text("base\nfirst\n")
            run("git", "-C", str(first), "add", "file")
            run("git", "-C", str(first), "commit", "-m", "first")
            run("git", "-C", str(first), "push", "origin", "HEAD:refs/heads/patched")
            (second / "file").write_text("base\nsecond\n")
            run("git", "-C", str(second), "add", "file")
            run("git", "-C", str(second), "commit", "-m", "second")
            local_parent = subprocess.check_output(
                ["git", "-C", str(second), "rev-parse", "HEAD^"], text=True
            ).strip()
            remote_before = subprocess.check_output(
                ["git", "-C", str(first), "rev-parse", "HEAD"], text=True
            ).strip()
            failed_push = subprocess.run(
                ["git", "-C", str(second), "push", "--porcelain", str(remote), "HEAD:refs/heads/patched"],
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(failed_push.returncode, 0)

            (first / "file").write_text("base\nfirst\nfirst-again\n")
            run("git", "-C", str(first), "add", "file")
            run("git", "-C", str(first), "commit", "-m", "first-again")
            run("git", "-C", str(first), "push", "origin", "HEAD:refs/heads/patched")
            remote_after = subprocess.check_output(
                ["git", "-C", str(first), "rev-parse", "HEAD"], text=True
            ).strip()
            result = u2_publish_module.classify_metadata_push(
                failed_push.returncode,
                failed_push.stdout + failed_push.stderr,
                local_parent,
                remote_before,
                remote_after,
                1,
                3,
            )
            self.assertEqual(
                result["action"],
                "retry",
                f"{result}; {failed_push.stdout + failed_push.stderr!r}; status={failed_push.returncode}; before={remote_before}; after={remote_after}; parent={local_parent}",
            )

    def test_metadata_push_classifier_requires_strict_porcelain_order_and_diagnostics(self):
        sha_a = "a" * 40
        sha_b = "b" * 40
        accepted = "=\tHEAD:refs/heads/patched\t[up to date]"
        rejected = "!\tHEAD:refs/heads/patched\t[rejected] (non-fast-forward)"
        valid_success = "To origin\n" + accepted + "\nDone"
        valid_rejection = "To origin\n" + rejected + "\nDone"

        malformed = (
            "Done\n" + valid_success,
            "To origin\nDone\n" + accepted,
            accepted + "\nTo origin\nDone",
            valid_success.removesuffix("\nDone"),
            valid_rejection + "\nerror: failed to push some refs to 'origin' with extra text",
            valid_rejection + "\nerror: failed to push some refs to 'other'",
            valid_rejection + "\nhint: an unrecognized diagnostic",
            valid_rejection + "\nremote: server hook failure",
            valid_rejection + "\nfatal: authentication failed",
            "To origin\n" + rejected + "\n" + accepted + "\nDone",
            "To origin\n!\tHEAD:refs/heads/main\t[rejected] (non-fast-forward)\nDone",
        )
        for porcelain in malformed:
            with self.subTest(porcelain=porcelain):
                self.assertEqual(
                    u2_publish_module.classify_metadata_push(
                        1 if rejected in porcelain else 0,
                        porcelain,
                        sha_a,
                        sha_a,
                        sha_b,
                        1,
                        3,
                    )["action"],
                    "fail",
                )

    def test_production_legacy_ledger_can_append_complete_entry_and_bind_latest_update_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            current_update = tmp_path / "current-update.json"
            current_ledger = tmp_path / "current-ledger.json"
            candidate_update = tmp_path / "candidate-update.json"
            entry_file = tmp_path / "entry.json"
            output = tmp_path / "output.json"

            current_update.write_bytes((ROOT / "update.json").read_bytes())
            current_ledger.write_bytes((ROOT / "gradle/verified-releases.json").read_bytes())
            candidate_url = "https://example.invalid/releases/v2.1.27.1/TVBox-Mobile-v2.1.27.1.apk"
            candidate_bytes = (json.dumps(
                build_update_json("2.1.27.1", candidate_url), sort_keys=True
            ) + "\n").encode()
            candidate_update.write_bytes(candidate_bytes)
            entry = u2_publish_module.verified_release_entry(
                tag="v2.1.27.1",
                target="1" * 40,
                version_name="2.1.27.1",
                version_code=23701,
                asset_sha256="2" * 64,
                update_sha256=hashlib.sha256(candidate_bytes).hexdigest(),
                signer_sha256="3" * 64,
                source_sha="4" * 40,
                debt="5" * 64,
                run_id="123457",
                run_attempt="1",
            )
            entry_file.write_text(json.dumps(entry, sort_keys=True) + "\n")

            command = [
                "python3", "scripts/u2_publish.py",
                "reconcile-verified-release-metadata",
                "--current-update", str(current_update),
                "--current-ledger", str(current_ledger),
                "--candidate-update", str(candidate_update),
                "--entry", str(entry_file),
                "--output", str(output),
            ]
            first = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(json.loads(first.stdout)["action"], "append")
            appended = json.loads(output.read_text())
            self.assertEqual(appended[0], json.loads(current_ledger.read_text())[0])
            self.assertEqual(appended[-1], entry)

            current_update.write_bytes(candidate_bytes + b"\n")
            current_ledger.write_text(json.dumps(appended, sort_keys=True) + "\n")
            drifted = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
            self.assertNotEqual(drifted.returncode, 0)
            self.assertIn("current update metadata digest", drifted.stderr)

    def test_release_read_classifier_allows_only_explicit_404_fallback(self):
        self.assertEqual(
            u2_publish_module.classify_release_read(0, 200)["action"],
            "present",
        )
        self.assertEqual(
            u2_publish_module.classify_release_read(1, 404)["action"],
            "missing",
        )
        for exit_status, http_status in (
            (1, 401),
            (1, 403),
            (1, 422),
            (1, 500),
            (1, 0),
            (0, 500),
        ):
            with self.subTest(exit_status=exit_status, http_status=http_status):
                self.assertEqual(
                    u2_publish_module.classify_release_read(exit_status, http_status)["action"],
                    "fail",
                )

    def test_reconcile_verified_releases_cli_round_trip(self):
        entry = _verified_entry()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ledger = tmp_path / "verified-releases.json"
            entry_file = tmp_path / "entry.json"
            output = tmp_path / "reconciled.json"
            ledger.write_text("[]\n")
            entry_file.write_text(json.dumps(entry, sort_keys=True) + "\n")

            command = [
                "python3", "scripts/u2_publish.py", "reconcile-verified-releases",
                "--ledger", str(ledger),
                "--entry", str(entry_file),
                "--output", str(output),
            ]
            first = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(json.loads(first.stdout)["action"], "append")
            self.assertEqual(json.loads(output.read_text()), [entry])

            ledger.write_bytes(output.read_bytes())
            second = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(json.loads(second.stdout)["action"], "exact-reuse")
            self.assertEqual(json.loads(output.read_text()), [entry])

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

    def test_released_identity_cli(self):
        published = json.dumps(_draft([_asset(APK_NAME, f"sha256:{APK_DIGEST}"), _asset("update.json", f"sha256:{UPDATE_DIGEST}")], is_draft=False))
        result = subprocess.run(
            [
                "python3", "scripts/u2_publish.py", "released-identity",
                "--release", published,
                "--version", VERSION,
                "--expected-tag", TAG,
                "--expected-target-sha", TARGET,
                "--apk-digest", APK_DIGEST,
                "--update-digest", UPDATE_DIGEST,
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["decision"], "verify-published")
        draft = json.loads(published)
        draft["isDraft"] = True
        result_draft = subprocess.run(
            [
                "python3", "scripts/u2_publish.py", "released-identity",
                "--release", json.dumps(draft),
                "--version", VERSION,
                "--expected-tag", TAG,
                "--expected-target-sha", TARGET,
                "--apk-digest", APK_DIGEST,
                "--update-digest", UPDATE_DIGEST,
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        self.assertEqual(result_draft.returncode, 0, result_draft.stderr)
        self.assertEqual(json.loads(result_draft.stdout)["decision"], "reject-published-is-draft")

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
