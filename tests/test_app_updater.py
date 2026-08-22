from __future__ import annotations

import hashlib
import io
import tempfile
import unittest
import urllib.error
from dataclasses import replace
from email.message import Message
from pathlib import Path
from unittest import mock

from amazify.app_updater import (
    INSTALLER_ASSET_NAME,
    MAX_INSTALLER_BYTES,
    RELEASE_API_URL,
    ApplicationUpdater,
    ReleaseInfo,
    UpdateError,
    download_installer,
    fetch_latest_release,
    launch_installer,
    parse_release_document,
    parse_version,
    update_available,
    verify_installer,
)


def installer_bytes() -> bytes:
    return b"MZ" + b"verified-amazify-installer" * 32


def release_info(payload: bytes | None = None, *, version: str = "1.1.0") -> ReleaseInfo:
    content = payload if payload is not None else installer_bytes()
    return ReleaseInfo(
        version=version,
        tag_name=f"v{version}",
        release_url=f"https://github.com/eripum9/Amazify/releases/tag/v{version}",
        published_at="2026-08-22T18:00:00Z",
        installer_url=(
            f"https://github.com/eripum9/Amazify/releases/download/v{version}/"
            f"{INSTALLER_ASSET_NAME}"
        ),
        installer_sha256=hashlib.sha256(content).hexdigest(),
        installer_size=len(content),
    )


def release_document(payload: bytes | None = None) -> dict[str, object]:
    release = release_info(payload)
    return {
        "tag_name": release.tag_name,
        "html_url": release.release_url,
        "published_at": release.published_at,
        "draft": False,
        "prerelease": False,
        "assets": [
            {
                "name": INSTALLER_ASSET_NAME,
                "state": "uploaded",
                "size": release.installer_size,
                "digest": f"sha256:{release.installer_sha256}",
                "browser_download_url": release.installer_url,
            }
        ],
    }


def headers(**values: str) -> Message:
    result = Message()
    for key, value in values.items():
        result.add_header(key.replace("_", "-"), value)
    return result


class FakeResponse:
    def __init__(
        self,
        payload: bytes,
        *,
        url: str,
        status: int = 200,
        response_headers: Message | None = None,
    ) -> None:
        self._stream = io.BytesIO(payload)
        self._url = url
        self.status = status
        self.headers = response_headers or headers(Content_Length=str(len(payload)))

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)

    def geturl(self) -> str:
        return self._url

    def getcode(self) -> int:
        return self.status

    def close(self) -> None:
        self._stream.close()

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


class FakeOpener:
    def __init__(self, responses: list[object]) -> None:
        self.responses = list(responses)
        self.requests: list[object] = []

    def open(self, request: object, *, timeout: int) -> FakeResponse:
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response  # type: ignore[return-value]


class ApplicationUpdaterTests(unittest.TestCase):
    def test_versions_are_strict_and_numeric(self) -> None:
        self.assertEqual(parse_version("1.20.3"), (1, 20, 3))
        self.assertTrue(update_available("1.9.9", "1.10.0"))
        for invalid in ("v1.0.0", "1.0", "01.0.0", "1.0.0-beta", "1.0.0.0"):
            with self.subTest(version=invalid), self.assertRaises(UpdateError):
                parse_version(invalid)

    def test_release_document_requires_exact_final_release_and_installer(self) -> None:
        parsed = parse_release_document(release_document())

        self.assertEqual(parsed.version, "1.1.0")
        self.assertEqual(parsed.installer_sha256, release_info().installer_sha256)

        mutations = []
        draft = release_document()
        draft["draft"] = True
        mutations.append(draft)
        prerelease = release_document()
        prerelease["prerelease"] = True
        mutations.append(prerelease)
        wrong_page = release_document()
        wrong_page["html_url"] = "https://github.com/attacker/Amazify/releases/tag/v1.1.0"
        mutations.append(wrong_page)
        wrong_asset_url = release_document()
        wrong_asset_url["assets"][0]["browser_download_url"] = (  # type: ignore[index]
            "https://example.com/AmazifySetup.exe"
        )
        mutations.append(wrong_asset_url)
        missing_digest = release_document()
        missing_digest["assets"][0]["digest"] = ""  # type: ignore[index]
        mutations.append(missing_digest)
        too_large = release_document()
        too_large["assets"][0]["size"] = MAX_INSTALLER_BYTES + 1  # type: ignore[index]
        mutations.append(too_large)

        for document in mutations:
            with self.subTest(document=document), self.assertRaises(UpdateError):
                parse_release_document(document)  # type: ignore[arg-type]

    def test_fetch_latest_release_rejects_redirects_and_non_json(self) -> None:
        redirect_headers = headers(Location="https://example.com/release.json")
        redirect = urllib.error.HTTPError(
            RELEASE_API_URL,
            302,
            "Found",
            redirect_headers,
            None,
        )
        with (
            mock.patch(
                "amazify.app_updater.urllib.request.build_opener",
                return_value=FakeOpener([redirect]),
            ),
            self.assertRaisesRegex(UpdateError, "redirected unexpectedly"),
        ):
            fetch_latest_release()

        response = FakeResponse(
            b"not-json",
            url=RELEASE_API_URL,
            response_headers=headers(Content_Type="text/plain"),
        )
        with (
            mock.patch(
                "amazify.app_updater.urllib.request.build_opener",
                return_value=FakeOpener([response]),
            ),
            self.assertRaisesRegex(UpdateError, "was not JSON"),
        ):
            fetch_latest_release()

    def test_download_follows_only_approved_redirect_and_verifies_bytes(self) -> None:
        payload = installer_bytes()
        release = release_info(payload)
        asset_url = "https://release-assets.githubusercontent.com/github-production/release"
        redirect = urllib.error.HTTPError(
            release.installer_url,
            302,
            "Found",
            headers(Location=asset_url),
            None,
        )
        response = FakeResponse(
            payload,
            url=asset_url,
            response_headers=headers(Content_Length=str(len(payload))),
        )
        opener = FakeOpener([redirect, response])
        progress: list[tuple[int, int]] = []

        with tempfile.TemporaryDirectory() as temp, mock.patch(
            "amazify.app_updater.urllib.request.build_opener", return_value=opener
        ):
            path = download_installer(
                release,
                Path(temp),
                lambda downloaded, total: progress.append((downloaded, total)),
            )

            self.assertEqual(path.read_bytes(), payload)
            verify_installer(path, release)
            self.assertEqual(progress[-1], (len(payload), len(payload)))
            self.assertEqual(len(opener.requests), 2)

    def test_download_rejects_unapproved_redirect_and_hash_mismatch(self) -> None:
        payload = installer_bytes()
        release = release_info(payload)
        redirect = urllib.error.HTTPError(
            release.installer_url,
            302,
            "Found",
            headers(Location="https://example.com/AmazifySetup.exe"),
            None,
        )
        with tempfile.TemporaryDirectory() as temp, mock.patch(
            "amazify.app_updater.urllib.request.build_opener",
            return_value=FakeOpener([redirect]),
        ), self.assertRaisesRegex(UpdateError, "host is not approved"):
            download_installer(release, Path(temp))

        bad_payload = b"MZ" + b"substituted"
        response = FakeResponse(
            bad_payload,
            url=release.installer_url,
            response_headers=headers(Content_Length=str(len(bad_payload))),
        )
        same_size_release = replace(release, installer_size=len(bad_payload))
        with tempfile.TemporaryDirectory() as temp, mock.patch(
            "amazify.app_updater.urllib.request.build_opener",
            return_value=FakeOpener([response]),
        ), self.assertRaisesRegex(UpdateError, "SHA-256 verification failed"):
            download_installer(same_size_release, Path(temp))

    def test_application_updater_tracks_check_download_and_launch(self) -> None:
        release = release_info()
        calls: list[object] = []

        def downloader(
            selected: ReleaseInfo,
            update_dir: Path,
            progress: object,
        ) -> Path:
            calls.append((selected, update_dir))
            assert callable(progress)
            progress(selected.installer_size, selected.installer_size)
            return update_dir / INSTALLER_ASSET_NAME

        def launcher(path: Path, selected: ReleaseInfo) -> None:
            calls.append((path, selected))

        with tempfile.TemporaryDirectory() as temp:
            updater = ApplicationUpdater(
                Path(temp),
                current_version="1.0.0",
                release_fetcher=lambda: release,
                installer_downloader=downloader,
                installer_launcher=launcher,
            )

            checked = updater.check_now()
            installed = updater.install_now()

        self.assertTrue(checked["updateAvailable"])
        self.assertEqual(checked["status"], "available")
        self.assertEqual(installed.name, INSTALLER_ASSET_NAME)
        self.assertEqual(updater.snapshot()["status"], "launched")
        self.assertEqual(updater.snapshot()["progress"], 100)
        self.assertEqual(len(calls), 2)

    def test_failed_recheck_clears_cached_release_metadata(self) -> None:
        release = release_info()
        responses: list[ReleaseInfo | UpdateError] = [
            release,
            UpdateError("GitHub is unavailable"),
        ]

        def fetcher() -> ReleaseInfo:
            response = responses.pop(0)
            if isinstance(response, UpdateError):
                raise response
            return response

        with tempfile.TemporaryDirectory() as temp:
            updater = ApplicationUpdater(
                Path(temp),
                current_version="1.0.0",
                release_fetcher=fetcher,
            )
            updater.check_now()
            with self.assertRaisesRegex(UpdateError, "GitHub is unavailable"):
                updater.check_now()
            failed = updater.snapshot()

        self.assertEqual(failed["status"], "error")
        self.assertFalse(failed["updateAvailable"])
        self.assertEqual(failed["latestVersion"], "")
        self.assertEqual(failed["releaseUrl"], "")
        self.assertEqual(failed["totalBytes"], 0)

    def test_launch_reverifies_before_using_argument_list(self) -> None:
        payload = installer_bytes()
        release = release_info(payload)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / INSTALLER_ASSET_NAME
            path.write_bytes(payload)
            with mock.patch("amazify.app_updater.subprocess.Popen") as popen:
                launch_installer(path, release)

        command = popen.call_args.args[0]
        self.assertEqual(command[0], str(path))
        self.assertIn("/CLOSEAPPLICATIONS", command)
        self.assertNotIn("cmd", command)
        self.assertNotIn("powershell", command)
        self.assertTrue(popen.call_args.kwargs["close_fds"])


if __name__ == "__main__":
    unittest.main()
