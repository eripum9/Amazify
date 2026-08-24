from __future__ import annotations

import hashlib
import json
import subprocess
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


class CatalogIntegrityTests(unittest.TestCase):
    def test_scrapped_plugins_are_indexed_and_not_cataloged(self) -> None:
        archive = ROOT / "sample_plugins" / "Scrapped"
        archive_readme = (archive / "README.md").read_text(encoding="utf-8")
        catalog: dict[str, Any] = json.loads(
            (ROOT / "plugin_catalog.json").read_text(encoding="utf-8")
        )
        catalog_ids = {plugin["id"] for plugin in catalog["plugins"]}

        archived = [
            plugin
            for plugin in archive.iterdir()
            if plugin.is_dir() and (plugin / "manifest.json").is_file()
        ]
        self.assertTrue(archived, "Scrapped must contain at least one archived plugin")
        for plugin in archived:
            manifest = json.loads(
                (plugin / "manifest.json").read_text(encoding="utf-8")
            )
            with self.subTest(plugin=manifest["id"]):
                self.assertIn(f"]({plugin.name}/)", archive_readme)
                self.assertNotIn(manifest["id"], catalog_ids)

    def test_catalog_hashes_match_the_pinned_git_blobs(self) -> None:
        if not (ROOT / ".git").exists():
            self.skipTest("Git metadata is unavailable")
        catalog: dict[str, Any] = json.loads(
            (ROOT / "plugin_catalog.json").read_text(encoding="utf-8")
        )

        for plugin in catalog["plugins"]:
            for item in plugin["files"]:
                with self.subTest(plugin=plugin["id"], path=item["path"]):
                    spec = (
                        f"{plugin['sourceCommit']}:"
                        f"{plugin['pluginRoot']}/{item['path']}"
                    )
                    result = subprocess.run(
                        ["git", "show", spec],
                        cwd=ROOT,
                        capture_output=True,
                        check=False,
                    )
                    self.assertEqual(
                        result.returncode,
                        0,
                        result.stderr.decode("utf-8", errors="replace"),
                    )
                    self.assertEqual(len(result.stdout), item["size"])
                    self.assertEqual(
                        hashlib.sha256(result.stdout).hexdigest(),
                        item["sha256"],
                    )


if __name__ == "__main__":
    unittest.main()
