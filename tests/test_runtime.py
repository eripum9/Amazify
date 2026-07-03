from __future__ import annotations

import unittest

from amazify.runtime import build_cleanup_script, build_runtime_script


class RuntimeScriptTests(unittest.TestCase):
    def test_runtime_script_contains_contract_markers(self) -> None:
        script = build_runtime_script(
            bridge_url="http://127.0.0.1:12345",
            bridge_token="token",
            plugins=[],
        )

        self.assertIn("window.Amazify", script)
        self.assertIn('data-amazify-root="true"', script)
        self.assertIn("position: fixed", script)
        self.assertIn("findHeaderHost", script)
        self.assertIn("data-amazify-placement", script)
        self.assertIn("host.appendChild(root)", script)
        self.assertIn("data-amazify-panel", script)
        self.assertIn("syncPlugins", script)
        self.assertIn("syncCatalog", script)
        self.assertIn("catalog.refresh", script)
        self.assertIn("updateAvailable", script)
        self.assertIn("plugins.install", script)
        self.assertIn("data-amazify-install-plugin", script)
        self.assertIn("plugins.disableAll", script)
        self.assertIn("LOGO_DATA_URI", script)
        self.assertIn("data:image/png;base64,", script)
        self.assertIn("amazify-logo", script)
        self.assertIn("amazify-header-label", script)
        self.assertNotIn('class="amazify-mark">A', script)

    def test_cleanup_script_removes_injected_markers(self) -> None:
        script = build_cleanup_script()

        self.assertIn("window.Amazify.cleanup", script)
        self.assertIn("data-amazify-root", script)
        self.assertIn("data-amazify-style-id", script)


if __name__ == "__main__":
    unittest.main()
