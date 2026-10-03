from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

import tomllib

from amazify import __version__


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_VERSION = "1.1.4"
EXPECTED_SIGNAL_STUDIO_VERSION = "0.2.2"


def matched_version(path: Path, pattern: str) -> str:
    match = re.search(pattern, path.read_text(encoding="utf-8"), re.MULTILINE)
    if not match:
        raise AssertionError(f"Could not read version from {path.relative_to(ROOT)}")
    return match.group(1)


class VersionMetadataTests(unittest.TestCase):
    def test_release_version_is_consistent(self) -> None:
        with (ROOT / "pyproject.toml").open("rb") as handle:
            project_version = str(tomllib.load(handle)["project"]["version"])

        versions = {
            "runtime": __version__,
            "project": project_version,
            "inno": matched_version(
                ROOT / "packaging" / "Amazify.iss",
                r'^#define\s+AppVersion\s+"([^"]+)"',
            ),
            "installer": matched_version(
                ROOT / "packaging" / "amazify_installer.py",
                r'^APP_VERSION\s*=\s*"([^"]+)"',
            ),
            "windows_resource": matched_version(
                ROOT / "packaging" / "Amazify.version",
                r'StringStruct\("ProductVersion",\s*"([^"]+)"\)',
            ),
        }

        self.assertEqual(set(versions.values()), {EXPECTED_VERSION}, versions)

        with (
            ROOT / "sample_plugins" / "amazify.theme.signal-studio" / "manifest.json"
        ).open(encoding="utf-8") as handle:
            signal_studio_version = json.load(handle)["version"]
        self.assertEqual(signal_studio_version, EXPECTED_SIGNAL_STUDIO_VERSION)


if __name__ == "__main__":
    unittest.main()
