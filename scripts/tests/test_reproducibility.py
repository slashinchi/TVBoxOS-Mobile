import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.reproducibility import ReproducibilityError, compare_build_evidence


EXPECTED_FILES = (
    "unsigned.apk",
    "build-identity.json",
    "payload-manifest.json",
    "native-compat.json",
    "runtime-components.json",
    "legacy-dependencies.lock.json",
)


class ReproducibilityTests(unittest.TestCase):
    def test_identical_primary_and_repro_evidence_is_equivalent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            primary = self._write_evidence(root / "primary", "primary")
            repro = self._write_evidence(root / "repro", "repro")

            report = compare_build_evidence(
                primary,
                repro,
                primary_artifact_id="101",
                repro_artifact_id="202",
                primary_artifact_digest="a" * 64,
                repro_artifact_digest="b" * 64,
            )

            self.assertEqual(report["status"], "equivalent")
            self.assertEqual(report["primary_artifact_id"], "101")
            self.assertEqual(report["repro_artifact_id"], "202")
            self.assertEqual(report["primary_builder_role"], "primary")
            self.assertFalse(report["runner_image_drift"])
            self.assertEqual(report["primary_artifact_digest"], "a" * 64)
            self.assertEqual(report["repro_artifact_digest"], "b" * 64)

    def test_rejects_same_artifact_id_and_role_swap(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            primary = self._write_evidence(root / "primary", "primary")
            repro = self._write_evidence(root / "repro", "repro")

            with self.assertRaisesRegex(ReproducibilityError, "artifact IDs must differ"):
                self._compare(primary, repro, repro_artifact_id="101")

            (repro / "build-identity.json").write_text(
                (repro / "build-identity.json").read_text().replace('"repro"', '"primary"')
            )
            with self.assertRaisesRegex(ReproducibilityError, "builder_role"):
                self._compare(primary, repro)

    def test_rejects_raw_payload_tool_and_recipe_mismatches(self):
        cases = (
            ("unsigned.apk", "raw unsigned APK mismatch"),
            ("payload-manifest.json", "payload manifest mismatch"),
            ("native-compat.json", "native compatibility report mismatch"),
            ("runtime-components.json", "runtime dependency report mismatch"),
            ("legacy-dependencies.lock.json", "legacy dependency lock mismatch"),
        )
        for changed_file, message in cases:
            with self.subTest(changed_file=changed_file), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                primary = self._write_evidence(root / "primary", "primary")
                repro = self._write_evidence(root / "repro", "repro")
                (repro / changed_file).write_bytes(b"different\n")
                if changed_file != "unsigned.apk":
                    self._refresh_identity_digest(repro, changed_file)

                with self.assertRaisesRegex(ReproducibilityError, message):
                    self._compare(primary, repro)

        for identity_field, message in (
            ("apksigner_sha256", "tool identity mismatch"),
            ("builder_recipe_sha256", "build recipe mismatch"),
        ):
            with self.subTest(identity_field=identity_field), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                primary = self._write_evidence(root / "primary", "primary")
                repro = self._write_evidence(root / "repro", "repro")
                identity_path = repro / "build-identity.json"
                identity = json.loads(identity_path.read_text())
                identity[identity_field] = "f" * 64
                identity_path.write_text(json.dumps(identity, sort_keys=True) + "\n")

                with self.assertRaisesRegex(ReproducibilityError, message):
                    self._compare(primary, repro)

    def test_allows_image_version_drift_but_records_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            primary = self._write_evidence(root / "primary", "primary", image_version="20260823.283.1")
            repro = self._write_evidence(root / "repro", "repro", image_version="20260824.284.1")

            report = compare_build_evidence(
                primary,
                repro,
                primary_artifact_id="101",
                repro_artifact_id="202",
                primary_artifact_digest="a" * 64,
                repro_artifact_digest="b" * 64,
            )

            self.assertEqual(report["status"], "equivalent")
            self.assertTrue(report["runner_image_drift"])
            self.assertEqual(report["primary_runner_image_version"], "20260823.283.1")
            self.assertEqual(report["repro_runner_image_version"], "20260824.284.1")

    def test_rejects_artifact_root_pollution_and_symlink(self):
        for pollution in ("extra.txt", "nested"):
            with self.subTest(pollution=pollution), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                primary = self._write_evidence(root / "primary", "primary")
                repro = self._write_evidence(root / "repro", "repro")
                if pollution == "extra.txt":
                    (repro / pollution).write_text("unexpected\n")
                else:
                    (repro / pollution).mkdir()

                with self.assertRaisesRegex(ReproducibilityError, "exactly 6 regular files"):
                    self._compare(primary, repro)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            primary = self._write_evidence(root / "primary", "primary")
            repro = self._write_evidence(root / "repro", "repro")
            (repro / "payload-manifest.json").unlink()
            (repro / "payload-manifest.json").symlink_to(primary / "payload-manifest.json")

            with self.assertRaisesRegex(ReproducibilityError, "symlink"):
                self._compare(primary, repro)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            primary = self._write_evidence(root / "primary", "primary")
            repro_target = self._write_evidence(root / "repro-target", "repro")
            repro = root / "repro-link"
            repro.symlink_to(repro_target, target_is_directory=True)

            with self.assertRaisesRegex(ReproducibilityError, "symlink"):
                self._compare(primary, repro)

    def test_rejects_missing_release_identity_field(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            primary = self._write_evidence(root / "primary", "primary")
            repro = self._write_evidence(root / "repro", "repro")
            identity_path = repro / "build-identity.json"
            identity = json.loads(identity_path.read_text())
            del identity["source_sha"]
            identity_path.write_text(json.dumps(identity, sort_keys=True) + "\n")

            with self.assertRaisesRegex(ReproducibilityError, "required identity field: source_sha"):
                self._compare(primary, repro)

    @staticmethod
    def _compare(primary, repro, primary_artifact_id="101", repro_artifact_id="202"):
        return compare_build_evidence(
            primary,
            repro,
            primary_artifact_id=primary_artifact_id,
            repro_artifact_id=repro_artifact_id,
            primary_artifact_digest="a" * 64,
            repro_artifact_digest="b" * 64,
        )

    @staticmethod
    def _write_evidence(root, role, image_version="20260823.283.1"):
        root.mkdir(parents=True)
        content = {
            "payload-manifest.json": b"payload\n",
            "native-compat.json": b"native\n",
            "runtime-components.json": b"runtime\n",
            "legacy-dependencies.lock.json": b"legacy\n",
        }
        (root / "unsigned.apk").write_bytes(b"unsigned-apk\n")
        for name, data in content.items():
            (root / name).write_bytes(data)
        identity = {
            "schema": "tvbox-release-identity-v2",
            "builder_role": role,
            "artifact_source_sha": "a" * 40,
            "source_sha": "b" * 40,
            "workflow_source_sha": "b" * 40,
            "mode": "manual-local",
            "upstream_sha": "c" * 40,
            "upstream_version": "2.1.26",
            "upstream_code": 23600,
            "version_name": "2.1.26.1",
            "version_code": "23601",
            "release_debt": "4" * 64,
            "candidate_pr": "",
            "provenance_marker": "",
            "builder_recipe_sha256": "c" * 64,
            "unsigned_sha256": hashlib.sha256((root / "unsigned.apk").read_bytes()).hexdigest(),
            "payload_manifest_sha256": hashlib.sha256(content["payload-manifest.json"]).hexdigest(),
            "runtime_components_sha256": hashlib.sha256(content["runtime-components.json"]).hexdigest(),
            "legacy_manifest_sha256": hashlib.sha256(content["legacy-dependencies.lock.json"]).hexdigest(),
            "native_compat_report_sha256": hashlib.sha256(content["native-compat.json"]).hexdigest(),
            "apksigner_sha256": "d" * 64,
            "apksigner_jar_sha256": "3" * 64,
            "aapt2_sha256": "e" * 64,
            "zipalign_sha256": "f" * 64,
            "llvm_readelf_sha256": "1" * 64,
            "java_binary_sha256": "2" * 64,
            "runner_image_os": "ubuntu24",
            "runner_image_version": image_version,
        }
        (root / "build-identity.json").write_text(json.dumps(identity, sort_keys=True) + "\n")
        return root

    @staticmethod
    def _refresh_identity_digest(root, filename):
        identity_path = root / "build-identity.json"
        identity = json.loads(identity_path.read_text())
        field = {
            "payload-manifest.json": "payload_manifest_sha256",
            "native-compat.json": "native_compat_report_sha256",
            "runtime-components.json": "runtime_components_sha256",
            "legacy-dependencies.lock.json": "legacy_manifest_sha256",
        }[filename]
        identity[field] = hashlib.sha256((root / filename).read_bytes()).hexdigest()
        identity_path.write_text(json.dumps(identity, sort_keys=True) + "\n")


if __name__ == "__main__":
    unittest.main(verbosity=2)
