from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from amazify.plugin_manager import PluginError, PluginManager


ROOT = Path(__file__).resolve().parent.parent


class PluginManagerTests(unittest.TestCase):
    def test_lists_github_catalog_plugins_without_installing_them(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manager = PluginManager(
                root / "plugins",
                root / "state.json",
                catalog_url=(ROOT / "plugin_catalog.json").resolve().as_uri(),
            )

            catalog = manager.catalog_plugins()
            ids = {plugin["id"] for plugin in catalog}

            self.assertEqual(
                ids,
                {
                    "amazify.resume-last-song",
                    "amazify.true-big-mode",
                    "amazify.button.focus-mode",
                    "amazify.theme.dark-green",
                },
            )
            self.assertFalse(any(plugin["installed"] for plugin in catalog))
            self.assertEqual(manager.list_plugins(), [])
            self.assertEqual(manager.runtime_snapshot(), [])

    def test_installs_catalog_plugin_and_keeps_it_disabled_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            remote = root / "remote" / "demo.plugin"
            remote.mkdir(parents=True)
            manifest = {
                "id": "demo.plugin",
                "name": "Demo Plugin",
                "version": "0.1.0",
                "author": "Amazify",
                "type": "ui",
                "description": "Demo catalog plugin.",
                "entry": "plugin.js",
                "styles": ["style.css"],
                "permissions": ["dom-read", "dom-write"],
                "amazonMusic": {"target": "desktop"},
            }
            (remote / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            (remote / "plugin.js").write_text(
                'const marker = "demo-plugin-entry"; return () => marker;',
                encoding="utf-8",
            )
            (remote / "style.css").write_text(
                ".demo-plugin { color: #25d366; }",
                encoding="utf-8",
            )
            catalog = root / "catalog.json"
            catalog.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "plugins": [
                            {
                                "id": "demo.plugin",
                                "channel": "stock",
                                "sourceUrl": "https://github.com/example/demo.plugin",
                                "manifest": manifest,
                                "files": [
                                    {
                                        "path": "manifest.json",
                                        "url": (remote / "manifest.json").resolve().as_uri(),
                                    },
                                    {
                                        "path": "plugin.js",
                                        "url": (remote / "plugin.js").resolve().as_uri(),
                                    },
                                    {
                                        "path": "style.css",
                                        "url": (remote / "style.css").resolve().as_uri(),
                                    },
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            manager = PluginManager(
                root / "plugins",
                root / "state.json",
                catalog_url=catalog.resolve().as_uri(),
            )

            package = manager.install_from_catalog("demo.plugin")

            self.assertEqual(package.manifest.id, "demo.plugin")
            self.assertFalse(package.enabled)
            self.assertTrue((root / "plugins" / "demo.plugin" / "manifest.json").exists())
            self.assertTrue((root / "plugins" / "demo.plugin" / "plugin.js").exists())
            self.assertTrue((root / "plugins" / "demo.plugin" / "style.css").exists())

            plugins = manager.list_plugins()
            self.assertEqual([plugin.manifest.id for plugin in plugins], ["demo.plugin"])
            self.assertFalse(plugins[0].enabled)

            catalog_after_install = manager.catalog_plugins(force_refresh=True)
            self.assertTrue(catalog_after_install[0]["installed"])
            self.assertEqual(catalog_after_install[0]["installedVersion"], "0.1.0")
            self.assertEqual(catalog_after_install[0]["latestVersion"], "0.1.0")
            self.assertFalse(catalog_after_install[0]["updateAvailable"])

            updated_manifest = dict(manifest)
            updated_manifest["version"] = "0.2.0"
            (remote / "manifest.json").write_text(
                json.dumps(updated_manifest),
                encoding="utf-8",
            )
            catalog.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "plugins": [
                            {
                                "id": "demo.plugin",
                                "channel": "stock",
                                "sourceUrl": "https://github.com/example/demo.plugin",
                                "manifest": updated_manifest,
                                "files": [
                                    {
                                        "path": "manifest.json",
                                        "url": (remote / "manifest.json").resolve().as_uri(),
                                    },
                                    {
                                        "path": "plugin.js",
                                        "url": (remote / "plugin.js").resolve().as_uri(),
                                    },
                                    {
                                        "path": "style.css",
                                        "url": (remote / "style.css").resolve().as_uri(),
                                    },
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            update_scan = manager.catalog_plugins(force_refresh=True)
            self.assertEqual(update_scan[0]["installedVersion"], "0.1.0")
            self.assertEqual(update_scan[0]["latestVersion"], "0.2.0")
            self.assertTrue(update_scan[0]["updateAvailable"])

            manager.enable("demo.plugin")
            snapshot = manager.runtime_snapshot()
            self.assertTrue(snapshot[0]["enabled"])
            self.assertIn("demo-plugin-entry", snapshot[0]["source"]["entry"])
            self.assertIn(
                "style.css",
                {style["path"] for style in snapshot[0]["source"]["styles"]},
            )

            manager.disable_all()
            self.assertFalse(any(plugin.enabled for plugin in manager.list_plugins()))

    def test_rejects_manifest_paths_that_escape_plugin_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plugin = root / "plugins" / "bad"
            plugin.mkdir(parents=True)
            (plugin / "manifest.json").write_text(
                """
{
  "id": "bad.plugin.path",
  "name": "Bad Plugin",
  "version": "0.1.0",
  "author": "Test",
  "type": "theme",
  "description": "Bad path",
  "entry": "../outside.js",
  "styles": [],
  "permissions": [],
  "amazonMusic": {"target": "desktop"}
}
""".strip(),
                encoding="utf-8",
            )
            manager = PluginManager(root / "plugins", root / "state.json")

            with self.assertRaises(PluginError):
                manager.load_manifest(plugin / "manifest.json")


if __name__ == "__main__":
    unittest.main()
