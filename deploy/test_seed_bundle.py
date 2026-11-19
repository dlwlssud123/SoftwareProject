import hashlib
import importlib.util
import json
import tarfile
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "seed_bundle", Path(__file__).with_name("make-seed-bundle.py")
)
seed_bundle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed_bundle)


def snapshot(kind, **overrides):
    items = (
        [{"RCP_SEQ": "1", "RCP_NM": "쌀죽"}]
        if kind == "recipes"
        else [{"FOOD_CD": "F1", "FOOD_NM_KR": "쌀"}]
    )
    options = {"ensure_ascii": False, "sort_keys": True}
    if kind == "recipes":
        options["separators"] = (",", ":")
    meta = {
        "service": "COOKRCP01"
        if kind == "recipes"
        else "식품의약품안전처_식품영양성분DB정보",
        "api_version": "03",
        "complete": True,
        "total_count": 1,
        "item_count": 1,
        "items_sha256": hashlib.sha256(
            json.dumps(items, **options).encode("utf-8")
        ).hexdigest(),
        "fetched_at": "2026-11-05T00:00:00+00:00",
    }
    meta.update(overrides)
    return json.dumps({"meta": meta, "items": items}, ensure_ascii=False).encode(
        "utf-8"
    )


class SeedBundleTest(unittest.TestCase):
    def test_both_source_checksum_formats(self):
        for kind in seed_bundle.INPUTS:
            with self.subTest(kind=kind):
                info = seed_bundle.snapshot_info(snapshot(kind), kind)
                self.assertEqual(info["count"], 1)

    def test_bad_input_is_rejected(self):
        for metadata in (
            {"complete": False},
            {"total_count": 2},
            {"items_sha256": "bad"},
            {"service": "wrong"},
        ):
            with self.subTest(metadata=metadata), self.assertRaises(ValueError):
                seed_bundle.snapshot_info(snapshot("recipes", **metadata), "recipes")

    def test_credentials_are_rejected(self):
        for metadata in (
            {"serviceKey": "private-test-value"},
            {"endpoint": "https://example.org/?serviceKey=private-test-value"},
            {"endpoint": "https://user:password@example.org/data"},
        ):
            with self.subTest(metadata=metadata), self.assertRaises(ValueError):
                seed_bundle.snapshot_info(snapshot("recipes", **metadata), "recipes")

    def test_allowlist_archive_excludes_env_and_user_db(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for kind, name in seed_bundle.INPUTS.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(snapshot(kind))
            (root / "deploy").mkdir()
            (root / "deploy/seed-first.sh").write_bytes(b"#!/bin/bash\r\nexit 0\r\n")
            (root / "deploy/seed.compose.yaml").write_bytes(b"services: {}\r\n")
            (root / ".env").write_text("private-test-value")
            (root / "users.dump").write_bytes(b"private-test-value")
            output = root / "seed.tar.gz"
            seed_bundle.build_bundle(root, output)
            with tarfile.open(output) as archive:
                self.assertEqual(
                    set(archive.getnames()),
                    set(seed_bundle.INPUTS.values())
                    | {
                        "seed-first.sh",
                        "seed.compose.yaml",
                        "manifest.json",
                        "snapshots.sha256",
                    },
                )
                self.assertNotIn(b"\r\n", archive.extractfile("seed-first.sh").read())
                for name in seed_bundle.INPUTS.values():
                    self.assertEqual(
                        archive.extractfile(name).read(), (root / name).read_bytes()
                    )
            original = output.read_bytes()
            (root / seed_bundle.INPUTS["recipes"]).write_bytes(
                snapshot("recipes", complete=False)
            )
            with self.assertRaises(ValueError):
                seed_bundle.build_bundle(root, output)
            self.assertEqual(output.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
