from __future__ import annotations

import concurrent.futures
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from amazify.plugin_manager import PluginError, PluginManager

ROOT = Path(__file__).resolve().parent.parent
COMMIT = "1" * 40


def demo_manifest(
    *, version: str = "0.1.0", plugin_id: str = "demo.plugin"
) -> dict[str, Any]:
    return {
        "id": plugin_id,
        "name": "Demo Plugin",
        "version": version,
        "author": "Amazify",
        "type": "ui",
        "description": "Demo catalog plugin.",
        "entry": "plugin.js",
        "styles": ["style.css"],
        "assets": {"logo": "assets/logo.svg"},
        "permissions": ["dom-read", "dom-write", "dom-style"],
        "amazonMusic": {"target": "desktop"},
    }


def demo_files(manifest: dict[str, Any] | None = None) -> dict[str, bytes]:
    selected_manifest = manifest or demo_manifest()
    return {
        "manifest.json": json.dumps(selected_manifest, separators=(",", ":")).encode(),
        "plugin.js": b'const marker = "demo-plugin-entry"; return () => marker;',
        "style.css": b".demo-plugin { background-image: url('assets/logo.svg'); }",
        "assets/logo.svg": (
            b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"></svg>'
        ),
    }


def catalog_plugin(
    files: dict[str, bytes],
    *,
    manifest: dict[str, Any] | None = None,
    trust: str = "stock",
    repository: str = "example/demo-plugin",
    source_commit: str = COMMIT,
    plugin_root: str = "plugins/demo.plugin",
) -> dict[str, Any]:
    selected_manifest = manifest or json.loads(files["manifest.json"])
    return {
        "id": selected_manifest["id"],
        "trust": trust,
        "repository": repository,
        "sourceCommit": source_commit,
        "pluginRoot": plugin_root,
        "manifest": selected_manifest,
        "files": [
            {
                "path": path,
                "sha256": hashlib.sha256(content).hexdigest(),
                "size": len(content),
            }
            for path, content in files.items()
        ],
    }


def write_catalog(path: Path, plugin: dict[str, Any], *, schema: int = 2) -> None:
    path.write_text(
        json.dumps({"schemaVersion": schema, "plugins": [plugin]}),
        encoding="utf-8",
    )


def catalog_manager(
    root: Path, files: dict[str, bytes], plugin: dict[str, Any]
) -> PluginManager:
    catalog = root / "catalog.json"
    write_catalog(catalog, plugin)
    manager = PluginManager(
        root / "plugins",
        root / "state.json",
        catalog_url=catalog.resolve().as_uri(),
        allow_local_catalog=True,
    )
    manager._download_catalog_file = (  # type: ignore[method-assign]
        lambda _catalog_item, file_item: files[file_item["path"]]
    )
    return manager


class FakeRedirectResponse:
    status = 302

    def __init__(self, location: str) -> None:
        self.headers = {"Location": location}

    def getcode(self) -> int:
        return self.status

    def close(self) -> None:
        return None


class PluginManagerTests(unittest.TestCase):
    def test_cached_catalog_payload_never_fetches_network(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manager = PluginManager(root / "plugins", root / "state.json")
            with mock.patch.object(manager, "_read_json_url") as read_json:
                payload = manager.cached_catalog_payload()
            read_json.assert_not_called()
            self.assertEqual(payload["plugins"], [])

    def test_local_catalog_requires_explicit_test_opt_in(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            catalog = Path(temp) / "catalog.json"
            catalog.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(
                PluginError, "require allow_local_catalog=True"
            ):
                PluginManager(
                    Path(temp) / "plugins",
                    Path(temp) / "state.json",
                    catalog_url=catalog.resolve().as_uri(),
                )

    def test_repository_catalog_is_schema_v2_and_lists_without_installing(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manager = PluginManager(
                root / "plugins",
                root / "state.json",
                catalog_url=(ROOT / "plugin_catalog.json").resolve().as_uri(),
                allow_local_catalog=True,
            )
            catalog = manager.catalog_plugins()
            self.assertEqual(
                {plugin["id"] for plugin in catalog},
                {"amazify.true-big-mode", "amazify.theme.signal-studio"},
            )
            self.assertTrue(
                all(plugin["verification"]["required"] for plugin in catalog)
            )
            self.assertFalse(any(plugin["installed"] for plugin in catalog))
            self.assertEqual(manager.runtime_snapshot(), [])

    def test_sample_plugins_seed_verified_and_disabled_with_runtime_sources(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manager = PluginManager(root / "plugins", root / "state.json")

            copied = manager.ensure_sample_plugins(ROOT / "sample_plugins")
            packages = manager.list_plugins()
            snapshot = manager.runtime_snapshot()

            self.assertEqual(
                set(copied),
                {"amazify.true-big-mode", "amazify.theme.signal-studio"},
            )
            self.assertTrue(all(not package.enabled for package in packages))
            self.assertTrue(all(package.security["verified"] for package in packages))
            self.assertTrue(all(not plugin["enabled"] for plugin in snapshot))
            self.assertTrue(all(plugin["source"]["entry"] for plugin in snapshot))
            self.assertTrue(all(plugin["source"]["styles"] for plugin in snapshot))

    def test_install_is_verified_atomic_and_disabled_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            files = demo_files()
            manager = catalog_manager(root, files, catalog_plugin(files))
            package = manager.install_from_catalog("demo.plugin")
            self.assertFalse(package.enabled)
            self.assertTrue(package.security["verified"])
            self.assertEqual(package.security["method"], "catalog-sha256")
            self.assertEqual(package.security["sourceCommit"], COMMIT)
            self.assertEqual(
                {
                    path.relative_to(package.root).as_posix()
                    for path in package.root.rglob("*")
                    if path.is_file()
                },
                set(files),
            )
            manager.enable("demo.plugin")
            snapshot = manager.runtime_snapshot()[0]
            self.assertTrue(snapshot["enabled"])
            self.assertIn("demo-plugin-entry", snapshot["source"]["entry"])
            self.assertEqual(
                snapshot["source"]["assets"][0]["mimeType"], "image/svg+xml"
            )

    def test_community_plugin_never_auto_enables_on_first_install(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            files = demo_files()
            manager = catalog_manager(
                root, files, catalog_plugin(files, trust="community")
            )
            package = manager.install_from_catalog("demo.plugin")
            self.assertFalse(package.enabled)
            self.assertEqual(package.security["trust"], "community")

    def test_tamper_fails_closed_and_cannot_be_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            files = demo_files()
            manager = catalog_manager(root, files, catalog_plugin(files))
            manager.install_from_catalog("demo.plugin")
            manager.enable("demo.plugin")
            (root / "plugins" / "demo.plugin" / "plugin.js").write_text(
                "tampered()", encoding="utf-8"
            )
            package = manager.get("demo.plugin")
            self.assertFalse(package.enabled)
            self.assertFalse(package.security["verified"])
            self.assertFalse(manager.runtime_snapshot()[0]["enabled"])
            with self.assertRaisesRegex(PluginError, "integrity verification failed"):
                manager.enable("demo.plugin")

    def test_identical_verified_reinstall_preserves_enabled_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            files = demo_files()
            manager = catalog_manager(root, files, catalog_plugin(files))
            manager.install_from_catalog("demo.plugin")
            manager.enable("demo.plugin")
            reordered_catalog_plugin = catalog_plugin(files)
            reordered_catalog_plugin["files"].reverse()
            write_catalog(root / "catalog.json", reordered_catalog_plugin)

            reinstalled = manager.install_from_catalog("demo.plugin")

            self.assertTrue(reinstalled.enabled)
            self.assertTrue(reinstalled.security["verified"])
            self.assertEqual(reinstalled.security["sourceCommit"], COMMIT)

    def test_changed_commit_or_manifest_inventory_installs_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            files = demo_files()
            manager = catalog_manager(root, files, catalog_plugin(files))
            manager.install_from_catalog("demo.plugin")
            manager.enable("demo.plugin")

            changed_commit = "2" * 40
            write_catalog(
                root / "catalog.json",
                catalog_plugin(files, source_commit=changed_commit),
            )
            commit_update = manager.install_from_catalog("demo.plugin")
            self.assertFalse(commit_update.enabled)
            self.assertEqual(commit_update.security["sourceCommit"], changed_commit)

            manager.enable("demo.plugin")
            permission_manifest = demo_manifest()
            permission_manifest["permissions"] = ["dom-read"]
            permission_files = demo_files(permission_manifest)
            write_catalog(
                root / "catalog.json",
                catalog_plugin(
                    permission_files,
                    manifest=permission_manifest,
                    source_commit=changed_commit,
                ),
            )
            manager._download_catalog_file = (  # type: ignore[method-assign]
                lambda _catalog_item, file_item: permission_files[file_item["path"]]
            )
            manifest_update = manager.install_from_catalog("demo.plugin")
            self.assertFalse(manifest_update.enabled)
            self.assertEqual(manifest_update.manifest.permissions, ["dom-read"])

    def test_rejects_noncanonical_and_windows_reserved_plugin_ids(self) -> None:
        rejected_ids = [
            "demo.plugin.",
            "demo.plugin ",
            "demo..plugin",
            "con.plugin",
            "demo.prn",
            "aux.demo",
            "nul",
            "com1.plugin",
            "plugin.lpt9",
        ]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manager = PluginManager(root / "plugins", root / "state.json")
            for index, plugin_id in enumerate(rejected_ids):
                plugin_root = root / f"invalid-manifest-{index}"
                plugin_root.mkdir()
                manifest_path = plugin_root / "manifest.json"
                manifest_path.write_text(
                    json.dumps(demo_manifest(plugin_id=plugin_id)), encoding="utf-8"
                )
                with (
                    self.subTest(plugin_id=plugin_id),
                    self.assertRaisesRegex(PluginError, "Invalid plugin id"),
                ):
                    manager.load_manifest(manifest_path)

            with mock.patch.object(manager, "catalog_plugins") as catalog_plugins:
                with self.assertRaisesRegex(PluginError, "Invalid plugin id"):
                    manager.install_from_catalog("demo.plugin ")
                catalog_plugins.assert_not_called()

            files = demo_files()
            catalog_entry = catalog_plugin(files)
            catalog_entry["id"] = "demo.plugin."
            catalog = root / "catalog.json"
            write_catalog(catalog, catalog_entry)
            manager.catalog_url = catalog.resolve().as_uri()
            manager.allow_local_catalog = True
            manager._validate_catalog_url(manager.catalog_url)
            with self.assertRaisesRegex(PluginError, "Invalid plugin id"):
                manager.catalog_plugins(force_refresh=True)

    def test_installed_directory_must_match_canonical_manifest_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plugin_root = root / "plugins" / "different.plugin"
            plugin_root.mkdir(parents=True)
            for relative, content in demo_files().items():
                destination = plugin_root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(content)

            manager = PluginManager(root / "plugins", root / "state.json")

            self.assertEqual(manager.list_plugins(), [])

    def test_failed_state_commit_rolls_back_files_and_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plugin_root = root / "plugins" / "demo.plugin"
            plugin_root.mkdir(parents=True)
            original_files = demo_files()
            for relative, content in original_files.items():
                destination = plugin_root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(content)
            manager = PluginManager(root / "plugins", root / "state.json")
            updated_manifest = demo_manifest(version="0.2.0")
            updated_files = demo_files(updated_manifest)
            catalog = root / "catalog.json"
            write_catalog(
                catalog, catalog_plugin(updated_files, manifest=updated_manifest)
            )
            manager.catalog_url = catalog.resolve().as_uri()
            manager.allow_local_catalog = True
            manager._validate_catalog_url(manager.catalog_url)
            manager._download_catalog_file = (  # type: ignore[method-assign]
                lambda _catalog_item, file_item: updated_files[file_item["path"]]
            )
            with (
                mock.patch.object(
                    manager, "_save_state", side_effect=OSError("disk full")
                ),
                self.assertRaisesRegex(PluginError, "Unable to install"),
            ):
                manager.install_from_catalog("demo.plugin")
            self.assertEqual(
                (plugin_root / "manifest.json").read_bytes(),
                original_files["manifest.json"],
            )
            self.assertFalse(
                any(
                    path.name.startswith(".demo.plugin.backup-")
                    for path in (root / "plugins").iterdir()
                )
            )

    def test_catalog_rejects_legacy_schema_mutable_commit_and_bad_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            files = demo_files()
            plugin = catalog_plugin(files)
            catalog = root / "catalog.json"
            write_catalog(catalog, plugin, schema=1)
            manager = PluginManager(
                root / "plugins",
                root / "state.json",
                catalog_url=catalog.resolve().as_uri(),
                allow_local_catalog=True,
            )
            with self.assertRaisesRegex(PluginError, "schemaVersion must be 2"):
                manager.catalog_plugins(force_refresh=True)
            plugin["sourceCommit"] = "main"
            write_catalog(catalog, plugin)
            with self.assertRaisesRegex(PluginError, "immutable 40-character"):
                manager.catalog_plugins(force_refresh=True)
            plugin["sourceCommit"] = COMMIT
            plugin["files"][0]["path"] = "../manifest.json"
            write_catalog(catalog, plugin)
            with self.assertRaisesRegex(PluginError, "Invalid plugin path"):
                manager.catalog_plugins(force_refresh=True)

    def test_hash_size_and_manifest_mismatch_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            files = demo_files()
            plugin = catalog_plugin(files)
            manager = catalog_manager(root, files, plugin)
            plugin["files"][1]["sha256"] = "0" * 64
            write_catalog(root / "catalog.json", plugin)
            with self.assertRaisesRegex(PluginError, "hash mismatch"):
                manager.install_from_catalog("demo.plugin")
            plugin = catalog_plugin(files)
            plugin["files"][1]["size"] += 1
            write_catalog(root / "catalog.json", plugin)
            with self.assertRaisesRegex(PluginError, "size mismatch"):
                manager.install_from_catalog("demo.plugin")
            plugin = catalog_plugin(files)
            plugin["manifest"] = demo_manifest(version="9.9.9")
            write_catalog(root / "catalog.json", plugin)
            with self.assertRaisesRegex(PluginError, "manifest does not match"):
                manager.install_from_catalog("demo.plugin")

    def test_redirect_to_non_github_host_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            manager = PluginManager(Path(temp) / "plugins", Path(temp) / "state.json")
            with (
                mock.patch.object(
                    manager,
                    "_open_once",
                    return_value=FakeRedirectResponse(
                        "https://example.com/plugin_catalog.json"
                    ),
                ),
                self.assertRaises(PluginError),
            ):
                manager._read_remote_url_bytes(
                    manager.catalog_url,
                    max_bytes=1024,
                    validator=manager._validate_catalog_url,
                    purpose="plugin catalog",
                )

    def test_state_writes_remain_valid_under_concurrent_commands(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plugin_root = root / "plugins" / "demo.plugin"
            plugin_root.mkdir(parents=True)
            for relative, content in demo_files().items():
                destination = plugin_root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(content)
            manager = PluginManager(root / "plugins", root / "state.json")

            def toggle(index: int) -> None:
                if index % 2:
                    manager.enable("demo.plugin")
                else:
                    manager.disable("demo.plugin")

            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
                list(executor.map(toggle, range(40)))
            state = json.loads((root / "state.json").read_text(encoding="utf-8"))
            self.assertIsInstance(state["enabled"]["demo.plugin"], bool)

    def test_rejects_manifest_paths_that_escape_plugin_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plugin = root / "plugins" / "bad"
            plugin.mkdir(parents=True)
            manifest = demo_manifest(plugin_id="bad.plugin.path")
            manifest["entry"] = "../outside.js"
            manifest["assets"] = {"bad": "../outside.svg"}
            (plugin / "manifest.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )
            manager = PluginManager(root / "plugins", root / "state.json")
            with self.assertRaises(PluginError):
                manager.load_manifest(plugin / "manifest.json")


if __name__ == "__main__":
    unittest.main()
