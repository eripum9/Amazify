from __future__ import annotations

import re
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = ROOT / ".github" / "workflows"
INSTALLER_SCRIPT = ROOT / "packaging" / "Amazify.iss"
BUILD_SCRIPT = ROOT / "Build.bat"
ACTION_REF_RE = re.compile(r"^\s*uses:\s*([^\s#]+)", re.MULTILINE)
FULL_SHA_RE = re.compile(r"[^@]+@[0-9a-f]{40}")
WRITE_PERMISSION_RE = re.compile(r"^\s*([a-z-]+):\s*write\s*$", re.MULTILINE)


def workflows() -> dict[str, str]:
    return {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted(WORKFLOW_DIR.glob("*.yml"))
    }


def run_blocks(text: str) -> list[str]:
    lines = text.splitlines()
    blocks: list[str] = []
    index = 0
    while index < len(lines):
        match = re.match(r"^(\s*)run:\s*(.*)$", lines[index])
        if not match:
            index += 1
            continue
        indent = len(match.group(1))
        remainder = match.group(2)
        if remainder not in {"|", ">", "|-", ">-"}:
            blocks.append(remainder)
            index += 1
            continue
        body: list[str] = []
        index += 1
        while index < len(lines):
            line = lines[index]
            if line.strip() and len(line) - len(line.lstrip()) <= indent:
                break
            body.append(line)
            index += 1
        blocks.append("\n".join(body))
    return blocks


class WorkflowSecurityContractTests(unittest.TestCase):
    def test_expected_workflows_exist(self) -> None:
        self.assertEqual(
            set(workflows()),
            {"build-windows.yml", "ci-windows.yml", "security.yml"},
        )

    def test_workflows_are_valid_yaml(self) -> None:
        for filename, text in workflows().items():
            with self.subTest(workflow=filename):
                self.assertIsNotNone(yaml.safe_load(text))

    def test_external_actions_are_pinned_to_full_commits(self) -> None:
        for filename, text in workflows().items():
            with self.subTest(workflow=filename):
                references = ACTION_REF_RE.findall(text)
                self.assertTrue(references)
                for reference in references:
                    if reference.startswith("./"):
                        continue
                    self.assertRegex(reference, FULL_SHA_RE)
                    self.assertNotRegex(reference, r"@(main|master|v?\d+(?:\.\d+)*)$")

    def test_checkout_never_persists_credentials(self) -> None:
        for filename, text in workflows().items():
            checkout_count = len(re.findall(r"uses:\s*actions/checkout@", text))
            disabled_count = len(re.findall(r"persist-credentials:\s*false", text))
            with self.subTest(workflow=filename):
                self.assertGreater(checkout_count, 0)
                self.assertEqual(disabled_count, checkout_count)

    def test_workflows_use_least_privilege_permissions(self) -> None:
        allowed_write_permissions = {
            "build-windows.yml": {"attestations", "id-token"},
            "ci-windows.yml": set(),
            "security.yml": {"security-events"},
        }
        for filename, text in workflows().items():
            with self.subTest(workflow=filename):
                self.assertRegex(text, r"(?m)^permissions:\n  contents: read(?:\n|$)")
                self.assertNotIn("write-all", text.lower())
                self.assertNotRegex(text, r"(?m)^\s*contents:\s*write\s*$")
                self.assertEqual(
                    set(WRITE_PERMISSION_RE.findall(text)),
                    allowed_write_permissions[filename],
                )

    def test_run_scripts_do_not_interpolate_manual_inputs(self) -> None:
        unsafe = ("${{ inputs.", "${{ github.event.inputs.")
        for filename, text in workflows().items():
            for block in run_blocks(text):
                with self.subTest(workflow=filename, block=block[:60]):
                    self.assertFalse(any(marker in block for marker in unsafe))

    def test_no_workflow_can_publish_a_release(self) -> None:
        forbidden = (
            r"\bgh\s+release\b",
            r"/releases(?:/|\b)",
            r"actions/create-release",
            r"softprops/action-gh-release",
            r"ncipollo/release-action",
            r"\bcreate\s+(?:or\s+update\s+)?draft\s+release\b",
        )
        for filename, text in workflows().items():
            with self.subTest(workflow=filename):
                for pattern in forbidden:
                    self.assertNotRegex(text.lower(), pattern)

    def test_candidate_workflow_is_manual_only(self) -> None:
        text = workflows()["build-windows.yml"]
        self.assertRegex(text, r"(?m)^  workflow_dispatch:\s*$")
        self.assertNotRegex(text, r"(?m)^  (push|pull_request|schedule):\s*$")
        self.assertIn("Upload candidate artifact", text)
        self.assertIn("actions/attest@", text)
        self.assertIn("create-storage-record: false", text)

    def test_candidate_installer_smoke_is_isolated(self) -> None:
        workflow = workflows()["build-windows.yml"]
        installer = INSTALLER_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("$env:RUNNER_TEMP", workflow)
        self.assertIn("/CI-SMOKE=1", workflow)
        self.assertIn("!startupdaemon,!desktopicon,!taskbaricon", workflow)
        self.assertIn("function IsCiSmoke(): Boolean;", installer)
        self.assertGreaterEqual(installer.count("Check: not IsCiSmoke"), 12)
        self.assertIn("if IsCiSmoke then Exit;", installer)
        self.assertIn("(CurStep = ssPostInstall) and (not IsCiSmoke)", installer)
        self.assertIn(
            "(CurUninstallStep = usPostUninstall) and (not IsCiSmoke)", installer
        )

    def test_python_and_dependency_installs_are_reproducible(self) -> None:
        for filename, text in workflows().items():
            with self.subTest(workflow=filename):
                if "actions/setup-python@" in text:
                    versions = re.findall(r'python-version:\s*["\']?([^"\'\s]+)', text)
                    self.assertTrue(versions)
                    self.assertEqual(set(versions), {"3.12.10"})
                for block in run_blocks(text):
                    for line in block.splitlines():
                        if re.search(r"\bpip\s+install\b.*\s-r\s+requirements", line):
                            self.assertIn("--require-hashes", line)
                            self.assertIn("--only-binary=:all:", line)

    def test_packaging_does_not_use_ambient_upx(self) -> None:
        build_script = BUILD_SCRIPT.read_text(encoding="utf-8")
        pyinstaller_commands = [
            line
            for line in build_script.splitlines()
            if "-m PyInstaller" in line
        ]
        self.assertEqual(len(pyinstaller_commands), 2)
        for command in pyinstaller_commands:
            self.assertIn("--noupx", command)


if __name__ == "__main__":
    unittest.main()
