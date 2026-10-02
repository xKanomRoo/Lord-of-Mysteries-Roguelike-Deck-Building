"""Install official, pinned native Android tooling without changing system files."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import shutil
import subprocess
import tarfile
import tempfile
import zipfile


def digest(path: Path, algorithm: str) -> str:
    h = hashlib.new(algorithm)
    with path.open("rb") as source:
        for data in iter(lambda: source.read(1024 * 1024), b""):
            h.update(data)
    return h.hexdigest()


def verify(path: Path, item: dict, limits: dict) -> None:
    if path.stat().st_size != limits["compressed_bytes"]:
        raise ValueError(f"Archive byte count mismatch: {path.name}")
    for key, algorithm in (("sha256", "sha256"), ("official_sha1", "sha1"),
                           ("official_sha512", "sha512")):
        if key in item and digest(path, algorithm) != item[key]:
            raise ValueError(f"Checksum mismatch: {path.name} ({algorithm})")


def child_path(destination: Path, name: str, prefix: str) -> Path | None:
    if prefix and name == prefix.rstrip("/"):
        return None
    if not name.startswith(prefix):
        raise ValueError(f"Archive member outside expected prefix: {name}")
    relative = name[len(prefix):]
    if not relative:
        return None
    p = PurePosixPath(relative)
    if p.is_absolute() or ".." in p.parts or "\\" in relative:
        raise ValueError(f"Unsafe archive member: {name}")
    return destination.joinpath(*p.parts)


def unpack(path: Path, destination: Path, item: dict, limits: dict) -> None:
    prefix = item["strip_prefix"]
    selected = set(item.get("members", []))
    if path.name.endswith(".tar.gz"):
        with tarfile.open(path, "r:gz") as archive:
            members = archive.getmembers()
            if len(members) > limits["selected_members"] or sum(m.size for m in members) > limits["expanded_bytes"]:
                raise ValueError("JDK archive exceeds the pinned extraction bounds")
            for member in members:
                target = child_path(destination, member.name, prefix)
                if target is None:
                    continue
                if member.issym() or member.islnk():
                    # The official JDK contains relative in-tree links.
                    resolved = (target.parent / member.linkname).resolve()
                    if not resolved.is_relative_to(destination.resolve()):
                        raise ValueError(f"Unsafe archive link: {member.name}")
                elif not (member.isdir() or member.isfile()):
                    raise ValueError(f"Unsupported archive member: {member.name}")
            archive.extractall(destination, members=members, filter="data")
        # tar retains its versioned directory; move its contents into stable jdk/.
        nested = destination / prefix.rstrip("/")
        for child in nested.iterdir():
            shutil.move(str(child), destination / child.name)
        nested.rmdir()
        return
    with zipfile.ZipFile(path) as archive:
        members = [member for member in archive.infolist()
                   if not selected or member.filename[len(prefix):] in selected]
        if len(members) > limits["selected_members"] or sum(m.file_size for m in members) > limits["expanded_bytes"]:
            raise ValueError("SDK/template archive exceeds the pinned extraction bounds")
        for member in members:
            target = child_path(destination, member.filename, prefix)
            if target is None:
                continue
            mode = member.external_attr >> 16
            if (mode & 0o170000) == 0o120000:
                raise ValueError(f"Unexpected ZIP symlink: {member.filename}")
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, target.open("wb") as sink:
                    shutil.copyfileobj(source, sink)
                target.chmod(0o755 if mode & 0o111 else 0o644)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tool-root", type=Path)
    parser.add_argument("--force-local-godot", action="store_true",
                        help="Install the pinned editor even if it is already available")
    args = parser.parse_args()
    if platform.system() != "Linux" or platform.machine() not in ("x86_64", "AMD64"):
        parser.error("This replay installer supports Linux x86_64; see docs/ANDROID_BUILD.md")
    repo = Path(__file__).resolve().parents[1]
    root = (args.tool_root or repo / ".local/android-tools").resolve()
    root.mkdir(parents=True, exist_ok=True)
    downloads = root / "downloads"
    downloads.mkdir(exist_ok=True)
    profile = json.loads((repo / "tools/android-toolchain.json").read_text())
    godot = None
    candidate = os.environ.get("GODOT_BIN") or shutil.which("godot")
    if candidate and not args.force_local_godot:
        version = subprocess.check_output([candidate, "--version"], text=True).strip()
        if version == profile["godot_version_output"]:
            godot = str(Path(candidate).resolve())
    for item in profile["archives"]:
        if item.get("optional_editor") and godot:
            continue
        path = downloads / item["name"]
        limits = profile["archive_limits"][item["name"]]
        if not path.exists():
            partial = path.with_suffix(path.suffix + ".partial")
            subprocess.run(["curl", "--fail", "--show-error", "--silent", "--location",
                            "--proto", "=https", "--tlsv1.2", "--retry", "2",
                            "--connect-timeout", "30", "--max-time", "1200",
                            "--max-filesize", str(limits["compressed_bytes"]),
                            "--output", str(partial), item["url"]], check=True)
            verify(partial, item, limits)
            partial.replace(path)
        verify(path, item, limits)
        destination = root / item["destination"]
        marker = destination / ".archive-pin.json"
        pin = json.dumps(item, sort_keys=True) + "\n"
        if not marker.exists() or marker.read_text() != pin:
            if destination.exists():
                raise ValueError(f"Unpinned existing tool directory: {destination}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix=".install-", dir=destination.parent) as temp:
                stage = Path(temp) / "payload"
                stage.mkdir()
                unpack(path, stage, item, limits)
                (stage / ".archive-pin.json").write_text(pin)
                stage.rename(destination)
        if item.get("optional_editor"):
            godot = str(destination / "Godot_v4.6.3-stable_linux.x86_64")
        print(f"Verified {item['name']}", flush=True)
    assert godot is not None
    if subprocess.check_output([godot, "--version"], text=True).strip() != profile["godot_version_output"]:
        raise ValueError("The installed Godot editor version does not match the profile")
    java = root / "jdk"
    sdk = root / "sdk"
    config = root / "xdg-config/godot"
    config.mkdir(parents=True, exist_ok=True)
    for dirname in ("xdg-cache", "xdg-data"):
        (root / dirname).mkdir(exist_ok=True)
    # Explicit debug-only key. Its public standard password is not a production secret.
    keystore = root / "debug.keystore"
    encoded_keystore = os.environ.get("GRAY_FOG_DEBUG_KEYSTORE_B64", "")
    if encoded_keystore:
        if len(encoded_keystore) > 4 * 1024 * 1024:
            raise ValueError("Debug keystore secret is too large")
        key_bytes = base64.b64decode(encoded_keystore, validate=True)
        if keystore.exists() and keystore.read_bytes() != key_bytes:
            raise ValueError("Provided debug key differs from existing local key; preserve the existing signing identity")
        if not keystore.exists():
            with tempfile.TemporaryDirectory(prefix=".key-", dir=root) as temp:
                candidate_key = Path(temp) / "debug.keystore"
                candidate_key.write_bytes(key_bytes)
                candidate_key.chmod(0o600)
                subprocess.run([str(java / "bin/keytool"), "-list", "-keystore", str(candidate_key),
                                "-storepass", "android", "-alias", "androiddebugkey"],
                               check=True, stdout=subprocess.DEVNULL)
                candidate_key.replace(keystore)
        else:
            subprocess.run([str(java / "bin/keytool"), "-list", "-keystore", str(keystore),
                            "-storepass", "android", "-alias", "androiddebugkey"],
                           check=True, stdout=subprocess.DEVNULL)
    if not keystore.exists():
        subprocess.run([str(java / "bin/keytool"), "-genkeypair", "-noprompt",
                        "-keystore", str(keystore), "-storepass", "android",
                        "-alias", "androiddebugkey", "-keypass", "android",
                        "-dname", "CN=Android Debug,O=Android,C=US", "-keyalg", "RSA",
                        "-keysize", "2048", "-validity", "10000"], check=True)
        keystore.chmod(0o600)
    settings = {
        "export/android/java_sdk_path": str(java),
        "export/android/android_sdk_path": str(sdk),
        "export/android/debug_keystore": str(keystore),
        "export/android/debug_keystore_user": "androiddebugkey",
        "export/android/debug_keystore_pass": "android",
    }
    text = '[gd_resource type="EditorSettings" format=3]\n\n[resource]\n'
    text += "\n".join(f"{key} = {json.dumps(value)}" for key, value in settings.items()) + "\n"
    (config / "editor_settings-4.6.tres").write_text(text)
    license_dir = sdk / "licenses"
    license_dir.mkdir(exist_ok=True)
    (license_dir / "android-sdk-license").write_text(profile["android_sdk_license_sha1"] + "\n")
    (root / "toolchain-paths.json").write_text(json.dumps({
        "godot": godot, "java": str(java), "sdk": str(sdk), "root": str(root),
        "license_accepted": profile["license_url"], "profile": profile,
    }, indent=2) + "\n")
    print(f"Native Android toolchain ready: {root}")


if __name__ == "__main__":
    main()
