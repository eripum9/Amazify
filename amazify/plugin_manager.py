from __future__ import annotations

import base64
import hashlib
import json
import math
import mimetypes
import os
import re
import shutil
import stat
import tempfile
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, unquote, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from . import __version__

PLUGIN_ID_SYNTAX_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,127}$")
WINDOWS_RESERVED_PLUGIN_ID_COMPONENTS = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}
GITHUB_OWNER_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
GITHUB_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
DEFAULT_CATALOG_URL = (
    "https://raw.githubusercontent.com/eripum9/Amazify/main/plugin_catalog.json"
)
OFFICIAL_CATALOG_REPOSITORIES = {("eripum9", "amazify")}
CATALOG_SCHEMA_VERSION = 2
CATALOG_CACHE_SECONDS = 60
MAX_CATALOG_BYTES = 1024 * 1024
MAX_STATE_BYTES = 2 * 1024 * 1024
MAX_PLUGIN_FILE_BYTES = 2 * 1024 * 1024
MAX_PLUGIN_ASSET_BYTES = 5 * 1024 * 1024
MAX_PLUGIN_PACKAGE_BYTES = 20 * 1024 * 1024
MAX_REDIRECTS = 3
PLUGIN_TYPES = {"theme", "ui"}
PLUGIN_SETTING_TYPES = {"boolean", "color", "image", "range", "select", "text"}
PLUGIN_SETTING_ID_RE = re.compile(r"^[a-z][A-Za-z0-9._-]{0,63}$")
PLUGIN_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
MAX_PLUGIN_SETTINGS = 32
MAX_PLUGIN_SETTING_OPTIONS = 64
MAX_PLUGIN_SETTING_IMAGE_BYTES = 2 * 1024 * 1024
PLUGIN_SETTING_IMAGE_MIME_TYPES = {
    "image/gif",
    "image/jpeg",
    "image/png",
    "image/webp",
}
TRUST_LEVELS = {"stock", "community"}
PERMISSIONS = {
    "dom-style",
    "dom-read",
    "dom-write",
    "bridge-state",
    "bridge-command",
    "network",
    "lyrics-provider",
}
REDIRECT_STATUSES = {301, 302, 303, 307, 308}


class PluginError(ValueError):
    pass


def _validate_plugin_id(plugin_id: object) -> str:
    if not isinstance(plugin_id, str):
        raise PluginError("Invalid plugin id")
    components = plugin_id.split(".")
    if (
        plugin_id != plugin_id.rstrip(". ")
        or not PLUGIN_ID_SYNTAX_RE.fullmatch(plugin_id)
        or any(not component for component in components)
        or any(
            component.casefold() in WINDOWS_RESERVED_PLUGIN_ID_COMPONENTS
            for component in components
        )
    ):
        raise PluginError(f"Invalid plugin id: {plugin_id}")
    return plugin_id


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        return None


@dataclass(slots=True)
class PluginManifest:
    id: str
    name: str
    version: str
    author: str
    type: str
    description: str
    entry: str | None
    styles: list[str]
    assets: dict[str, str]
    permissions: list[str]
    settings: list[dict[str, Any]]
    minimum_amazify_version: str
    amazon_music: dict[str, Any]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PluginManifest":
        plugin_id = _validate_plugin_id(data.get("id"))

        plugin_type = _required_str(data, "type")
        if plugin_type not in PLUGIN_TYPES:
            raise PluginError(f"Plugin {plugin_id} has unsupported type: {plugin_type}")

        permissions = data.get("permissions", [])
        if not isinstance(permissions, list) or not all(
            isinstance(item, str) and item for item in permissions
        ):
            raise PluginError(f"Plugin {plugin_id} permissions must be a string list")
        if len(set(permissions)) != len(permissions):
            raise PluginError(f"Plugin {plugin_id} permissions must not repeat")
        unknown_permissions = sorted(set(permissions) - PERMISSIONS)
        if unknown_permissions:
            raise PluginError(
                f"Plugin {plugin_id} uses unknown permissions: {unknown_permissions}"
            )
        if "lyrics-provider" in permissions and plugin_id != "amazify.karaoke-lyrics":
            raise PluginError(
                "The lyrics-provider permission is reserved for Amazify Karaoke Lyrics"
            )

        styles = data.get("styles", [])
        if not isinstance(styles, list) or not all(
            isinstance(item, str) for item in styles
        ):
            raise PluginError(f"Plugin {plugin_id} styles must be a string list")
        if len(set(styles)) != len(styles):
            raise PluginError(f"Plugin {plugin_id} styles must not repeat")

        entry = data.get("entry")
        if entry is not None and not isinstance(entry, str):
            raise PluginError(f"Plugin {plugin_id} entry must be a string")

        assets = _normalize_assets(plugin_id, data.get("assets", {}))
        settings = _normalize_plugin_settings(plugin_id, data.get("settings", []))
        minimum_amazify_version = str(
            data.get("minimumAmazifyVersion", "")
        ).strip()
        if minimum_amazify_version and not VERSION_RE.fullmatch(
            minimum_amazify_version
        ):
            raise PluginError(
                f"Plugin {plugin_id} has invalid minimumAmazifyVersion"
            )
        amazon_music = data.get("amazonMusic", {})
        if not isinstance(amazon_music, dict):
            raise PluginError(f"Plugin {plugin_id} amazonMusic must be an object")

        manifest = cls(
            id=plugin_id,
            name=_required_str(data, "name"),
            version=_required_str(data, "version"),
            author=_required_str(data, "author"),
            type=plugin_type,
            description=str(data.get("description", "")),
            entry=entry.strip() if entry else None,
            styles=[item.strip() for item in styles],
            assets=assets,
            permissions=list(permissions),
            settings=settings,
            minimum_amazify_version=minimum_amazify_version,
            amazon_music=amazon_music,
        )
        if not manifest.entry and not manifest.styles:
            raise PluginError(f"Plugin {plugin_id} must define entry or styles")
        return manifest

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "author": self.author,
            "type": self.type,
            "description": self.description,
            "entry": self.entry,
            "styles": list(self.styles),
            "assets": dict(self.assets),
            "permissions": list(self.permissions),
            "settings": _json_copy(self.settings),
            "minimumAmazifyVersion": self.minimum_amazify_version,
            "amazonMusic": dict(self.amazon_music),
        }


@dataclass(slots=True)
class PluginPackage:
    root: Path
    manifest: PluginManifest
    enabled: bool
    security: dict[str, Any]

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "manifest": self.manifest.to_public_dict(),
            "enabled": self.enabled,
            "compatible": not self.manifest.minimum_amazify_version
            or compare_versions(
                __version__, self.manifest.minimum_amazify_version
            )
            >= 0,
            "rootName": self.root.name,
            "security": _json_copy(self.security),
        }


class PluginManager:
    def __init__(
        self,
        plugin_dir: Path,
        state_file: Path,
        *,
        catalog_url: str | None = None,
        allow_local_catalog: bool = False,
    ) -> None:
        self.plugin_dir = plugin_dir
        self.state_file = state_file
        self.catalog_url = (
            catalog_url
            or os.environ.get("AMAZIFY_PLUGIN_CATALOG_URL")
            or DEFAULT_CATALOG_URL
        )
        self.allow_local_catalog = bool(allow_local_catalog)
        self._lock = threading.RLock()
        self._opener = build_opener(_NoRedirectHandler())
        self._validate_catalog_url(self.catalog_url)
        self.plugin_dir.mkdir(parents=True, exist_ok=True)
        self._catalog_cache_file = self.state_file.parent / "plugin_catalog_cache.json"
        self._state = self._load_state()
        self._catalog_cache: tuple[float, list[dict[str, Any]]] | None = None
        self._load_catalog_cache()

    def _load_state(self) -> dict[str, Any]:
        default = {"enabled": {}, "installed": {}}
        if not self.state_file.exists():
            return default
        try:
            raw = self._read_bounded_file(self.state_file, MAX_STATE_BYTES)
            data = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, PluginError):
            return default
        if not isinstance(data, dict):
            return default
        enabled = data.get("enabled")
        installed = data.get("installed")
        data["enabled"] = enabled if isinstance(enabled, dict) else {}
        data["installed"] = installed if isinstance(installed, dict) else {}
        return data

    def _save_state(self) -> None:
        self._atomic_write_json(self.state_file, self._state)

    def ensure_sample_plugins(self, source_dir: Path) -> list[str]:
        with self._lock:
            copied: list[str] = []
            if not source_dir.exists():
                return copied
            for sample in source_dir.iterdir():
                if not sample.is_dir() or self._path_is_link(sample):
                    continue
                manifest_path = sample / "manifest.json"
                if not manifest_path.exists():
                    continue
                sample_id = _validate_plugin_id(sample.name)
                target = self.plugin_dir / sample_id
                self._assert_plugin_child_path(target)
                if target.exists():
                    continue

                self._assert_tree_has_no_links(sample)
                staging = self._new_staging_dir(sample_id)
                try:
                    staging.rmdir()
                    shutil.copytree(sample, staging, symlinks=False)
                    self._assert_tree_has_no_links(staging)
                    manifest = self.load_manifest(staging / "manifest.json")
                    if manifest.id != sample_id:
                        raise PluginError(
                            f"Bundled plugin directory {sample_id} does not match {manifest.id}"
                        )
                    files = self._inventory_for_tree(staging)
                    os.replace(staging, target)
                    self._state["enabled"].setdefault(manifest.id, False)
                    self._state["installed"][manifest.id] = {
                        "trust": "stock",
                        "method": "bundled",
                        "repository": "",
                        "sourceCommit": "",
                        "pluginRoot": sample_id,
                        "files": files,
                    }
                    self._save_state()
                    copied.append(sample_id)
                finally:
                    if staging.exists():
                        self._remove_tree(staging)
            return copied

    def catalog_plugins(self, *, force_refresh: bool = False) -> list[dict[str, Any]]:
        with self._lock:
            if not force_refresh and self._catalog_cache is not None:
                cached_at, cached_plugins = self._catalog_cache
                if _now() - cached_at < CATALOG_CACHE_SECONDS:
                    return self._annotate_catalog_plugins(cached_plugins)

            data = self._read_json_url(self.catalog_url)
            normalized = self._normalize_catalog_document(data)
            self._catalog_cache = (_now(), normalized)
            self._save_catalog_cache(normalized)
            return self._annotate_catalog_plugins(normalized)

    def catalog_payload(self, *, force_refresh: bool = False) -> dict[str, Any]:
        try:
            return {
                "plugins": self.catalog_plugins(force_refresh=force_refresh),
                "error": "",
                "url": self.catalog_url,
            }
        except PluginError as exc:
            return {"plugins": [], "error": str(exc), "url": self.catalog_url}

    def cached_catalog_payload(self) -> dict[str, Any]:
        with self._lock:
            plugins = self._catalog_cache[1] if self._catalog_cache is not None else []
            return {
                "plugins": self._annotate_catalog_plugins(plugins),
                "error": "",
                "url": self.catalog_url,
            }

    def _load_catalog_cache(self) -> None:
        with self._lock:
            try:
                raw = self._read_bounded_file(
                    self._catalog_cache_file,
                    MAX_CATALOG_BYTES,
                )
                data = json.loads(raw.decode("utf-8"))
                normalized = self._normalize_catalog_document(data)
                updated_at = data.get("updatedAt", 0.0)
                cached_at = (
                    float(updated_at) if isinstance(updated_at, (int, float)) else 0.0
                )
                self._catalog_cache = (cached_at, normalized)
            except (
                OSError,
                UnicodeDecodeError,
                ValueError,
                json.JSONDecodeError,
                PluginError,
            ):
                return

    def _save_catalog_cache(self, plugins: list[dict[str, Any]]) -> None:
        payload = {
            "schemaVersion": CATALOG_SCHEMA_VERSION,
            "updatedAt": _now(),
            "plugins": plugins,
        }
        try:
            self._atomic_write_json(self._catalog_cache_file, payload)
        except OSError:
            pass

    def install_from_catalog(self, plugin_id: str) -> PluginPackage:
        with self._lock:
            plugin_id = _validate_plugin_id(plugin_id)

            catalog_plugins = self.catalog_plugins(force_refresh=True)
            catalog_item = next(
                (item for item in catalog_plugins if item.get("id") == plugin_id),
                None,
            )
            if not catalog_item:
                raise PluginError(f"Plugin not found in catalog: {plugin_id}")
            if catalog_item.get("compatible") is False:
                required = catalog_item.get("minimumAmazifyVersion", "")
                raise PluginError(
                    f"Plugin {plugin_id} requires Amazify {required} or newer"
                )

            target = self.plugin_dir / plugin_id
            self._assert_plugin_child_path(target)
            preserve_enabled = False
            if target.exists() and not self._path_is_link(target):
                try:
                    existing = self.get(plugin_id)
                    existing_security = existing.security
                    preserve_enabled = bool(
                        existing.enabled
                        and existing_security.get("verified") is True
                        and existing_security.get("method") == "catalog-sha256"
                        and existing_security.get("trust") == catalog_item["trust"]
                        and existing_security.get("repository")
                        == catalog_item["repository"]
                        and existing_security.get("sourceCommit")
                        == catalog_item["sourceCommit"]
                        and existing_security.get("pluginRoot")
                        == catalog_item["pluginRoot"]
                        and self._normalized_inventory_identity(
                            existing_security.get("files")
                        )
                        == self._normalized_inventory_identity(catalog_item["files"])
                    )
                except PluginError:
                    preserve_enabled = False

            files = catalog_item["files"]
            staging = self._new_staging_dir(plugin_id)
            backup = self.plugin_dir / f".{plugin_id}.backup-{uuid.uuid4().hex}"
            self._assert_plugin_child_path(backup)
            previous_state = _json_copy(self._state)
            target_moved = False
            staged_installed = False

            try:
                for file_item in files:
                    relative_path = file_item["path"]
                    destination = self._resolve_download_target(staging, relative_path)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    raw = self._download_catalog_file(catalog_item, file_item)
                    if len(raw) != file_item["size"]:
                        raise PluginError(
                            f"Catalog plugin {plugin_id} size mismatch for {relative_path}"
                        )
                    digest = hashlib.sha256(raw).hexdigest()
                    if digest != file_item["sha256"]:
                        raise PluginError(
                            f"Catalog plugin {plugin_id} hash mismatch for {relative_path}"
                        )
                    with destination.open("xb") as handle:
                        handle.write(raw)

                self._assert_tree_has_no_links(staging)
                self._verify_tree_inventory(staging, files)
                manifest = self.load_manifest(staging / "manifest.json")
                if manifest.to_public_dict() != catalog_item["manifest"]:
                    raise PluginError(
                        f"Catalog plugin {plugin_id} downloaded manifest does not match catalog"
                    )

                if target.exists() or target.is_symlink():
                    if self._path_is_link(target):
                        raise PluginError(
                            f"Installed plugin path is a link: {plugin_id}"
                        )
                    os.replace(target, backup)
                    target_moved = True
                os.replace(staging, target)
                staged_installed = True

                # A stale enabled-state entry is not authority to activate new code.
                self._state["enabled"][plugin_id] = preserve_enabled
                self._state["installed"][plugin_id] = {
                    "trust": catalog_item["trust"],
                    "method": "catalog-sha256",
                    "repository": catalog_item["repository"],
                    "sourceCommit": catalog_item["sourceCommit"],
                    "pluginRoot": catalog_item["pluginRoot"],
                    "files": _json_copy(files),
                }
                self._save_state()
            except Exception as exc:
                self._state = previous_state
                if staged_installed and target.exists():
                    self._remove_tree(target)
                if target_moved and backup.exists():
                    os.replace(backup, target)
                if isinstance(exc, PluginError):
                    raise
                raise PluginError(
                    f"Unable to install catalog plugin {plugin_id}: {exc}"
                ) from exc
            finally:
                if staging.exists():
                    self._remove_tree(staging)

            if backup.exists():
                try:
                    self._remove_tree(backup)
                except (OSError, PluginError):
                    # Installation and state commit already succeeded. A stale, hidden
                    # backup is safer than rolling a verified install back at this point.
                    pass
            return self.get(plugin_id)

    def list_plugins(self) -> list[PluginPackage]:
        with self._lock:
            packages: list[PluginPackage] = []
            for child in sorted(
                self.plugin_dir.iterdir(), key=lambda item: item.name.lower()
            ):
                if (
                    child.name.startswith(".")
                    or not child.is_dir()
                    or self._path_is_link(child)
                ):
                    continue
                manifest_path = child / "manifest.json"
                if not manifest_path.exists():
                    continue
                try:
                    directory_id = _validate_plugin_id(child.name)
                    self._assert_tree_has_no_links(child)
                    manifest = self.load_manifest(manifest_path)
                    if manifest.id != directory_id:
                        raise PluginError(
                            f"Plugin directory {directory_id} does not match {manifest.id}"
                        )
                except PluginError:
                    continue
                security = self._plugin_security(child, manifest.id)
                requested_enabled = bool(self._state["enabled"].get(manifest.id, False))
                requires_integrity = security.get("method") in {
                    "catalog-sha256",
                    "bundled",
                }
                packages.append(
                    PluginPackage(
                        root=child,
                        manifest=manifest,
                        enabled=requested_enabled
                        and (
                            not manifest.minimum_amazify_version
                            or compare_versions(
                                __version__, manifest.minimum_amazify_version
                            )
                            >= 0
                        )
                        and (
                            not requires_integrity or security.get("verified") is True
                        ),
                        security=security,
                    )
                )
            return packages

    def load_manifest(self, manifest_path: Path) -> PluginManifest:
        with self._lock:
            try:
                raw = self._read_bounded_file(manifest_path, MAX_PLUGIN_FILE_BYTES)
                data = json.loads(raw.decode("utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise PluginError(f"Invalid manifest JSON: {manifest_path}") from exc
            if not isinstance(data, dict):
                raise PluginError(f"Manifest must be an object: {manifest_path}")
            manifest = PluginManifest.from_dict(data)
            root = manifest_path.parent
            for relative in [
                *(manifest.styles or []),
                *([manifest.entry] if manifest.entry else []),
                *manifest.assets.values(),
            ]:
                self._resolve_plugin_file(root, relative)
            return manifest

    def get(self, plugin_id: str) -> PluginPackage:
        with self._lock:
            for package in self.list_plugins():
                if package.manifest.id == plugin_id:
                    return package
            raise PluginError(f"Plugin not found: {plugin_id}")

    def enable(self, plugin_id: str) -> PluginPackage:
        with self._lock:
            package = self.get(plugin_id)
            required = package.manifest.minimum_amazify_version
            if required and compare_versions(__version__, required) < 0:
                self._state["enabled"][package.manifest.id] = False
                self._save_state()
                raise PluginError(
                    f"Plugin {package.manifest.id} requires Amazify {required} or newer"
                )
            if (
                package.security.get("method") in {"catalog-sha256", "bundled"}
                and package.security.get("verified") is not True
            ):
                self._state["enabled"][package.manifest.id] = False
                self._save_state()
                raise PluginError(
                    f"Plugin integrity verification failed: {package.manifest.id}"
                )
            self._state["enabled"][package.manifest.id] = True
            self._save_state()
            return PluginPackage(package.root, package.manifest, True, package.security)

    def disable(self, plugin_id: str) -> PluginPackage:
        with self._lock:
            package = self.get(plugin_id)
            self._state["enabled"][package.manifest.id] = False
            self._save_state()
            return PluginPackage(
                package.root, package.manifest, False, package.security
            )

    def disable_all(self) -> None:
        with self._lock:
            for package in self.list_plugins():
                self._state["enabled"][package.manifest.id] = False
            self._save_state()

    def public_plugins(self) -> list[dict[str, Any]]:
        with self._lock:
            return [package.to_public_dict() for package in self.list_plugins()]

    def runtime_snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            snapshot: list[dict[str, Any]] = []
            for package in self.list_plugins():
                manifest = package.manifest
                source: dict[str, Any] = {"entry": "", "styles": [], "assets": []}
                if manifest.entry:
                    source["entry"] = self._read_plugin_file(
                        package.root, manifest.entry
                    )
                for style_path in manifest.styles:
                    source["styles"].append(
                        {
                            "path": style_path,
                            "content": self._read_plugin_file(package.root, style_path),
                        }
                    )
                for name, asset_path in manifest.assets.items():
                    source["assets"].append(
                        self._read_plugin_asset(package.root, name, asset_path)
                    )
                snapshot.append(
                    {
                        "manifest": manifest.to_public_dict(),
                        "enabled": package.enabled,
                        "security": _json_copy(package.security),
                        "source": source,
                    }
                )
            return snapshot

    def _normalize_catalog_document(self, data: object) -> list[dict[str, Any]]:
        if not isinstance(data, dict):
            raise PluginError("Plugin catalog must be a JSON object")
        if data.get("schemaVersion") != CATALOG_SCHEMA_VERSION:
            raise PluginError(
                f"Plugin catalog schemaVersion must be {CATALOG_SCHEMA_VERSION}; legacy catalogs are not accepted"
            )
        plugins = data.get("plugins")
        if not isinstance(plugins, list):
            raise PluginError("Plugin catalog must contain a plugins list")
        normalized = [self._normalize_catalog_plugin(item) for item in plugins]
        ids = [item["id"].casefold() for item in normalized]
        if len(set(ids)) != len(ids):
            raise PluginError("Plugin catalog contains duplicate plugin ids")
        return normalized

    def _normalize_catalog_plugin(self, item: object) -> dict[str, Any]:
        if not isinstance(item, dict):
            raise PluginError("Plugin catalog entries must be objects")
        manifest_data = item.get("manifest")
        if not isinstance(manifest_data, dict):
            raise PluginError("Plugin catalog entries must include a manifest object")
        manifest = PluginManifest.from_dict(manifest_data)
        item_id = _validate_plugin_id(item.get("id"))
        if item_id != manifest.id:
            raise PluginError(
                f"Catalog plugin id mismatch: entry {item_id}, manifest {manifest.id}"
            )

        trust = _required_str(item, "trust")
        if trust not in TRUST_LEVELS:
            raise PluginError(
                f"Catalog plugin {manifest.id} has invalid trust: {trust}"
            )
        repository = self._validate_repository(_required_str(item, "repository"))
        source_commit = _required_str(item, "sourceCommit")
        if not COMMIT_RE.fullmatch(source_commit) or source_commit == "0" * 40:
            raise PluginError(
                f"Catalog plugin {manifest.id} sourceCommit must be an immutable 40-character lowercase commit"
            )
        plugin_root = self._normalize_relative_path(_required_str(item, "pluginRoot"))
        catalog_minimum_version = str(
            item.get("minimumAmazifyVersion", "")
        ).strip()
        if catalog_minimum_version and not VERSION_RE.fullmatch(
            catalog_minimum_version
        ):
            raise PluginError(
                f"Catalog plugin {manifest.id} has invalid minimumAmazifyVersion"
            )
        if (
            catalog_minimum_version
            and manifest.minimum_amazify_version
            and catalog_minimum_version != manifest.minimum_amazify_version
        ):
            raise PluginError(
                f"Catalog plugin {manifest.id} minimumAmazifyVersion does not match its manifest"
            )
        minimum_amazify_version = (
            manifest.minimum_amazify_version or catalog_minimum_version
        )

        files = item.get("files")
        if not isinstance(files, list) or not files:
            raise PluginError(f"Catalog plugin {manifest.id} must include files")
        asset_paths = set(manifest.assets.values())
        normalized_files: list[dict[str, Any]] = []
        seen_paths: set[str] = set()
        total_size = 0
        for file_item in files:
            if not isinstance(file_item, dict):
                raise PluginError(
                    f"Catalog plugin {manifest.id} has an invalid file entry"
                )
            path = self._normalize_relative_path(_required_str(file_item, "path"))
            path_key = path.casefold()
            if path_key in seen_paths:
                raise PluginError(f"Catalog plugin {manifest.id} repeats file: {path}")
            seen_paths.add(path_key)
            sha256 = _required_str(file_item, "sha256")
            if not SHA256_RE.fullmatch(sha256):
                raise PluginError(
                    f"Catalog plugin {manifest.id} has invalid SHA-256 for {path}"
                )
            size = file_item.get("size")
            max_size = (
                MAX_PLUGIN_ASSET_BYTES if path in asset_paths else MAX_PLUGIN_FILE_BYTES
            )
            if (
                isinstance(size, bool)
                or not isinstance(size, int)
                or size <= 0
                or size > max_size
            ):
                raise PluginError(
                    f"Catalog plugin {manifest.id} has invalid size for {path}"
                )
            total_size += size
            normalized_files.append({"path": path, "sha256": sha256, "size": size})
        if total_size > MAX_PLUGIN_PACKAGE_BYTES:
            raise PluginError(
                f"Catalog plugin {manifest.id} exceeds package size limit"
            )

        manifest_paths = ["manifest.json"]
        if manifest.entry:
            manifest_paths.append(manifest.entry)
        manifest_paths.extend(manifest.styles)
        manifest_paths.extend(manifest.assets.values())
        normalized_manifest_paths = {
            self._normalize_relative_path(path).casefold() for path in manifest_paths
        }
        missing = sorted(normalized_manifest_paths - seen_paths)
        if missing:
            raise PluginError(f"Catalog plugin {manifest.id} missing files: {missing}")

        source_url = (
            f"https://github.com/{repository}/tree/{source_commit}/"
            + "/".join(
                quote(part, safe="") for part in PurePosixPath(plugin_root).parts
            )
        )
        return {
            "id": manifest.id,
            "trust": trust,
            "channel": trust,
            "repository": repository,
            "sourceCommit": source_commit,
            "pluginRoot": plugin_root,
            "sourceUrl": source_url,
            "manifest": manifest.to_public_dict(),
            "files": normalized_files,
            "minimumAmazifyVersion": minimum_amazify_version,
            "compatible": not minimum_amazify_version
            or compare_versions(__version__, minimum_amazify_version) >= 0,
            "verification": {
                "required": True,
                "method": "sha256",
                "fileCount": len(normalized_files),
                "totalSize": total_size,
            },
        }

    def _annotate_catalog_plugins(
        self, plugins: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        installed = {package.manifest.id: package for package in self.list_plugins()}
        annotated: list[dict[str, Any]] = []
        for plugin in plugins:
            package = installed.get(str(plugin.get("id", "")))
            item = _json_copy(plugin)
            item["installed"] = package is not None
            item["enabled"] = bool(package.enabled) if package else False
            item["installedVersion"] = package.manifest.version if package else ""
            item["latestVersion"] = item["manifest"]["version"]
            item["updateAvailable"] = (
                package is not None
                and compare_versions(
                    item["manifest"]["version"], package.manifest.version
                )
                > 0
            )
            if package is not None:
                item["installedSecurity"] = _json_copy(package.security)
            annotated.append(item)
        return annotated

    def _read_json_url(self, url: str) -> dict[str, Any]:
        try:
            raw = self._read_catalog_bytes(url)
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PluginError(f"Invalid plugin catalog JSON: {url}") from exc
        if not isinstance(data, dict):
            raise PluginError(f"Plugin catalog must be a JSON object: {url}")
        return data

    def _read_catalog_bytes(self, url: str) -> bytes:
        parsed = self._validate_catalog_url(url)
        if parsed.scheme == "file":
            path = self._file_url_path(parsed)
            if self._path_is_link(path):
                raise PluginError(f"Local plugin catalog must not be a link: {path}")
            try:
                with path.open("rb") as handle:
                    raw = handle.read(MAX_CATALOG_BYTES + 1)
            except OSError as exc:
                raise PluginError(
                    f"Unable to read local plugin catalog: {path}"
                ) from exc
            if len(raw) > MAX_CATALOG_BYTES:
                raise PluginError("Plugin catalog is too large")
            return raw
        return self._read_remote_url_bytes(
            url,
            max_bytes=MAX_CATALOG_BYTES,
            validator=self._validate_catalog_url,
            purpose="plugin catalog",
        )

    def _download_catalog_file(
        self,
        catalog_item: dict[str, Any],
        file_item: dict[str, Any],
    ) -> bytes:
        url = self._catalog_file_url(catalog_item, file_item["path"])

        def validate(candidate: str) -> Any:
            return self._validate_catalog_file_url(
                candidate,
                repository=catalog_item["repository"],
                source_commit=catalog_item["sourceCommit"],
                plugin_root=catalog_item["pluginRoot"],
                relative_path=file_item["path"],
            )

        return self._read_remote_url_bytes(
            url,
            max_bytes=file_item["size"],
            validator=validate,
            purpose=f"plugin file {catalog_item['id']}/{file_item['path']}",
        )

    def _read_remote_url_bytes(
        self,
        url: str,
        *,
        max_bytes: int,
        validator: Callable[[str], Any],
        purpose: str,
    ) -> bytes:
        current = url
        for redirect_count in range(MAX_REDIRECTS + 1):
            parsed = validator(current)
            headers = {
                "User-Agent": "Amazify/0.1",
                "Accept-Encoding": "identity",
            }
            if parsed.hostname and parsed.hostname.lower() == "api.github.com":
                headers["Accept"] = "application/vnd.github.raw+json"
            request = Request(current, headers=headers)
            try:
                response = self._open_once(request)
            except HTTPError as exc:
                if exc.code in REDIRECT_STATUSES:
                    response = exc
                else:
                    raise PluginError(
                        f"Unable to download {purpose}: HTTP {exc.code}"
                    ) from exc
            except (OSError, URLError) as exc:
                raise PluginError(f"Unable to download {purpose}: {current}") from exc

            try:
                status_value = getattr(response, "status", None)
                status = int(
                    status_value if status_value is not None else response.getcode()
                )
                if status in REDIRECT_STATUSES:
                    location = response.headers.get("Location")
                    if not location:
                        raise PluginError(
                            f"Redirect for {purpose} has no Location header"
                        )
                    if redirect_count >= MAX_REDIRECTS:
                        raise PluginError(
                            f"Too many redirects while downloading {purpose}"
                        )
                    current = urljoin(current, location)
                    validator(current)
                    continue
                if status != 200:
                    raise PluginError(f"Unable to download {purpose}: HTTP {status}")
                content_length = response.headers.get("Content-Length")
                if content_length is not None:
                    try:
                        declared_length = int(content_length)
                    except ValueError as exc:
                        raise PluginError(
                            f"Invalid Content-Length while downloading {purpose}"
                        ) from exc
                    if declared_length < 0 or declared_length > max_bytes:
                        raise PluginError(f"Downloaded {purpose} is too large")
                raw = response.read(max_bytes + 1)
                if len(raw) > max_bytes:
                    raise PluginError(f"Downloaded {purpose} is too large")
                return raw
            finally:
                response.close()
        raise PluginError(f"Too many redirects while downloading {purpose}")

    def _open_once(self, request: Request) -> Any:
        return self._opener.open(request, timeout=15)

    def _validate_catalog_url(self, url: str) -> Any:
        parsed = self._parse_secure_url(url, allow_file=self.allow_local_catalog)
        if parsed.scheme == "file":
            return parsed
        host = parsed.hostname.lower() if parsed.hostname else ""
        if host == "raw.githubusercontent.com":
            if parsed.query:
                raise PluginError("Raw GitHub catalog URLs must not contain a query")
            segments = self._decoded_url_segments(parsed.path)
            if len(segments) < 4 or segments[-1] != "plugin_catalog.json":
                raise PluginError("GitHub catalog URL must target plugin_catalog.json")
            owner, repository = segments[0], segments[1]
        elif host == "api.github.com":
            segments = self._decoded_url_segments(parsed.path)
            if len(segments) < 5 or segments[0] != "repos" or segments[3] != "contents":
                raise PluginError(
                    "GitHub API catalog URL must use the repository contents API"
                )
            if segments[-1] != "plugin_catalog.json":
                raise PluginError(
                    "GitHub API catalog URL must target plugin_catalog.json"
                )
            query = parse_qs(parsed.query, keep_blank_values=True)
            if set(query) - {"ref"} or len(query.get("ref", [])) > 1:
                raise PluginError(
                    "GitHub API catalog URL has unsupported query parameters"
                )
            owner, repository = segments[1], segments[2]
        else:
            raise PluginError(
                "Remote plugin catalogs must use approved GitHub raw or API hosts"
            )
        if (
            owner.casefold(),
            repository.casefold(),
        ) not in OFFICIAL_CATALOG_REPOSITORIES:
            raise PluginError(
                "Remote plugin catalog must come from the official Amazify repository"
            )
        return parsed

    def _validate_catalog_file_url(
        self,
        url: str,
        *,
        repository: str,
        source_commit: str,
        plugin_root: str,
        relative_path: str,
    ) -> Any:
        parsed = self._parse_secure_url(url, allow_file=False)
        if (
            parsed.hostname is None
            or parsed.hostname.lower() != "raw.githubusercontent.com"
        ):
            raise PluginError("Plugin files must use raw.githubusercontent.com")
        if parsed.query:
            raise PluginError("Plugin file URLs must not contain a query")
        owner, repo = repository.split("/", 1)
        expected = [
            owner,
            repo,
            source_commit,
            *PurePosixPath(plugin_root).parts,
            *PurePosixPath(relative_path).parts,
        ]
        if self._decoded_url_segments(parsed.path) != expected:
            raise PluginError(
                "Plugin file URL does not match its pinned catalog source"
            )
        return parsed

    def _parse_secure_url(self, url: str, *, allow_file: bool) -> Any:
        try:
            parsed = urlsplit(url)
            port = parsed.port
        except ValueError as exc:
            raise PluginError(f"Invalid plugin URL: {url}") from exc
        if (
            parsed.fragment
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise PluginError("Plugin URLs must not include credentials or fragments")
        if parsed.scheme == "file":
            if not allow_file:
                raise PluginError(
                    "Local plugin catalogs require allow_local_catalog=True"
                )
            if parsed.netloc not in {"", "localhost"} or parsed.query:
                raise PluginError("Invalid local plugin catalog URL")
            return parsed
        if parsed.scheme != "https" or not parsed.hostname:
            raise PluginError("Remote plugin URLs must use HTTPS")
        if port is not None:
            raise PluginError("Plugin URLs must not use explicit ports")
        return parsed

    def _validate_repository(self, repository: str) -> str:
        parts = repository.split("/")
        if len(parts) != 2:
            raise PluginError(f"Invalid GitHub repository: {repository}")
        owner, name = parts
        if not GITHUB_OWNER_RE.fullmatch(owner) or not GITHUB_REPOSITORY_RE.fullmatch(
            name
        ):
            raise PluginError(f"Invalid GitHub repository: {repository}")
        if name in {".", ".."} or name.lower().endswith(".git"):
            raise PluginError(f"Invalid GitHub repository: {repository}")
        return f"{owner}/{name}"

    def _catalog_file_url(
        self, catalog_item: dict[str, Any], relative_path: str
    ) -> str:
        owner, repository = catalog_item["repository"].split("/", 1)
        parts = [
            owner,
            repository,
            catalog_item["sourceCommit"],
            *PurePosixPath(catalog_item["pluginRoot"]).parts,
            *PurePosixPath(relative_path).parts,
        ]
        return "https://raw.githubusercontent.com/" + "/".join(
            quote(part, safe="") for part in parts
        )

    def _decoded_url_segments(self, path: str) -> list[str]:
        segments: list[str] = []
        for encoded in path.split("/"):
            if not encoded:
                continue
            decoded = unquote(encoded)
            if (
                not decoded
                or decoded in {".", ".."}
                or "/" in decoded
                or "\\" in decoded
            ):
                raise PluginError("Plugin URL contains an invalid path segment")
            segments.append(decoded)
        return segments

    def _file_url_path(self, parsed: Any) -> Path:
        path = unquote(parsed.path)
        if os.name == "nt" and re.match(r"^/[A-Za-z]:/", path):
            path = path[1:]
        return Path(path)

    def _plugin_security(self, root: Path, plugin_id: str) -> dict[str, Any]:
        stored = self._state.get("installed", {}).get(plugin_id)
        if not isinstance(stored, dict):
            return {
                "trust": "local",
                "verified": False,
                "method": "legacy-local",
                "status": "unverified local or legacy plugin",
                "repository": "",
                "sourceCommit": "",
                "pluginRoot": root.name,
                "files": [],
            }
        trust = str(stored.get("trust", "local"))
        method = str(stored.get("method", "legacy-local"))
        files = stored.get("files", [])
        verified = False
        if (
            isinstance(files, list)
            and files
            and method in {"catalog-sha256", "bundled"}
        ):
            try:
                normalized_files = [
                    self._normalize_inventory_file(item) for item in files
                ]
                self._verify_tree_inventory(root, normalized_files)
                verified = True
                files = normalized_files
            except PluginError:
                verified = False
        return {
            "trust": trust if trust in TRUST_LEVELS else "local",
            "verified": verified,
            "method": method,
            "status": "verified" if verified else "verification failed or unavailable",
            "repository": str(stored.get("repository", "")),
            "sourceCommit": str(stored.get("sourceCommit", "")),
            "pluginRoot": str(stored.get("pluginRoot", root.name)),
            "files": _json_copy(files) if isinstance(files, list) else [],
        }

    def _normalize_inventory_file(self, item: object) -> dict[str, Any]:
        if not isinstance(item, dict):
            raise PluginError("Invalid installed plugin inventory")
        path = self._normalize_relative_path(_required_str(item, "path"))
        sha256 = _required_str(item, "sha256")
        size = item.get("size")
        if (
            not SHA256_RE.fullmatch(sha256)
            or isinstance(size, bool)
            or not isinstance(size, int)
            or size <= 0
        ):
            raise PluginError("Invalid installed plugin inventory")
        return {"path": path, "sha256": sha256, "size": size}

    def _normalized_inventory_identity(
        self, files: object
    ) -> tuple[tuple[str, str, int], ...]:
        if not isinstance(files, list) or not files:
            raise PluginError("Invalid installed plugin inventory")
        identity = [
            (
                normalized["path"].casefold(),
                normalized["sha256"],
                normalized["size"],
            )
            for normalized in (
                self._normalize_inventory_file(item) for item in files
            )
        ]
        paths = [item[0] for item in identity]
        if len(set(paths)) != len(paths):
            raise PluginError("Invalid installed plugin inventory")
        return tuple(sorted(identity))

    def _inventory_for_tree(self, root: Path) -> list[dict[str, Any]]:
        inventory: list[dict[str, Any]] = []
        total_size = 0
        for path in sorted(root.rglob("*")):
            if path.is_dir():
                continue
            if self._path_is_link(path) or not path.is_file():
                raise PluginError(f"Plugin tree contains an unsupported file: {path}")
            relative = path.relative_to(root).as_posix()
            size, digest = self._hash_bounded_file(path, MAX_PLUGIN_ASSET_BYTES)
            total_size += size
            if total_size > MAX_PLUGIN_PACKAGE_BYTES:
                raise PluginError("Plugin package exceeds size limit")
            inventory.append(
                {
                    "path": relative,
                    "sha256": digest,
                    "size": size,
                }
            )
        return inventory

    def _verify_tree_inventory(self, root: Path, files: list[dict[str, Any]]) -> None:
        self._assert_tree_has_no_links(root)
        actual_file_paths: list[str] = []
        for path in root.rglob("*"):
            if path.is_dir():
                continue
            if self._path_is_link(path) or not path.is_file():
                raise PluginError(f"Plugin tree contains an unsupported file: {path}")
            actual_file_paths.append(path.relative_to(root).as_posix().casefold())
        actual_paths = set(actual_file_paths)
        expected_paths = {item["path"].casefold() for item in files}
        if (
            len(actual_file_paths) != len(actual_paths)
            or actual_paths != expected_paths
        ):
            raise PluginError("Plugin file inventory does not match catalog")
        for item in files:
            path = self._resolve_plugin_file(root, item["path"])
            size, digest = self._hash_bounded_file(path, item["size"])
            if size != item["size"] or digest != item["sha256"]:
                raise PluginError(f"Plugin verification failed for {item['path']}")

    def _atomic_write_json(self, path: Path, payload: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def _new_staging_dir(self, plugin_id: str) -> Path:
        plugin_id = _validate_plugin_id(plugin_id)
        path = Path(
            tempfile.mkdtemp(prefix=f".{plugin_id}.staging-", dir=self.plugin_dir)
        )
        self._assert_plugin_child_path(path)
        return path

    def _remove_tree(self, path: Path) -> None:
        self._assert_plugin_child_path(path)
        if self._path_is_link(path):
            raise PluginError(f"Refusing to remove linked plugin path: {path}")
        shutil.rmtree(path)

    def _assert_tree_has_no_links(self, root: Path) -> None:
        if self._path_is_link(root):
            raise PluginError(
                f"Plugin path must not be a link or reparse point: {root}"
            )
        for path in root.rglob("*"):
            if self._path_is_link(path):
                raise PluginError(
                    f"Plugin path must not be a link or reparse point: {path}"
                )

    def _path_is_link(self, path: Path) -> bool:
        try:
            info = path.lstat()
        except OSError:
            return False
        if stat.S_ISLNK(info.st_mode):
            return True
        attributes = getattr(info, "st_file_attributes", 0)
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        return bool(attributes & reparse_flag)

    def _assert_plugin_child_path(self, path: Path) -> None:
        root_resolved = self.plugin_dir.resolve()
        resolved = path.resolve(strict=False)
        try:
            relative = resolved.relative_to(root_resolved)
        except ValueError as exc:
            raise PluginError(f"Plugin path escapes plugin directory: {path}") from exc
        if not relative.parts:
            raise PluginError(
                "Plugin operation cannot target the plugin directory itself"
            )

    def _normalize_relative_path(self, relative_path: str) -> str:
        if (
            not relative_path
            or "\\" in relative_path
            or "\x00" in relative_path
            or relative_path.startswith("/")
        ):
            raise PluginError(f"Invalid plugin path: {relative_path}")
        pure = PurePosixPath(relative_path)
        if str(pure) != relative_path or any(
            part in {"", ".", ".."} or ":" in part for part in pure.parts
        ):
            raise PluginError(f"Invalid plugin path: {relative_path}")
        return pure.as_posix()

    def _resolve_download_target(self, root: Path, relative_path: str) -> Path:
        normalized = self._normalize_relative_path(relative_path)
        root_resolved = root.resolve()
        path = root.joinpath(*PurePosixPath(normalized).parts).resolve(strict=False)
        try:
            path.relative_to(root_resolved)
        except ValueError as exc:
            raise PluginError(
                f"Plugin path escapes download root: {relative_path}"
            ) from exc
        return path

    def _read_plugin_file(self, root: Path, relative_path: str) -> str:
        path = self._resolve_plugin_file(root, relative_path)
        try:
            return self._read_bounded_file(path, MAX_PLUGIN_FILE_BYTES).decode("utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise PluginError(f"Unable to read plugin file: {relative_path}") from exc

    def _read_plugin_asset(
        self, root: Path, name: str, relative_path: str
    ) -> dict[str, Any]:
        path = self._resolve_plugin_file(root, relative_path)
        try:
            data = self._read_bounded_file(path, MAX_PLUGIN_ASSET_BYTES)
        except OSError as exc:
            raise PluginError(f"Unable to read plugin asset: {relative_path}") from exc
        mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        encoded = base64.b64encode(data).decode("ascii")
        return {
            "name": name,
            "path": relative_path,
            "mimeType": mime_type,
            "size": len(data),
            "dataUri": f"data:{mime_type};base64,{encoded}",
        }

    def _read_bounded_file(self, path: Path, max_bytes: int) -> bytes:
        declared_size = path.stat().st_size
        if declared_size < 0 or declared_size > max_bytes:
            raise PluginError(f"File exceeds size limit: {path}")
        with path.open("rb") as handle:
            data = handle.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise PluginError(f"File exceeds size limit: {path}")
        return data

    def _hash_bounded_file(self, path: Path, max_bytes: int) -> tuple[int, str]:
        try:
            declared_size = path.stat().st_size
        except OSError as exc:
            raise PluginError(f"Unable to inspect plugin file: {path}") from exc
        if declared_size < 0 or declared_size > max_bytes:
            raise PluginError(f"Plugin file exceeds size limit: {path}")
        digest = hashlib.sha256()
        size = 0
        try:
            with path.open("rb") as handle:
                while chunk := handle.read(64 * 1024):
                    size += len(chunk)
                    if size > max_bytes:
                        raise PluginError(f"Plugin file exceeds size limit: {path}")
                    digest.update(chunk)
        except OSError as exc:
            raise PluginError(f"Unable to read plugin file: {path}") from exc
        return size, digest.hexdigest()

    def _resolve_plugin_file(self, root: Path, relative_path: str) -> Path:
        normalized = self._normalize_relative_path(relative_path)
        if self._path_is_link(root):
            raise PluginError(f"Plugin root is a link or reparse point: {root}")
        root_resolved = root.resolve()
        current = root
        for part in PurePosixPath(normalized).parts:
            current = current / part
            if current.exists() and self._path_is_link(current):
                raise PluginError(
                    f"Plugin path is a link or reparse point: {relative_path}"
                )
        path = current.resolve(strict=False)
        try:
            path.relative_to(root_resolved)
        except ValueError as exc:
            raise PluginError(f"Plugin path escapes root: {relative_path}") from exc
        if not path.exists() or not path.is_file():
            raise PluginError(f"Plugin file missing: {relative_path}")
        return path


def _required_str(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PluginError(f"Field {key} must be a non-empty string")
    return value.strip()


def _normalize_assets(plugin_id: str, value: object) -> dict[str, str]:
    if value in (None, {}):
        return {}
    if isinstance(value, list):
        if not all(isinstance(item, str) and item.strip() for item in value):
            raise PluginError(
                f"Plugin {plugin_id} assets must be strings or a string map"
            )
        return {item.strip(): item.strip() for item in value}
    if isinstance(value, dict):
        assets: dict[str, str] = {}
        for name, path in value.items():
            if not isinstance(name, str) or not name.strip():
                raise PluginError(
                    f"Plugin {plugin_id} asset names must be non-empty strings"
                )
            if not isinstance(path, str) or not path.strip():
                raise PluginError(
                    f"Plugin {plugin_id} asset paths must be non-empty strings"
                )
            normalized_name = name.strip()
            if normalized_name in assets:
                raise PluginError(f"Plugin {plugin_id} asset names must not repeat")
            assets[normalized_name] = path.strip()
        return assets
    raise PluginError(f"Plugin {plugin_id} assets must be a string list or string map")


def _normalize_plugin_settings(
    plugin_id: str, value: object
) -> list[dict[str, Any]]:
    if value in (None, []):
        return []
    if not isinstance(value, list) or len(value) > MAX_PLUGIN_SETTINGS:
        raise PluginError(
            f"Plugin {plugin_id} settings must be a list with at most "
            f"{MAX_PLUGIN_SETTINGS} entries"
        )

    settings: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for raw in value:
        if not isinstance(raw, dict):
            raise PluginError(f"Plugin {plugin_id} settings must be objects")
        setting_id = raw.get("id")
        if not isinstance(setting_id, str) or not PLUGIN_SETTING_ID_RE.fullmatch(
            setting_id
        ):
            raise PluginError(f"Plugin {plugin_id} has an invalid setting id")
        if setting_id in seen_ids:
            raise PluginError(f"Plugin {plugin_id} setting ids must not repeat")
        seen_ids.add(setting_id)

        setting_type = raw.get("type")
        if setting_type not in PLUGIN_SETTING_TYPES:
            raise PluginError(
                f"Plugin {plugin_id} setting {setting_id} has an unsupported type"
            )
        label = _bounded_setting_text(plugin_id, setting_id, raw, "label", 80, True)
        description = _bounded_setting_text(
            plugin_id, setting_id, raw, "description", 240, False
        )
        normalized: dict[str, Any] = {
            "id": setting_id,
            "type": setting_type,
            "label": label,
            "description": description,
        }

        default = raw.get("default")
        if setting_type == "boolean":
            if not isinstance(default, bool):
                raise PluginError(
                    f"Plugin {plugin_id} setting {setting_id} requires a boolean default"
                )
        elif setting_type == "color":
            if not isinstance(default, str) or not PLUGIN_COLOR_RE.fullmatch(default):
                raise PluginError(
                    f"Plugin {plugin_id} setting {setting_id} requires a #RRGGBB default"
                )
            default = default.lower()
        elif setting_type == "range":
            minimum = _finite_setting_number(plugin_id, setting_id, raw.get("min"), "min")
            maximum = _finite_setting_number(plugin_id, setting_id, raw.get("max"), "max")
            step = _finite_setting_number(plugin_id, setting_id, raw.get("step"), "step")
            default = _finite_setting_number(plugin_id, setting_id, default, "default")
            if maximum <= minimum or step <= 0 or not minimum <= default <= maximum:
                raise PluginError(
                    f"Plugin {plugin_id} setting {setting_id} has invalid range bounds"
                )
            normalized.update({"min": minimum, "max": maximum, "step": step})
        elif setting_type == "image":
            if default != "":
                raise PluginError(
                    f"Plugin {plugin_id} setting {setting_id} image default must be empty"
                )
            accept = raw.get(
                "accept", ["image/png", "image/jpeg", "image/webp"]
            )
            if (
                not isinstance(accept, list)
                or not accept
                or not all(
                    isinstance(item, str)
                    and item in PLUGIN_SETTING_IMAGE_MIME_TYPES
                    for item in accept
                )
                or len(set(accept)) != len(accept)
            ):
                raise PluginError(
                    f"Plugin {plugin_id} setting {setting_id} has invalid image types"
                )
            max_bytes = raw.get("maxBytes", 1024 * 1024)
            if (
                isinstance(max_bytes, bool)
                or not isinstance(max_bytes, int)
                or not 1024 <= max_bytes <= MAX_PLUGIN_SETTING_IMAGE_BYTES
            ):
                raise PluginError(
                    f"Plugin {plugin_id} setting {setting_id} has invalid maxBytes"
                )
            normalized.update({"accept": list(accept), "maxBytes": max_bytes})
        elif setting_type == "select":
            options = raw.get("options")
            if (
                not isinstance(options, list)
                or not options
                or len(options) > MAX_PLUGIN_SETTING_OPTIONS
            ):
                raise PluginError(
                    f"Plugin {plugin_id} setting {setting_id} requires select options"
                )
            normalized_options: list[dict[str, str]] = []
            option_values: set[str] = set()
            for option in options:
                if not isinstance(option, dict):
                    raise PluginError(
                        f"Plugin {plugin_id} setting {setting_id} options must be objects"
                    )
                option_value = _bounded_setting_text(
                    plugin_id, setting_id, option, "value", 128, True
                )
                option_label = _bounded_setting_text(
                    plugin_id, setting_id, option, "label", 80, True
                )
                if option_value in option_values:
                    raise PluginError(
                        f"Plugin {plugin_id} setting {setting_id} option values must not repeat"
                    )
                option_values.add(option_value)
                normalized_options.append(
                    {"value": option_value, "label": option_label}
                )
            if not isinstance(default, str) or default not in option_values:
                raise PluginError(
                    f"Plugin {plugin_id} setting {setting_id} default must match an option"
                )
            normalized["options"] = normalized_options
        else:
            max_length = raw.get("maxLength", 256)
            if (
                isinstance(max_length, bool)
                or not isinstance(max_length, int)
                or not 1 <= max_length <= 1024
            ):
                raise PluginError(
                    f"Plugin {plugin_id} setting {setting_id} has an invalid maxLength"
                )
            if not isinstance(default, str) or len(default) > max_length:
                raise PluginError(
                    f"Plugin {plugin_id} setting {setting_id} has an invalid text default"
                )
            normalized["maxLength"] = max_length
            normalized["placeholder"] = _bounded_setting_text(
                plugin_id, setting_id, raw, "placeholder", 120, False
            )

        normalized["default"] = default
        settings.append(normalized)
    return settings


def _bounded_setting_text(
    plugin_id: str,
    setting_id: str,
    data: dict[str, Any],
    key: str,
    limit: int,
    required: bool,
) -> str:
    value = data.get(key, "")
    if not isinstance(value, str):
        raise PluginError(
            f"Plugin {plugin_id} setting {setting_id} field {key} must be a string"
        )
    value = value.strip()
    if (required and not value) or len(value) > limit:
        raise PluginError(
            f"Plugin {plugin_id} setting {setting_id} field {key} is invalid"
        )
    return value


def _finite_setting_number(
    plugin_id: str, setting_id: str, value: object, field: str
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PluginError(
            f"Plugin {plugin_id} setting {setting_id} field {field} must be numeric"
        )
    number = float(value)
    if not math.isfinite(number) or abs(number) > 1_000_000:
        raise PluginError(
            f"Plugin {plugin_id} setting {setting_id} field {field} is out of range"
        )
    return number


def _json_copy(value: Any) -> Any:
    return json.loads(json.dumps(value))


def _now() -> float:
    import time

    return time.time()


def compare_versions(left: str, right: str) -> int:
    left_parts = _version_key(left)
    right_parts = _version_key(right)
    max_length = max(len(left_parts), len(right_parts))
    left_parts.extend([0] * (max_length - len(left_parts)))
    right_parts.extend([0] * (max_length - len(right_parts)))
    if left_parts > right_parts:
        return 1
    if left_parts < right_parts:
        return -1
    return 0


def _version_key(version: str) -> list[int]:
    numbers = re.findall(r"\d+", version)
    if not numbers:
        return [0]
    return [int(number) for number in numbers]
