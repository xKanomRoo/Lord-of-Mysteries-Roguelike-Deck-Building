#!/usr/bin/env python3
"""Fetch one statically verified startup profile; never run or decrypt game code.

This is an environment/version request, not a downloader for arbitrary URLs.
The response may require native interpretation. Response bodies stay in the
chosen private research directory and are never printed to the terminal.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


EXPECTED_APK_SHA256 = "6ef56d50d15168a8c29c080f8e621468876263de14410998fbc99ecca6179908"
EXPECTED_APK_BYTES = 22979689
SOURCE_LIBRARY_SHA256 = "a790283a8f283b767425feaab8281281c46b352a93c02da79f3baaf6065f04b0"
ENDPOINT = "https://live-czn-entry2lx2fz.game.playstove.com:13001/cznlive"
MAX_APK_BYTES = 30 * 1024 * 1024
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_ERROR_BYTES = 16 * 1024
TIMEOUT_SECONDS = 20
QUERY = (
    ("platform", "android"),
    ("appid", "cznlive"),
    ("build", "811"),
    ("lang", "en"),
    ("oslang", "en"),
    ("package", "com.smilegate.chaoszero.stove.google"),
    ("device_uid", ""),
    ("publisher_uid", ""),
    ("buildx", "4d05fb1ce48af8a7309ad719fcfb3023a850fa40631255ece8fd657163c929a9"),
)
HEADERS = {
    "X-App-Id": "cznlive",
    "X-App-NS": "ssr-stove-260930",
    "User-Agent": "Static-resource-research/1.0",
}


class FetchError(ValueError):
    """An invalid source or output prevents the network request."""


class ResponseReadError(Exception):
    """A transport failure with only a bounded, unexecuted response prefix."""

    def __init__(self, prefix: bytes, error_type: str):
        super().__init__(error_type)
        self.prefix = prefix
        self.error_type = error_type


TRANSPORT_ERRORS = (urllib.error.URLError, TimeoutError, ssl.SSLError,
                    ConnectionError, OSError, http.client.HTTPException)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Keep any redirect response at its original endpoint; do not follow it."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def build_request() -> urllib.request.Request:
    return urllib.request.Request(
        ENDPOINT + "?" + urllib.parse.urlencode(QUERY),
        headers=HEADERS,
        method="GET",
    )


def build_opener() -> urllib.request.OpenerDirector:
    # Keep normal environment routing, verify HTTPS certificates/hostnames,
    # and install neither cookie storage nor an authentication handler.
    context = ssl.create_default_context()
    return urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=context), NoRedirect(),
    )


def verify_apk(apk_path: Path) -> dict[str, Any]:
    apk_path = Path(apk_path)
    size = apk_path.stat().st_size
    if size > MAX_APK_BYTES:
        raise FetchError("APK exceeds the 30 MiB source limit")
    if size != EXPECTED_APK_BYTES:
        raise FetchError("APK size does not match the verified native split")
    digest = hashlib.sha256()
    with apk_path.open("rb") as source:
        remaining = MAX_APK_BYTES + 1
        while remaining:
            block = source.read(min(1024 * 1024, remaining))
            if not block:
                break
            digest.update(block)
            remaining -= len(block)
        if remaining == 0:
            raise FetchError("APK grew past the source limit while being read")
    actual = digest.hexdigest()
    if actual != EXPECTED_APK_SHA256:
        raise FetchError("APK SHA-256 does not match the verified native split")
    return {"filename": apk_path.name, "bytes": size, "sha256": actual}


def prepare_output(output_path: Path, apk_path: Path) -> None:
    output_path = Path(output_path)
    if output_path.resolve() == Path(apk_path).resolve():
        raise FetchError("Output must not replace the source APK")
    if os.path.lexists(output_path):
        if output_path.is_symlink() or not output_path.is_dir():
            raise FetchError("Output must be a new or empty directory, not a symlink")
        if any(output_path.iterdir()):
            raise FetchError("Output directory already contains files; choose a new directory")
    else:
        output_path.mkdir(parents=True)


def _read_bounded(response: Any, limit: int) -> tuple[bytes, bool]:
    """Read at most limit+1 bytes to establish truncation without draining a body."""
    chunks: list[bytes] = []
    observed = 0
    while observed <= limit:
        try:
            block = response.read(min(65536, limit + 1 - observed))
        except TRANSPORT_ERRORS as error:
            prefix = b"".join(chunks)[:limit]
            partial = getattr(error, "partial", b"")
            if isinstance(partial, bytes):
                prefix += partial[:max(0, limit - len(prefix))]
            # Preserve bytes already read and IncompleteRead.partial, while
            # keeping both transport exception text and excess bytes private.
            raise ResponseReadError(prefix, type(error).__name__) from None
        if not block:
            return b"".join(chunks), False
        if not isinstance(block, bytes):
            raise ValueError("HTTP response returned non-byte data")
        if len(block) > limit + 1 - observed:
            raise ValueError("HTTP response exceeded its requested read bound")
        chunks.append(block)
        observed += len(block)
    return b"".join(chunks)[:limit], True


def _content_length(response: Any) -> int | None:
    raw = response.headers.get("Content-Length")
    if isinstance(raw, str) and len(raw) <= 20 and raw.isascii() and raw.isdecimal():
        return int(raw)
    return None


def _save_body(output_path: Path, name: str, body: bytes, complete: bool) -> dict[str, Any]:
    # Exclusive creation preserves any file that appeared during the request.
    try:
        with (output_path / name).open("xb") as destination:
            destination.write(body)
    except OSError as error:
        raise FetchError("Cannot safely create private response artifact: "
                         + type(error).__name__) from error
    return {
        "file": name, "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(), "complete": complete,
    }


def _record_http_response(response: Any, output_path: Path,
                          result: dict[str, Any]) -> None:
    status = int(response.getcode())
    result["http_status"] = status
    result["declared_content_length"] = _content_length(response)
    if 200 <= status < 300:
        if (result["declared_content_length"] is not None
                and result["declared_content_length"] > MAX_RESPONSE_BYTES):
            result["status"] = "response_oversized"
            result["response"] = {"complete": False, "bytes": 0, "file": None,
                                  "reason": "declared_content_length_exceeds_limit"}
            return
        try:
            body, truncated = _read_bounded(response, MAX_RESPONSE_BYTES)
        except ResponseReadError as error:
            result["status"] = "response_read_error"
            result["body_read_error"] = {"type": error.error_type}
            result["response"] = _save_body(output_path, "response-prefix.bin", error.prefix, False)
            return
        result["status"] = "response_oversized" if truncated else "received"
        result["response"] = _save_body(
            output_path, "response-prefix.bin" if truncated else "response.bin",
            body, not truncated,
        )
        if (not truncated and result["declared_content_length"] is not None
                and len(body) != result["declared_content_length"]):
            result["status"] = "response_length_mismatch"
            result["response"]["complete"] = False
    else:
        result["status"] = ("redirect_not_followed" if 300 <= status < 400 else
                            "access_rejected" if status in (401, 403) else "http_error")
        try:
            body, truncated = _read_bounded(response, MAX_ERROR_BYTES)
        except ResponseReadError as error:
            # HTTP headers establish the source/status even if its body breaks.
            # An upstream 403 must remain distinct from a proxy tunnel failure.
            result["body_read_error"] = {"type": error.error_type}
            result["response"] = _save_body(output_path, "error-response.bin", error.prefix, False)
            return
        result["response"] = _save_body(output_path, "error-response.bin", body, not truncated)


def _network_error(error: BaseException, upstream_response_received: bool = False) -> dict[str, Any]:
    reason = error.reason if isinstance(error, urllib.error.URLError) else error
    # Exception text may contain local proxy configuration or credentials; record
    # a bounded classification only, never that text, response headers or cookies.
    tunnel_403 = isinstance(reason, OSError) and "Tunnel connection failed: 403" in str(reason)
    return {
        "status": "proxy_tunnel_rejected" if tunnel_403 else "network_error",
        "network_error_type": type(reason).__name__,
        "http_status": None,
        "upstream_response_received": upstream_response_received,
    }


def fetch_game_entry(apk_path: Path, output_path: Path, *, opener: Any = None) -> dict[str, Any]:
    """Verify this build, attempt one GET, and save a private bounded artifact.

    `opener` is an injection point for offline tests. The CLI always uses the
    built-in fixed-profile opener and offers no URL, ID, token or TLS override.
    Network or upstream failure is recorded and returned; invalid input raises.
    """
    apk_path, output_path = Path(apk_path), Path(output_path)
    source = verify_apk(apk_path)
    prepare_output(output_path, apk_path)
    request = build_request()
    result: dict[str, Any] = {
        "schema_version": 1,
        "analysis_type": "single_verified_game_startup_request",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "source_library": {"path": "lib/arm64-v8a/libssr.so",
                           "sha256": SOURCE_LIBRARY_SHA256},
        "native_evidence": {
            "endpoint_environment": {"symbol": "SSRApp::loadSourcePackEnv()", "va": "0x1bb3764"},
            "request": {"symbol": "yuna2d::async_load_remote_environment", "va": "0x1e40888"},
            "query": {"symbol": "yuna2d::get_app_query_string()", "va": "0x1e3f6cc"},
            "android_platform": {"symbol": "AppDelegate::applicationDidFinishLaunching()",
                                 "va": "0x1bc9300"},
        },
        "request": {"method": "GET", "endpoint": ENDPOINT, "query": dict(QUERY),
                    "headers": dict(HEADERS), "attempts": 1,
                    "timeout_seconds": TIMEOUT_SECONDS},
        "constraints": {"tls_verification": True, "redirects_followed": False,
                        "max_response_bytes": MAX_RESPONSE_BYTES,
                        "max_error_bytes": MAX_ERROR_BYTES,
                        "login_or_authentication_used": False,
                        "identifiers": "empty; no generated device or publisher ID",
                        "locale_assumption": "en", "response_executed_or_decrypted": False},
        "status": "not_requested", "http_status": None,
        "upstream_response_received": False,
    }
    selected_opener = opener if opener is not None else build_opener()
    response = None
    try:
        response = selected_opener.open(request, timeout=TIMEOUT_SECONDS)
    except urllib.error.HTTPError as error:
        response = error
    except TRANSPORT_ERRORS as error:
        result.update(_network_error(error))
    if response is not None:
        try:
            with response:
                result["upstream_response_received"] = True
                _record_http_response(response, output_path, result)
        except TRANSPORT_ERRORS as error:
            # Closing an established HTTP response can also fail. Keep its
            # known status and any bounded artifact; never call it a proxy 403.
            result["upstream_response_received"] = True
            result["response_close_error"] = {"type": type(error).__name__}
            if result["status"] == "received":
                result["status"] = "response_close_error"
    result["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
    with (output_path / "result.json").open("x", encoding="utf-8") as destination:
        json.dump(result, destination, ensure_ascii=False, indent=2)
        destination.write("\n")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("apk", type=Path, help="Verified config.arm64_v8a.apk from build 1.0.811")
    parser.add_argument("--output", required=True, type=Path,
                        help="New or empty private research directory, preferably under .local/")
    args = parser.parse_args(argv)
    try:
        result = fetch_game_entry(args.apk, args.output)
    except (FetchError, OSError, ValueError) as error:
        # Input/output errors are local and have no response body or credentials.
        print(f"Entry request failed: {error}", file=sys.stderr)
        return 1
    response = result.get("response", {})
    print(f"Status: {result['status']}; HTTP: {result['http_status']}")
    print(f"Saved body bytes: {response.get('bytes', 0)}; SHA-256: {response.get('sha256', 'none')}")
    print(f"Result: {args.output / 'result.json'}")
    return 0 if result["status"] == "received" else 1


if __name__ == "__main__":
    raise SystemExit(main())
