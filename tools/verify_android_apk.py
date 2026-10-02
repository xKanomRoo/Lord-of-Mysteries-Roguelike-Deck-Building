"""Verify the signed native debug APK produced by this repository."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import zipfile


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apk", required=True, type=Path)
    parser.add_argument("--tool-root", required=True, type=Path)
    args = parser.parse_args()
    root = args.tool_root.resolve()
    settings = json.loads((root / "toolchain-paths.json").read_text())
    profile = settings["profile"]
    tools = Path(settings["sdk"]) / "build-tools" / profile["build_tools_version"]
    env = dict(os.environ, JAVA_HOME=settings["java"])
    signature = subprocess.check_output([str(tools / "apksigner"), "verify", "--verbose",
                                         "--print-certs", str(args.apk)], text=True, env=env)
    badging = subprocess.check_output([str(tools / "aapt"), "dump", "badging", str(args.apk)], text=True)
    manifest = subprocess.check_output([str(tools / "aapt"), "dump", "xmltree", str(args.apk),
                                        "AndroidManifest.xml"], text=True)
    expected = f"package: name='{profile['package_name']}'"
    if expected not in badging:
        raise ValueError("Unexpected Android package name")
    if f"versionCode='{profile['apk_version_code']}'" not in badging or f"versionName='{profile['apk_version_name']}'" not in badging:
        raise ValueError("Unexpected Android APK version")
    if f"sdkVersion:'{profile['min_sdk']}'" not in badging:
        raise ValueError("Unexpected Android minimum SDK")
    if f"targetSdkVersion:'{profile['target_sdk']}'" not in badging:
        raise ValueError("Unexpected Android target SDK")
    if "uses-permission: name='android.permission.INTERNET'" not in badging:
        raise ValueError("APK is missing Internet permission for optional cloud saves")
    if "android:screenOrientation" not in manifest or not re.search(
            r"android:screenOrientation[^\n]*\(type 0x10\)0x0\b", manifest):
        raise ValueError("Android activity is not configured landscape")
    with zipfile.ZipFile(args.apk) as archive:
        if archive.testzip() is not None:
            raise ValueError("APK member CRC verification failed")
        names = archive.namelist()
        libraries = [n for n in names if n.startswith("lib/") and n.endswith(".so")]
        if "lib/arm64-v8a/libgodot_android.so" not in libraries:
            raise ValueError("Native ARM64 Godot engine missing")
        if any(not n.startswith("lib/arm64-v8a/") for n in libraries):
            raise ValueError("Unexpected native architecture")
        assets = [n for n in names if n.startswith("assets/")]
        if "assets/project.binary" not in assets:
            raise ValueError("Godot project payload missing")
        if not any("game_engine" in n for n in assets):
            raise ValueError("Native game engine script missing")
        content_path = Path(__file__).resolve().parents[1] / "mobile/data/content.json"
        content_bytes = content_path.read_bytes()
        if len(content_bytes) > 1024 * 1024:
            raise ValueError("Original game content exceeds the allowed size")
        if archive.read("assets/data/content.json") != content_bytes:
            raise ValueError("Bundled original content differs from the current source")
        content = json.loads(content_bytes)
        if not isinstance(content, dict) or not isinstance(content.get("metadata"), dict) or content["metadata"].get("classification") != "original-adaptation":
            raise ValueError("Expected original-adaptation content metadata")
        counts = {}
        for key, count in profile["content_counts"].items():
            if not isinstance(content.get(key), list) or len(content[key]) != count:
                raise ValueError("Bundled game content counts differ from the build profile")
            counts[key] = count
        if any(n.endswith(('.html', '.htm', '.js', '.xapk', '.txt')) for n in assets):
            raise ValueError("Unexpected browser source, reference package or text book in APK")
        # This is a static packaging check, not proof of behavior on a phone.
        dex = {n: hashlib.sha256(archive.read(n)).hexdigest() for n in names
               if re.fullmatch(r"classes\d*\.dex", n)}
        webview_reference = any(b"Landroid/webkit/WebView;" in archive.read(n) for n in dex)
        template = root / "xdg-data/godot/export_templates" / profile["template_version"] / "android_debug.apk"
        with zipfile.ZipFile(template) as baseline:
            expected_dex = {n: hashlib.sha256(baseline.read(n)).hexdigest() for n in baseline.namelist()
                            if re.fullmatch(r"classes\d*\.dex", n)}
            expected_libraries = {n: hashlib.sha256(baseline.read(n)).hexdigest()
                                  for n in baseline.namelist()
                                  if n.startswith("lib/arm64-v8a/") and n.endswith(".so")}
        native_hashes = {n: hashlib.sha256(archive.read(n)).hexdigest() for n in libraries}
        if dex != expected_dex:
            raise ValueError("APK Java payload differs from the official native Godot template")
        if native_hashes != expected_libraries:
            raise ValueError("APK native libraries differ from the official ARM64 Godot template")
    receipt = {
        "apk": args.apk.name, "bytes": args.apk.stat().st_size,
        "sha256": hashlib.sha256(args.apk.read_bytes()).hexdigest(),
        "package": profile["package_name"], "min_sdk": profile["min_sdk"],
        "version_code": profile["apk_version_code"], "version_name": profile["apk_version_name"],
        "target_sdk": profile["target_sdk"], "orientation": "landscape",
        "internet_permission": True,
        "native_libraries": libraries, "assets": assets,
        "native_library_sha256": native_hashes,
        "native_libraries_match_official_template": True,
        "webview_class_reference": webview_reference,
        "webview_reference_context": "The official Godot template includes Android support classes; this reference alone is not a web-based game UI",
        "dex_matches_official_template": True,
        "web_wrapper_assets": False,
        "content": {"path": "assets/data/content.json", "bytes": len(content_bytes),
                    "sha256": hashlib.sha256(content_bytes).hexdigest(), "counts": counts,
                    "matches_current_source_bytes": True},
        "signature_verified": True,
        "signature": signature.strip(), "badging": badging.strip(),
        "verification_scope": "Static export, CRC, manifest, signature and payload verification; not a device launch test",
    }
    args.apk.with_suffix(".verification.json").write_text(json.dumps(receipt, indent=2) + "\n")
    args.apk.with_suffix(args.apk.suffix + ".sha256").write_text(f"{receipt['sha256']}  {args.apk.name}\n")
    print(json.dumps({k: v for k, v in receipt.items() if k not in ("assets", "signature", "badging")}, indent=2))


if __name__ == "__main__":
    main()
