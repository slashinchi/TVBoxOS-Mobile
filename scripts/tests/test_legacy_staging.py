import hashlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from scripts.legacy_staging import (
    ALLOWED_COORDINATES,
    load_manifest,
    stage_manifest,
    validate_manifest,
    validate_pom_bytes,
    verify_staged_directory,
)
from unittest.mock import patch


ROOT = Path(__file__).parents[2]
MANIFEST_PATH = ROOT / "gradle/legacy-dependencies.lock.json"


def synthetic_manifest_and_payloads():
    manifest = json.loads(MANIFEST_PATH.read_text())
    payloads = {}
    for component in manifest["components"]:
        pom = (
            "<project xmlns=\"http://maven.apache.org/POM/4.0.0\">"
            f"<groupId>{component['group']}</groupId>"
            f"<artifactId>{component['module']}</artifactId>"
            f"<version>{component['version']}</version>"
            f"<packaging>{component['packaging']}</packaging>"
            "</project>"
        ).encode()
        binary = f"synthetic-{component['module']}".encode()
        component["pom_sha256"] = hashlib.sha256(pom).hexdigest()
        component["binary_sha256"] = hashlib.sha256(binary).hexdigest()
        payloads[component["module"]] = (pom, binary)
    return manifest, payloads


class LegacyStagingContractTests(unittest.TestCase):
    def test_manifest_contains_exact_approved_coordinates(self):
        manifest = load_manifest(MANIFEST_PATH)
        coordinates = {(item["group"], item["module"], item["version"]) for item in manifest["components"]}
        self.assertEqual(coordinates, ALLOWED_COORDINATES)

    def test_manifest_rejects_dynamic_version_and_unexpected_coordinate(self):
        manifest = json.loads(MANIFEST_PATH.read_text())
        manifest["components"][0]["version"] = "1.+"
        with self.assertRaisesRegex(ValueError, "dynamic or invalid version"):
            validate_manifest(manifest)

        manifest = json.loads(MANIFEST_PATH.read_text())
        manifest["components"][0]["group"] = "com.example"
        with self.assertRaisesRegex(ValueError, "outside the approved legacy island"):
            validate_manifest(manifest)

    def test_poms_match_manifest_coordinates_and_packaging(self):
        manifest = load_manifest(MANIFEST_PATH)
        synthetic, payloads = synthetic_manifest_and_payloads()
        validate_manifest(synthetic)
        for component in synthetic["components"]:
            pom = payloads[component["module"]][0]
            validate_pom_bytes(pom, component)

    def test_staged_file_set_rejects_extra_files(self):
        manifest, payloads = synthetic_manifest_and_payloads()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "maven"
            for component in manifest["components"]:
                relative = Path(component["group"].replace(".", "/")) / component["module"] / component["version"]
                destination = root / relative
                destination.mkdir(parents=True)
                pom, binary = payloads[component["module"]]
                (destination / component["pom"]).write_bytes(pom)
                (destination / component["binary"]).write_bytes(binary)

            verify_staged_directory(manifest, root)
            (root / "unexpected.txt").write_text("unexpected")
            with self.assertRaisesRegex(ValueError, "file set differs"):
                verify_staged_directory(manifest, root)

    def test_staged_file_set_rejects_symlink(self):
        manifest, payloads = synthetic_manifest_and_payloads()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "maven"
            for component in manifest["components"]:
                relative = Path(component["group"].replace(".", "/")) / component["module"] / component["version"]
                destination = root / relative
                destination.mkdir(parents=True)
                pom, binary = payloads[component["module"]]
                (destination / component["pom"]).write_bytes(pom)
                (destination / component["binary"]).write_bytes(binary)
            component = manifest["components"][0]
            relative = Path(component["group"].replace(".", "/")) / component["module"] / component["version"]
            (root / relative / component["binary"]).unlink()
            (root / relative / component["binary"]).symlink_to("missing-binary")
            with self.assertRaisesRegex(ValueError, "symlink"):
                verify_staged_directory(manifest, root)

    def test_stage_downloads_exact_payloads_and_makes_layout_read_only(self):
        manifest, payloads = synthetic_manifest_and_payloads()

        class Response(io.BytesIO):
            def __init__(self, data, url):
                super().__init__(data)
                self.url = url

            def geturl(self):
                return self.url

        def opener(request, timeout):
            filename = request.full_url.rsplit("/", 1)[-1]
            module = next(
                component["module"]
                for component in manifest["components"]
                if filename in {component["pom"], component["binary"]}
            )
            payload = payloads[module][0 if filename.endswith(".pom") else 1]
            return Response(payload, request.full_url)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "maven"
            with patch.dict(os.environ, {"RUNNER_TEMP": tmp}, clear=False):
                stage_manifest(manifest, root, opener=opener)
                verify_staged_directory(manifest, root)
                for path in root.rglob("*"):
                    self.assertEqual(path.stat().st_mode & 0o222, 0, str(path))

    def test_stage_rejects_output_outside_runner_temp(self):
        manifest, payloads = synthetic_manifest_and_payloads()

        class Response(io.BytesIO):
            def __init__(self, data, url):
                super().__init__(data)
                self.url = url

            def geturl(self):
                return self.url

        def opener(request, timeout):
            filename = request.full_url.rsplit("/", 1)[-1]
            module = next(
                component["module"]
                for component in manifest["components"]
                if filename in {component["pom"], component["binary"]}
            )
            payload = payloads[module][0 if filename.endswith(".pom") else 1]
            return Response(payload, request.full_url)

        with tempfile.TemporaryDirectory() as tmp:
            runner_temp = Path(tmp) / "runner-temp"
            runner_temp.mkdir()
            outside = Path(tmp) / "outside"
            outside.mkdir()
            with patch.dict(os.environ, {"RUNNER_TEMP": str(runner_temp)}, clear=False):
                with self.assertRaisesRegex(ValueError, "must be under RUNNER_TEMP"):
                    stage_manifest(manifest, outside / "maven", opener=opener)


if __name__ == "__main__":
    unittest.main(verbosity=2)
