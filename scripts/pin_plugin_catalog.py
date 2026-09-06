"""Pin selected catalog entries to committed Git bytes, never worktree line endings."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def git_bytes(*args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True).stdout


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("plugin_ids", nargs="+")
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.source_commit):
        parser.error("Use a full immutable 40-character source commit")
    commit = git_bytes("rev-parse", "--verify", args.source_commit + "^{commit}").decode().strip()
    catalog_path = ROOT / "plugin_catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    for plugin_id in args.plugin_ids:
        if not re.fullmatch(r"amazify\.[a-z0-9.-]+", plugin_id):
            parser.error("Expected an Amazify stock plugin ID")
        root = f"sample_plugins/{plugin_id}"
        manifest = json.loads(git_bytes("show", f"{commit}:{root}/manifest.json"))
        if manifest["id"] != plugin_id:
            parser.error("Manifest ID does not match its directory")
        paths = ["manifest.json", manifest["entry"], *manifest.get("styles", []), *manifest.get("assets", {}).values()]
        files = []
        for path in dict.fromkeys(paths):
            if not isinstance(path, str) or ".." in path.split("/") or path.startswith("/") or "\\" in path:
                parser.error("Plugin manifest contains an unsafe file path")
            content = git_bytes("show", f"{commit}:{root}/{path}")
            files.append({"path": path, "sha256": hashlib.sha256(content).hexdigest(), "size": len(content)})
        entry = {
            "id": plugin_id, "trust": "stock", "repository": "eripum9/Amazify",
            "sourceCommit": commit, "pluginRoot": root,
            "minimumAmazifyVersion": manifest["minimumAmazifyVersion"],
            "manifest": manifest, "files": files,
        }
        index = next((i for i, plugin in enumerate(catalog["plugins"]) if plugin["id"] == plugin_id), None)
        if index is None:
            catalog["plugins"].append(entry)
        else:
            catalog["plugins"][index] = entry
    catalog_path.write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
