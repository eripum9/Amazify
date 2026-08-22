from __future__ import annotations

import shutil
import subprocess
import unittest

from amazify.runtime import build_cleanup_script, build_runtime_script


class RuntimeScriptTests(unittest.TestCase):
    def test_generated_runtime_is_valid_javascript(self) -> None:
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is unavailable")
        script = build_runtime_script(
            bridge_url="http://127.0.0.1:12345",
            bridge_token="token",
            plugins=[],
            native_session_nonce="nonce",
            native_response_callback="__amazifyNativeResult_" + "a" * 36,
        )

        result = subprocess.run(
            [node, "--check", "-"],
            input=script,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)

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
        self.assertIn("host.appendChild(state.root)", script)
        self.assertIn("host.appendChild(root)", script)
        self.assertIn("data-amazify-panel", script)
        self.assertIn("syncPlugins", script)
        self.assertIn("syncCatalog", script)
        self.assertIn("catalog.refresh", script)
        self.assertIn("updateAvailable", script)
        self.assertIn("plugins.install", script)
        self.assertIn("data-amazify-install-plugin", script)
        self.assertIn("plugins.disableAll", script)
        self.assertIn("SETTINGS_STORAGE_KEY", script)
        self.assertIn('data-amazify-setting="autoCheckUpdates"', script)
        self.assertNotIn('data-amazify-setting="enableAfterDownload"', script)
        self.assertIn("data-amazify-refresh-catalog", script)
        self.assertIn("Available updates", script)
        self.assertIn("Catalog source", script)
        self.assertNotIn("amazify-safety-row", script)
        self.assertNotIn('<div class="amazify-section-title">Safety</div>', script)
        self.assertIn("buildPluginApi", script)
        self.assertIn("Plugins may only access their own assets", script)
        self.assertIn("rewriteCssAssetUrls", script)
        self.assertIn("assetUrl", script)
        self.assertIn("LOGO_DATA_URI", script)
        self.assertIn("data:image/png;base64,", script)
        self.assertIn("amazify-logo", script)
        self.assertIn("amazify-header-label", script)
        self.assertNotIn('class="amazify-mark">A', script)

    def test_runtime_keeps_privileged_internals_out_of_global_api(self) -> None:
        script = build_runtime_script(
            bridge_url="http://127.0.0.1:12345",
            bridge_token="token",
            plugins=[],
            native_session_nonce="n" * 43,
            native_response_callback="__amazifyNativeResult_" + "a" * 36,
        )

        self.assertIn('NATIVE_DEFINE_PROPERTY(window, "Amazify"', script)
        self.assertIn("plugins: publicPluginLookup", script)
        self.assertIn("NATIVE_SESSION_NONCE", script)
        self.assertIn("NATIVE_SET_HAS", script)
        self.assertIn("NATIVE_SET_ADD", script)
        self.assertIn("delete window.AmazifyNativeCommand", script)
        self.assertIn("NATIVE_ADD_EVENT_LISTENER(window, CLEANUP_EVENT", script)
        self.assertNotIn("window.Amazify = {", script)
        self.assertNotIn("window.Amazify.cleanup", script)
        self.assertNotIn("window.Amazify.receiveNativeResult", script)
        self.assertNotIn("window.Amazify.bridge", script)

    def test_reinjection_captures_primitives_before_cleanup_and_credentials(self) -> None:
        bridge_token = "source-order-secret"
        native_nonce = "native-session-secret"
        script = build_runtime_script(
            bridge_url="http://127.0.0.1:12345",
            bridge_token=bridge_token,
            plugins=[],
            native_session_nonce=native_nonce,
            native_response_callback="__amazifyNativeResult_" + "b" * 36,
        )

        cleanup_index = script.index(
            "NATIVE_DISPATCH_EVENT(window, new NATIVE_EVENT(CLEANUP_EVENT))"
        )
        for marker in (
            "const NATIVE_FETCH",
            "const NATIVE_COMMAND",
            "const NATIVE_JSON_PARSE",
            "const NATIVE_JSON_STRINGIFY",
            "const NATIVE_DISPATCH_EVENT",
            "const NATIVE_EVENT",
        ):
            self.assertLess(script.index(marker), cleanup_index)
        self.assertLess(cleanup_index, script.index(f'const BRIDGE_TOKEN = "{bridge_token}"'))
        self.assertLess(
            cleanup_index,
            script.index(f'const NATIVE_SESSION_NONCE = "{native_nonce}"'),
        )
        self.assertEqual(
            script.count(
                "NATIVE_DISPATCH_EVENT(window, new NATIVE_EVENT(CLEANUP_EVENT))"
            ),
            1,
        )

    def test_privileged_bridge_bodies_use_captured_json_serializer(self) -> None:
        script = build_runtime_script(
            bridge_url="http://127.0.0.1:12345",
            bridge_token="token",
            plugins=[],
        )

        self.assertNotIn("JSON.stringify(", script)
        self.assertEqual(script.count("body: NATIVE_JSON_STRINGIFY("), 5)

    def test_marketplace_lifecycle_clicks_require_trusted_events(self) -> None:
        script = build_runtime_script(
            bridge_url="http://127.0.0.1:12345",
            bridge_token="token",
            plugins=[],
        )

        self.assertIn("function addTrustedLifecycleClick(target, handler)", script)
        self.assertIn("if (!event || event.isTrusted !== true) return;", script)
        self.assertIn(
            'addTrustedLifecycleClick(menu.querySelector("[data-amazify-disable-all]")',
            script,
        )
        self.assertIn("addTrustedLifecycleClick(toggle, async () =>", script)
        self.assertIn(
            "addTrustedLifecycleClick(disableAllButton, disableAllPlugins)", script
        )
        self.assertIn("addTrustedLifecycleClick(button, async () =>", script)
        self.assertNotIn(
            'addEventListener("click", disableAllPlugins)',
            script,
        )

    def test_install_flow_requires_explicit_confirmation_and_integrity(self) -> None:
        script = build_runtime_script(
            bridge_url="http://127.0.0.1:12345",
            bridge_token="token",
            plugins=[],
        )

        self.assertIn("NATIVE_CONFIRM", script)
        self.assertIn("SHA-256", script)
        self.assertIn("will remain disabled", script)
        self.assertIn("NATIVE_JSON_STRINGIFY", script)

    def test_cleanup_script_removes_injected_markers(self) -> None:
        script = build_cleanup_script()

        self.assertIn("amazify-runtime-cleanup-request", script)
        self.assertNotIn("window.Amazify.cleanup", script)
        self.assertIn("data-amazify-root", script)
        self.assertIn("data-amazify-style-id", script)


if __name__ == "__main__":
    unittest.main()
