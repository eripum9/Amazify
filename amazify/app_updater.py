from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import subprocess
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO

from . import __version__


RELEASE_API_URL = "https://api.github.com/repos/eripum9/Amazify/releases/latest"
REPOSITORY_RELEASE_ROOT = "https://github.com/eripum9/Amazify/releases"
INSTALLER_ASSET_NAME = "AmazifySetup.exe"
MAX_RELEASE_METADATA_BYTES = 256 * 1024
MAX_INSTALLER_BYTES = 256 * 1024 * 1024
MAX_RELEASE_ASSETS = 64
MAX_DOWNLOAD_REDIRECTS = 3
NETWORK_TIMEOUT_SECONDS = 20
DOWNLOAD_CHUNK_BYTES = 128 * 1024
GITHUB_API_VERSION = "2022-11-28"
SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
TAG_RE = re.compile(r"^v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
SHA256_DIGEST_RE = re.compile(r"^sha256:([0-9a-fA-F]{64})$")
REDIRECT_STATUS_CODES = frozenset({301, 302, 303, 307, 308})
RELEASE_ASSET_HOSTS = frozenset(
    {
        "release-assets.githubusercontent.com",
        "objects.githubusercontent.com",
        "github-releases.githubusercontent.com",
    }
)


class UpdateError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ReleaseInfo:
    version: str
    tag_name: str
    release_url: str
    published_at: str
    installer_url: str
    installer_sha256: str
    installer_size: int


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: BinaryIO,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        return None


def parse_version(value: str) -> tuple[int, int, int]:
    match = SEMVER_RE.fullmatch(str(value or "").strip())
    if not match:
        raise UpdateError("Amazify versions must use major.minor.patch")
    major, minor, patch = match.groups()
    return int(major), int(minor), int(patch)


def update_available(current_version: str, latest_version: str) -> bool:
    return parse_version(latest_version) > parse_version(current_version)


def fetch_latest_release() -> ReleaseInfo:
    request = urllib.request.Request(
        RELEASE_API_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "Accept-Encoding": "identity",
            "User-Agent": f"Amazify/{__version__}",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
        },
        method="GET",
    )
    opener = urllib.request.build_opener(_NoRedirectHandler())
    try:
        response = opener.open(request, timeout=NETWORK_TIMEOUT_SECONDS)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise UpdateError("No published Amazify release is available") from exc
        if exc.code in REDIRECT_STATUS_CODES:
            raise UpdateError("GitHub release metadata redirected unexpectedly") from exc
        raise UpdateError(f"GitHub release check failed with HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise UpdateError("Unable to contact GitHub for Amazify updates") from exc

    with response:
        status = int(getattr(response, "status", response.getcode()))
        if status != 200:
            raise UpdateError(f"GitHub release check failed with HTTP {status}")
        if response.geturl() != RELEASE_API_URL:
            raise UpdateError("GitHub release metadata came from an unexpected URL")
        content_type = str(response.headers.get("Content-Type") or "").lower()
        if "json" not in content_type:
            raise UpdateError("GitHub release metadata was not JSON")
        raw = _read_bounded_response(response, MAX_RELEASE_METADATA_BYTES)

    document = _strict_json_object(raw)
    return parse_release_document(document)


def parse_release_document(document: dict[str, Any]) -> ReleaseInfo:
    if document.get("draft") is not False or document.get("prerelease") is not False:
        raise UpdateError("Only final published Amazify releases can be installed")

    tag_name = _required_string(document, "tag_name")
    tag_match = TAG_RE.fullmatch(tag_name)
    if not tag_match:
        raise UpdateError("The release tag must use vmajor.minor.patch")
    version = ".".join(tag_match.groups())
    parse_version(version)

    expected_release_url = f"{REPOSITORY_RELEASE_ROOT}/tag/{tag_name}"
    release_url = _required_string(document, "html_url")
    if release_url != expected_release_url:
        raise UpdateError("The release page did not match the official Amazify repository")

    assets = document.get("assets")
    if not isinstance(assets, list) or len(assets) > MAX_RELEASE_ASSETS:
        raise UpdateError("The release asset list is invalid")
    matching_assets = [
        asset
        for asset in assets
        if isinstance(asset, dict) and asset.get("name") == INSTALLER_ASSET_NAME
    ]
    if len(matching_assets) != 1:
        raise UpdateError("The release must contain exactly one AmazifySetup.exe asset")
    asset = matching_assets[0]
    if asset.get("state") != "uploaded":
        raise UpdateError("The Amazify installer asset is not ready")

    installer_size = asset.get("size")
    if (
        isinstance(installer_size, bool)
        or not isinstance(installer_size, int)
        or installer_size <= 0
        or installer_size > MAX_INSTALLER_BYTES
    ):
        raise UpdateError("The Amazify installer size is invalid")

    digest_match = SHA256_DIGEST_RE.fullmatch(str(asset.get("digest") or ""))
    if not digest_match:
        raise UpdateError("The release installer is missing its GitHub SHA-256 digest")
    installer_sha256 = digest_match.group(1).lower()

    expected_installer_url = (
        f"{REPOSITORY_RELEASE_ROOT}/download/{tag_name}/{INSTALLER_ASSET_NAME}"
    )
    installer_url = _required_string(asset, "browser_download_url")
    if installer_url != expected_installer_url:
        raise UpdateError("The installer URL did not match the official Amazify release")

    return ReleaseInfo(
        version=version,
        tag_name=tag_name,
        release_url=release_url,
        published_at=str(document.get("published_at") or ""),
        installer_url=installer_url,
        installer_sha256=installer_sha256,
        installer_size=installer_size,
    )


def download_installer(
    release: ReleaseInfo,
    update_dir: Path,
    progress: Callable[[int, int], None] | None = None,
) -> Path:
    parse_version(release.version)
    _validate_installer_url(release.installer_url, release, allow_asset_host=False)
    update_dir.mkdir(parents=True, exist_ok=True)
    _reject_reparse_point(update_dir)

    destination = update_dir / (
        f"AmazifySetup-v{release.version}-{release.installer_sha256[:12]}.exe"
    )
    if destination.exists():
        try:
            verify_installer(destination, release)
            if progress:
                progress(release.installer_size, release.installer_size)
            return destination
        except UpdateError:
            destination.unlink(missing_ok=True)

    temporary = update_dir / f".{destination.name}.{secrets.token_hex(12)}.part"
    response = _open_installer_response(release)
    try:
        with response:
            _validate_download_headers(response, release.installer_size)
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            descriptor = os.open(temporary, flags, 0o600)
            digest = hashlib.sha256()
            total = 0
            first_bytes = b""
            try:
                with os.fdopen(descriptor, "wb") as output:
                    while True:
                        chunk = response.read(DOWNLOAD_CHUNK_BYTES)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > release.installer_size or total > MAX_INSTALLER_BYTES:
                            raise UpdateError("The installer download exceeded its declared size")
                        if len(first_bytes) < 2:
                            first_bytes += chunk[: 2 - len(first_bytes)]
                        digest.update(chunk)
                        output.write(chunk)
                        if progress:
                            progress(total, release.installer_size)
                    output.flush()
                    os.fsync(output.fileno())
            except Exception:
                temporary.unlink(missing_ok=True)
                raise

            if total != release.installer_size:
                raise UpdateError("The installer download size did not match the release")
            if first_bytes != b"MZ":
                raise UpdateError("The downloaded installer is not a Windows executable")
            if not secrets.compare_digest(digest.hexdigest(), release.installer_sha256):
                raise UpdateError("The installer SHA-256 verification failed")
            os.replace(temporary, destination)
            verify_installer(destination, release)
            return destination
    except UpdateError:
        temporary.unlink(missing_ok=True)
        raise
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        temporary.unlink(missing_ok=True)
        raise UpdateError("The Amazify installer download failed") from exc
    finally:
        temporary.unlink(missing_ok=True)


def verify_installer(path: Path, release: ReleaseInfo) -> None:
    try:
        _reject_reparse_point(path)
        stat = path.stat()
    except OSError as exc:
        raise UpdateError("The staged installer is unavailable") from exc
    if not path.is_file() or stat.st_size != release.installer_size:
        raise UpdateError("The staged installer size is invalid")

    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            if handle.read(2) != b"MZ":
                raise UpdateError("The staged installer is not a Windows executable")
            handle.seek(0)
            for chunk in iter(lambda: handle.read(DOWNLOAD_CHUNK_BYTES), b""):
                digest.update(chunk)
    except OSError as exc:
        raise UpdateError("The staged installer could not be verified") from exc
    if not secrets.compare_digest(digest.hexdigest(), release.installer_sha256):
        raise UpdateError("The staged installer SHA-256 verification failed")


def launch_installer(path: Path, release: ReleaseInfo) -> None:
    if os.name != "nt":
        raise UpdateError("Amazify application updates are supported only on Windows")
    verify_installer(path, release)
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    try:
        subprocess.Popen(
            [
                str(path),
                "/SP-",
                "/NORESTART",
                "/CLOSEAPPLICATIONS",
                "/RESTARTAPPLICATIONS",
            ],
            cwd=str(path.parent),
            close_fds=True,
            creationflags=creationflags,
        )
    except OSError as exc:
        raise UpdateError("The verified Amazify installer could not be launched") from exc


class ApplicationUpdater:
    def __init__(
        self,
        update_dir: Path,
        *,
        current_version: str = __version__,
        release_fetcher: Callable[[], ReleaseInfo] = fetch_latest_release,
        installer_downloader: Callable[
            [ReleaseInfo, Path, Callable[[int, int], None] | None], Path
        ] = download_installer,
        installer_launcher: Callable[[Path, ReleaseInfo], None] = launch_installer,
    ) -> None:
        parse_version(current_version)
        self.update_dir = update_dir
        self.current_version = current_version
        self._release_fetcher = release_fetcher
        self._installer_downloader = installer_downloader
        self._installer_launcher = installer_launcher
        self._lock = threading.RLock()
        self._release: ReleaseInfo | None = None
        self._worker: threading.Thread | None = None
        self._state: dict[str, Any] = {
            "currentVersion": current_version,
            "latestVersion": "",
            "status": "idle",
            "updateAvailable": False,
            "progress": 0,
            "downloadedBytes": 0,
            "totalBytes": 0,
            "releaseUrl": "",
            "publishedAt": "",
            "error": "",
        }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._state)

    def check_now(self) -> dict[str, Any]:
        self._set_state(status="checking", error="", progress=0)
        try:
            release = self._release_fetcher()
            available = update_available(self.current_version, release.version)
            with self._lock:
                self._release = release
                self._state.update(
                    {
                        "latestVersion": release.version,
                        "status": "available" if available else "up-to-date",
                        "updateAvailable": available,
                        "progress": 0,
                        "downloadedBytes": 0,
                        "totalBytes": release.installer_size,
                        "releaseUrl": release.release_url,
                        "publishedAt": release.published_at,
                        "error": "",
                    }
                )
            return self.snapshot()
        except UpdateError as exc:
            self._record_check_failure(str(exc))
            raise
        except Exception as exc:
            message = "The Amazify update check failed"
            self._record_check_failure(message)
            raise UpdateError(message) from exc

    def start_check(self) -> dict[str, Any]:
        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                return dict(self._state)
            self._state.update({"status": "checking", "error": "", "progress": 0})
            self._worker = threading.Thread(
                target=self._check_worker,
                name="amazify-update-check",
                daemon=True,
            )
            self._worker.start()
            return dict(self._state)

    def start_install(self) -> dict[str, Any]:
        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                raise UpdateError("An Amazify update operation is already running")
            release = self._release
            if release is None or not update_available(
                self.current_version, release.version
            ):
                raise UpdateError("Check for an available Amazify update first")
            self._state.update(
                {
                    "status": "downloading",
                    "error": "",
                    "progress": 0,
                    "downloadedBytes": 0,
                    "totalBytes": release.installer_size,
                }
            )
            self._worker = threading.Thread(
                target=self._install_worker,
                args=(release,),
                name="amazify-update-install",
                daemon=True,
            )
            self._worker.start()
            return dict(self._state)

    def install_now(self, release: ReleaseInfo | None = None) -> Path:
        selected = release
        if selected is None:
            with self._lock:
                selected = self._release
        if selected is None:
            self.check_now()
            with self._lock:
                selected = self._release
        if selected is None or not update_available(
            self.current_version, selected.version
        ):
            raise UpdateError("Amazify is already up to date")
        self._set_state(
            status="downloading",
            error="",
            progress=0,
            downloadedBytes=0,
            totalBytes=selected.installer_size,
        )
        try:
            installer = self._installer_downloader(
                selected, self.update_dir, self._record_progress
            )
            self._set_state(status="launching", progress=100)
            self._installer_launcher(installer, selected)
            self._set_state(status="launched", progress=100)
            return installer
        except UpdateError as exc:
            self._set_state(status="error", error=str(exc))
            raise
        except Exception as exc:
            self._set_state(status="error", error="The Amazify update failed")
            raise UpdateError("The Amazify update failed") from exc

    def _check_worker(self) -> None:
        try:
            self.check_now()
        except UpdateError:
            return

    def _install_worker(self, release: ReleaseInfo) -> None:
        try:
            self.install_now(release)
        except UpdateError:
            return

    def _record_progress(self, downloaded: int, total: int) -> None:
        percentage = min(100, max(0, int(downloaded * 100 / total))) if total else 0
        self._set_state(
            status="downloading",
            downloadedBytes=downloaded,
            totalBytes=total,
            progress=percentage,
        )

    def _record_check_failure(self, message: str) -> None:
        with self._lock:
            self._release = None
            self._state.update(
                {
                    "latestVersion": "",
                    "status": "error",
                    "updateAvailable": False,
                    "progress": 0,
                    "downloadedBytes": 0,
                    "totalBytes": 0,
                    "releaseUrl": "",
                    "publishedAt": "",
                    "error": message,
                }
            )

    def _set_state(self, **changes: Any) -> None:
        with self._lock:
            self._state.update(changes)


def _open_installer_response(release: ReleaseInfo) -> Any:
    opener = urllib.request.build_opener(_NoRedirectHandler())
    current_url = release.installer_url
    for redirect_count in range(MAX_DOWNLOAD_REDIRECTS + 1):
        _validate_installer_url(
            current_url,
            release,
            allow_asset_host=redirect_count > 0,
        )
        request = urllib.request.Request(
            current_url,
            headers={
                "Accept": "application/octet-stream",
                "Accept-Encoding": "identity",
                "User-Agent": f"Amazify/{__version__}",
            },
            method="GET",
        )
        try:
            response = opener.open(request, timeout=NETWORK_TIMEOUT_SECONDS)
        except urllib.error.HTTPError as exc:
            if exc.code not in REDIRECT_STATUS_CODES:
                raise UpdateError(
                    f"The installer download failed with HTTP {exc.code}"
                ) from exc
            if redirect_count >= MAX_DOWNLOAD_REDIRECTS:
                raise UpdateError("The installer download redirected too many times") from exc
            locations = exc.headers.get_all("Location") or []
            if len(locations) != 1:
                raise UpdateError("The installer redirect was invalid") from exc
            next_url = urllib.parse.urljoin(current_url, str(locations[0]))
            _validate_installer_url(next_url, release, allow_asset_host=True)
            current_url = next_url
            continue
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise UpdateError("Unable to download the Amazify installer") from exc

        status = int(getattr(response, "status", response.getcode()))
        if status != 200:
            response.close()
            raise UpdateError(f"The installer download failed with HTTP {status}")
        if response.geturl() != current_url:
            response.close()
            raise UpdateError("The installer download redirected outside validation")
        return response
    raise UpdateError("The installer download redirected too many times")


def _validate_installer_url(
    value: str,
    release: ReleaseInfo,
    *,
    allow_asset_host: bool,
) -> None:
    if not value or value.strip() != value or any(ord(char) < 32 for char in value):
        raise UpdateError("The installer URL is invalid")
    parsed = urllib.parse.urlsplit(value)
    try:
        port = parsed.port
    except ValueError as exc:
        raise UpdateError("The installer URL port is invalid") from exc
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme.lower() != "https"
        or port not in (None, 443)
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise UpdateError("The installer URL is not an approved HTTPS URL")
    if host == "github.com":
        if value != release.installer_url:
            raise UpdateError("The GitHub installer URL did not match the release")
        return
    if not allow_asset_host or host not in RELEASE_ASSET_HOSTS or not parsed.path:
        raise UpdateError("The installer redirect host is not approved")


def _validate_download_headers(response: Any, expected_size: int) -> None:
    encodings = response.headers.get_all("Content-Encoding") or []
    if len(encodings) > 1 or (
        encodings and str(encodings[0]).strip().lower() not in {"", "identity"}
    ):
        raise UpdateError("The installer response used an unexpected encoding")
    lengths = response.headers.get_all("Content-Length") or []
    if len(lengths) > 1:
        raise UpdateError("The installer response had conflicting sizes")
    if lengths:
        try:
            declared = int(str(lengths[0]))
        except ValueError as exc:
            raise UpdateError("The installer response size was invalid") from exc
        if declared != expected_size:
            raise UpdateError("The installer response size did not match the release")


def _read_bounded_response(response: Any, limit: int) -> bytes:
    lengths = response.headers.get_all("Content-Length") or []
    if len(lengths) > 1:
        raise UpdateError("The release response had conflicting sizes")
    if lengths:
        try:
            declared = int(str(lengths[0]))
        except ValueError as exc:
            raise UpdateError("The release response size was invalid") from exc
        if declared < 0 or declared > limit:
            raise UpdateError("The release response was too large")
    raw = response.read(limit + 1)
    if len(raw) > limit:
        raise UpdateError("The release response was too large")
    return raw


def _strict_json_object(raw: bytes) -> dict[str, Any]:
    def pairs_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise UpdateError(f"Duplicate release metadata key: {key}")
            result[key] = value
        return result

    try:
        document = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs_hook)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpdateError("GitHub returned invalid release metadata") from exc
    if not isinstance(document, dict):
        raise UpdateError("GitHub release metadata must be an object")
    return document


def _required_string(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise UpdateError(f"Release metadata field {key} is invalid")
    return value


def _reject_reparse_point(path: Path) -> None:
    stat = path.lstat()
    attributes = int(getattr(stat, "st_file_attributes", 0))
    reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    if path.is_symlink() or attributes & reparse_flag:
        raise UpdateError("The update staging path cannot be a link or reparse point")
