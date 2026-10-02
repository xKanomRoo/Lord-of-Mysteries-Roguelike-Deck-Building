"""Validate the only public online configuration allowed in the native APK."""
from __future__ import annotations
import argparse
import base64
import json
from pathlib import Path
import re


def unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("Duplicate JSON properties are not allowed")
        result[name] = value
    return result


def validate_config(project: Path) -> bool:
    path = project / "cloud-config.json"
    if not path.exists():
        return False
    if path.stat().st_size > 4096:
        raise ValueError("Cloud configuration exceeds the allowed size")
    config = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_object)
    if not isinstance(config, dict) or set(config) != {"base_url", "public_key"}:
        raise ValueError("Only the project URL and public key may enter the APK")
    url, key = config["base_url"], config["public_key"]
    if not isinstance(url, str) or not isinstance(key, str):
        raise ValueError("Cloud configuration must contain strings")
    if not re.fullmatch(r"https://[A-Za-z0-9][A-Za-z0-9.-]*(?::443)?/?", url):
        raise ValueError("Cloud project URL must be a bare HTTPS URL")
    if not 20 <= len(key) <= 2048 or "\n" in key or "\r" in key:
        raise ValueError("Invalid public key format")
    public = bool(re.fullmatch(r"sb_publishable_[A-Za-z0-9_-]+", key))
    if not public and key.count(".") == 2:
        part = key.split(".")[1]
        try:
            claims = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)),
                                object_pairs_hook=unique_object)
            public = isinstance(claims, dict) and claims.get("role") == "anon"
        except (ValueError, UnicodeError):
            pass
    if not public:
        raise ValueError("Only a publishable or legacy anon public key may enter the APK")
    # A key-type check only; server-side Auth verifies tokens and RLS protects rows.
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    args = parser.parse_args()
    try:
        enabled = validate_config(args.project)
    except (OSError, ValueError, TypeError):
        raise SystemExit("Cloud configuration rejected. Use a bare HTTPS URL and only a publishable/anon public key, or remove this file for offline play.") from None
    print("Public cloud configuration verified." if enabled else "Offline APK: no cloud configuration supplied.")


if __name__ == "__main__":
    main()
