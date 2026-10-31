"""Write the updater manifest (latest.json) for a release.

    python latest_json.py <assets dir> <version> <download base URL> [notes]

<assets dir> holds the release assets of every platform, with each update
package next to its signature (<file>.sig, written by `tauri build` when the
signing key is set). <download base URL> is where the assets will be served,
e.g. https://github.com/<owner>/<repo>/releases/download/v1.31.

The app asks for releases/latest/download/latest.json, so a release is offered
only once it is published (drafts and pre-releases are not "latest").
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Update package suffix → updater platform keys. The updater tries
# "<os>-<arch>-<installer>" first, then "<os>-<arch>".
PACKAGES = {
    ".AppImage": ["linux-x86_64", "linux-x86_64-appimage"],
    "-setup.exe": ["windows-x86_64", "windows-x86_64-nsis"],
    ".msi": ["windows-x86_64-msi"],
    ".app.tar.gz": ["darwin-aarch64", "darwin-aarch64-app"],
}


def manifest(assets: Path, version: str, base_url: str, notes: str = "") -> dict:
    platforms: dict[str, dict] = {}
    for sig in sorted(assets.glob("*.sig")):
        package = sig.with_suffix("")                      # drop .sig
        keys = next((k for suffix, k in PACKAGES.items() if package.name.endswith(suffix)), None)
        if keys is None or not package.exists():
            continue
        entry = {"signature": sig.read_text(encoding="utf-8").strip(),
                 "url": f"{base_url.rstrip('/')}/{package.name}"}
        for key in keys:
            platforms[key] = entry
    if not platforms:
        raise SystemExit(f"no signed update packages in {assets}")
    return {"version": version.lstrip("v"), "notes": notes,
            "pub_date": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "platforms": platforms}


if __name__ == "__main__":
    if len(sys.argv) not in (4, 5):
        raise SystemExit(__doc__)
    assets = Path(sys.argv[1])
    out = manifest(assets, sys.argv[2], sys.argv[3], sys.argv[4] if len(sys.argv) == 5 else "")
    (assets / "latest.json").write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print("latest.json:", ", ".join(sorted(out["platforms"])))
