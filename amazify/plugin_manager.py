from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen


PLUGIN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,127}$")
DEFAULT_CATALOG_URL = (
    "https://raw.githubusercontent.com/eripum9/Amazify/main/plugin_catalog.json"
)
CATALOG_CACHE_SECONDS = 60
MAX_PLUGIN_FILE_BYTES = 2 * 1024 * 1024
MAX_PLUGIN_ASSET_BYTES = 5 * 1024 * 1024
PLUGIN_TYPES = {"theme", "ui"}
PERMISSIONS = {
    "dom-style",
    "dom-read",
    "dom-write",
    "bridge-state",
    "bridge-command",
    "network",
}


class PluginError(ValueError):
    pass


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
    amazon_music: dict[str, Any]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PluginManifest":
        plugin_id = _required_str(data, "id")
        if not PLUGIN_ID_RE.match(plugin_id):
            raise PluginError(f"Invalid plugin id: {plugin_id}")

        plugin_type = _required_str(data, "type")
        if plugin_type not in PLUGIN_TYPES:
            raise PluginError(f"Plugin {plugin_id} has unsupported type: {plugin_type}")

        permissions = data.get("permissions", [])
        if not isinstance(permissions, list) or not all(
            isinstance(item, str) for item in permissions
        ):
            raise PluginError(f"Plugin {plugin_id} permissions must be a string list")

        unknown_permissions = sorted(set(permissions) - PERMISSIONS)
        if unknown_permissions:
            raise PluginError(
                f"Plugin {plugin_id} uses unknown permissions: {unknown_permissions}"
            )

        styles = data.get("styles", [])
        if not isinstance(styles, list) or not all(isinstance(item, str) for item in styles):
            raise PluginError(f"Plugin {plugin_id} styles must be a string list")

        entry = data.get("entry")
        if entry is not None and not isinstance(entry, str):
            raise PluginError(f"Plugin {plugin_id} entry must be a string")

        assets = _normalize_assets(plugin_id, data.get("assets", {}))

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
            entry=entry,
            styles=styles,
            assets=assets,
            permissions=permissions,
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
            "styles": self.styles,
            "assets": self.assets,
            "permissions": self.permissions,
            "amazonMusic": self.amazon_music,
        }


@dataclass(slots=True)
class PluginPackage:
    root: Path
    manifest: PluginManifest
    enabled: bool

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "manifest": self.manifest.to_public_dict(),
            "enabled": self.enabled,
            "rootName": self.root.name,
        }


class PluginManager:
    def __init__(
        self,
        plugin_dir: Path,
        state_file: Path,
        *,
        catalog_url: str | None = None,
    ) -> None:
        self.plugin_dir = plugin_dir
        self.state_file = state_file
        self.catalog_url = (
            catalog_url
            or os.environ.get("AMAZIFY_PLUGIN_CATALOG_URL")
            or DEFAULT_CATALOG_URL
        )
        self.plugin_dir.mkdir(parents=True, exist_ok=True)
        self._state = self._load_state()
        self._catalog_cache: tuple[float, list[dict[str, Any]]] | None = None

    def _load_state(self) -> dict[str, Any]:
        if not self.state_file.exists():
            return {"enabled": {}}
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"enabled": {}}
        if not isinstance(data, dict):
            return {"enabled": {}}
        enabled = data.get("enabled")
        if not isinstance(enabled, dict):
            data["enabled"] = {}
        return data

    def _save_state(self) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(
            json.dumps(self._state, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def ensure_sample_plugins(self, source_dir: Path) -> list[str]:
        copied: list[str] = []
        if not source_dir.exists():
            return copied
        for sample in source_dir.iterdir():
            if not sample.is_dir():
                continue
            manifest = sample / "manifest.json"
            if not manifest.exists():
                continue
            target = self.plugin_dir / sample.name
            if target.exists():
                continue
            shutil.copytree(sample, target)
            copied.append(sample.name)
        return copied

    def catalog_plugins(self, *, force_refresh: bool = False) -> list[dict[str, Any]]:
        if not force_refresh and self._catalog_cache is not None:
            cached_at, cached_plugins = self._catalog_cache
            if _now() - cached_at < CATALOG_CACHE_SECONDS:
                return self._annotate_catalog_plugins(cached_plugins)

        data = self._read_json_url(self.catalog_url)
        plugins = data.get("plugins")
        if not isinstance(plugins, list):
            raise PluginError("Plugin catalog must contain a plugins list")

        normalized = [self._normalize_catalog_plugin(item) for item in plugins]
        self._catalog_cache = (_now(), normalized)
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

    def install_from_catalog(self, plugin_id: str) -> PluginPackage:
        plugin_id = plugin_id.strip()
        if not PLUGIN_ID_RE.match(plugin_id):
            raise PluginError(f"Invalid plugin id: {plugin_id}")

        catalog_plugins = self.catalog_plugins(force_refresh=True)
        catalog_item = next(
            (item for item in catalog_plugins if item.get("id") == plugin_id),
            None,
        )
        if not catalog_item:
            raise PluginError(f"Plugin not found in catalog: {plugin_id}")

        files = catalog_item.get("files")
        if not isinstance(files, list) or not files:
            raise PluginError(f"Catalog plugin {plugin_id} has no downloadable files")
        manifest_data = catalog_item.get("manifest")
        asset_paths = set()
        if isinstance(manifest_data, dict) and isinstance(manifest_data.get("assets"), dict):
            asset_paths = {
                path
                for path in manifest_data["assets"].values()
                if isinstance(path, str) and path
            }

        tmp_root = self.plugin_dir / f".{plugin_id}.download"
        target = self.plugin_dir / plugin_id
        self._assert_plugin_child_path(tmp_root)
        self._assert_plugin_child_path(target)
        if tmp_root.exists():
            shutil.rmtree(tmp_root)
        tmp_root.mkdir(parents=True)

        try:
            seen_paths: set[str] = set()
            for file_item in files:
                if not isinstance(file_item, dict):
                    raise PluginError(f"Catalog plugin {plugin_id} has an invalid file entry")
                relative_path = str(file_item.get("path", "")).strip()
                url = str(file_item.get("url", "")).strip()
                if not relative_path or not url:
                    raise PluginError(f"Catalog plugin {plugin_id} file entries need path and url")
                if relative_path in seen_paths:
                    raise PluginError(f"Catalog plugin {plugin_id} repeats file: {relative_path}")
                seen_paths.add(relative_path)

                destination = self._resolve_download_target(tmp_root, relative_path)
                destination.parent.mkdir(parents=True, exist_ok=True)
                max_bytes = (
                    MAX_PLUGIN_ASSET_BYTES
                    if relative_path in asset_paths
                    else MAX_PLUGIN_FILE_BYTES
                )
                destination.write_bytes(
                    self._read_url_bytes(url, max_bytes=max_bytes)
                )

            manifest_path = tmp_root / "manifest.json"
            if not manifest_path.exists():
                raise PluginError(f"Catalog plugin {plugin_id} did not download manifest.json")
            manifest = self.load_manifest(manifest_path)
            if manifest.id != plugin_id:
                raise PluginError(
                    f"Catalog plugin id mismatch: requested {plugin_id}, downloaded {manifest.id}"
                )

            if target.exists():
                shutil.rmtree(target)
            tmp_root.rename(target)
            return PluginPackage(
                root=target,
                manifest=manifest,
                enabled=bool(self._state["enabled"].get(manifest.id, False)),
            )
        except Exception:
            if tmp_root.exists():
                shutil.rmtree(tmp_root)
            raise

    def list_plugins(self) -> list[PluginPackage]:
        packages: list[PluginPackage] = []
        for child in sorted(self.plugin_dir.iterdir(), key=lambda item: item.name.lower()):
            if not child.is_dir():
                continue
            manifest_path = child / "manifest.json"
            if not manifest_path.exists():
                continue
            try:
                manifest = self.load_manifest(manifest_path)
            except PluginError:
                continue
            packages.append(
                PluginPackage(
                    root=child,
                    manifest=manifest,
                    enabled=bool(self._state["enabled"].get(manifest.id, False)),
                )
            )
        return packages

    def load_manifest(self, manifest_path: Path) -> PluginManifest:
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
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
        for package in self.list_plugins():
            if package.manifest.id == plugin_id:
                return package
        raise PluginError(f"Plugin not found: {plugin_id}")

    def enable(self, plugin_id: str) -> PluginPackage:
        package = self.get(plugin_id)
        self._state["enabled"][package.manifest.id] = True
        self._save_state()
        return PluginPackage(package.root, package.manifest, True)

    def disable(self, plugin_id: str) -> PluginPackage:
        package = self.get(plugin_id)
        self._state["enabled"][package.manifest.id] = False
        self._save_state()
        return PluginPackage(package.root, package.manifest, False)

    def disable_all(self) -> None:
        for package in self.list_plugins():
            self._state["enabled"][package.manifest.id] = False
        self._save_state()

    def public_plugins(self) -> list[dict[str, Any]]:
        return [package.to_public_dict() for package in self.list_plugins()]

    def runtime_snapshot(self) -> list[dict[str, Any]]:
        snapshot: list[dict[str, Any]] = []
        for package in self.list_plugins():
            manifest = package.manifest
            source: dict[str, Any] = {"entry": "", "styles": [], "assets": []}
            if manifest.entry:
                source["entry"] = self._read_plugin_file(package.root, manifest.entry)
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
                    "source": source,
                }
            )
        return snapshot

    def _normalize_catalog_plugin(self, item: object) -> dict[str, Any]:
        if not isinstance(item, dict):
            raise PluginError("Plugin catalog entries must be objects")
        manifest_data = item.get("manifest")
        if not isinstance(manifest_data, dict):
            raise PluginError("Plugin catalog entries must include a manifest object")
        manifest = PluginManifest.from_dict(manifest_data)

        files = item.get("files")
        if not isinstance(files, list) or not files:
            raise PluginError(f"Catalog plugin {manifest.id} must include files")
        normalized_files: list[dict[str, str]] = []
        for file_item in files:
            if not isinstance(file_item, dict):
                raise PluginError(f"Catalog plugin {manifest.id} has an invalid file entry")
            path = str(file_item.get("path", "")).strip()
            url = str(file_item.get("url", "")).strip()
            if not path or not url:
                raise PluginError(f"Catalog plugin {manifest.id} file entries need path and url")
            self._validate_relative_path(path)
            normalized_files.append({"path": path, "url": url})

        manifest_paths = ["manifest.json"]
        if manifest.entry:
            manifest_paths.append(manifest.entry)
        manifest_paths.extend(manifest.styles)
        manifest_paths.extend(manifest.assets.values())
        for manifest_path in manifest_paths:
            self._validate_relative_path(manifest_path)
        missing = sorted(set(manifest_paths) - {file_item["path"] for file_item in normalized_files})
        if missing:
            raise PluginError(f"Catalog plugin {manifest.id} missing files: {missing}")

        return {
            "id": manifest.id,
            "channel": str(item.get("channel", "community")),
            "sourceUrl": str(item.get("sourceUrl", "")),
            "manifest": manifest.to_public_dict(),
            "files": normalized_files,
        }

    def _annotate_catalog_plugins(self, plugins: list[dict[str, Any]]) -> list[dict[str, Any]]:
        installed = {
            package.manifest.id: package
            for package in self.list_plugins()
        }
        annotated: list[dict[str, Any]] = []
        for plugin in plugins:
            package = installed.get(str(plugin.get("id", "")))
            item = dict(plugin)
            item["installed"] = package is not None
            item["enabled"] = bool(package.enabled) if package else False
            item["installedVersion"] = package.manifest.version if package else ""
            item["latestVersion"] = item["manifest"]["version"]
            item["updateAvailable"] = (
                package is not None
                and compare_versions(
                    item["manifest"]["version"],
                    package.manifest.version,
                )
                > 0
            )
            annotated.append(item)
        return annotated

    def _read_json_url(self, url: str) -> dict[str, Any]:
        try:
            data = json.loads(self._read_text_url(url))
        except json.JSONDecodeError as exc:
            raise PluginError(f"Invalid plugin catalog JSON: {url}") from exc
        if not isinstance(data, dict):
            raise PluginError(f"Plugin catalog must be a JSON object: {url}")
        return data

    def _read_text_url(self, url: str) -> str:
        return self._read_url_bytes(url, max_bytes=MAX_PLUGIN_FILE_BYTES).decode("utf-8")

    def _read_url_bytes(self, url: str, *, max_bytes: int) -> bytes:
        request = Request(url, headers={"User-Agent": "Amazify/0.1"})
        try:
            with urlopen(request, timeout=15) as response:
                raw = response.read(max_bytes + 1)
        except (OSError, URLError) as exc:
            raise PluginError(f"Unable to download plugin file: {url}") from exc
        if len(raw) > max_bytes:
            raise PluginError(f"Downloaded plugin file is too large: {url}")
        return raw

    def _assert_plugin_child_path(self, path: Path) -> None:
        root_resolved = self.plugin_dir.resolve()
        resolved = path.resolve()
        try:
            resolved.relative_to(root_resolved)
        except ValueError as exc:
            raise PluginError(f"Plugin path escapes plugin directory: {path}") from exc

    def _validate_relative_path(self, relative_path: str) -> None:
        if not relative_path or Path(relative_path).is_absolute():
            raise PluginError(f"Invalid plugin path: {relative_path}")
        parts = Path(relative_path).parts
        if any(part in {"", ".", ".."} for part in parts):
            raise PluginError(f"Invalid plugin path: {relative_path}")

    def _resolve_download_target(self, root: Path, relative_path: str) -> Path:
        self._validate_relative_path(relative_path)
        root_resolved = root.resolve()
        path = (root / relative_path).resolve()
        try:
            path.relative_to(root_resolved)
        except ValueError as exc:
            raise PluginError(f"Plugin path escapes download root: {relative_path}") from exc
        return path

    def _read_plugin_file(self, root: Path, relative_path: str) -> str:
        path = self._resolve_plugin_file(root, relative_path)
        return path.read_text(encoding="utf-8")

    def _read_plugin_asset(self, root: Path, name: str, relative_path: str) -> dict[str, Any]:
        path = self._resolve_plugin_file(root, relative_path)
        data = path.read_bytes()
        if len(data) > MAX_PLUGIN_ASSET_BYTES:
            raise PluginError(f"Plugin asset is too large: {relative_path}")
        mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        encoded = base64.b64encode(data).decode("ascii")
        return {
            "name": name,
            "path": relative_path,
            "mimeType": mime_type,
            "size": len(data),
            "dataUri": f"data:{mime_type};base64,{encoded}",
        }

    def _resolve_plugin_file(self, root: Path, relative_path: str) -> Path:
        if not relative_path or Path(relative_path).is_absolute():
            raise PluginError(f"Invalid plugin path: {relative_path}")
        root_resolved = root.resolve()
        path = (root / relative_path).resolve()
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
        raise PluginError(f"Manifest field {key} must be a non-empty string")
    return value.strip()


def _normalize_assets(plugin_id: str, value: object) -> dict[str, str]:
    if value in (None, {}):
        return {}
    if isinstance(value, list):
        if not all(isinstance(item, str) for item in value):
            raise PluginError(f"Plugin {plugin_id} assets must be strings or a string map")
        return {item: item for item in value}
    if isinstance(value, dict):
        assets: dict[str, str] = {}
        for name, path in value.items():
            if not isinstance(name, str) or not name.strip():
                raise PluginError(f"Plugin {plugin_id} asset names must be non-empty strings")
            if not isinstance(path, str) or not path.strip():
                raise PluginError(f"Plugin {plugin_id} asset paths must be non-empty strings")
            assets[name.strip()] = path.strip()
        return assets
    raise PluginError(f"Plugin {plugin_id} assets must be a string list or string map")


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
