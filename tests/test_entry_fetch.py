"""Offline synthetic source and HTTP tests; never contact the reference server."""

import hashlib
import http.client
import io
import json
import ssl
import tempfile
import unittest
import urllib.error
import urllib.parse
import urllib.request
from contextlib import redirect_stdout
from email.message import Message
from pathlib import Path
from unittest.mock import Mock, patch

from tools import fetch_game_entry as entry


class FakeResponse(io.BytesIO):
    def __init__(self, body=b"", status=200, content_length=None):
        super().__init__(body)
        self.status = status
        self.headers = Message()
        if content_length is not None:
            self.headers["Content-Length"] = str(content_length)
        self.requested_read_bytes = 0

    def getcode(self):
        return self.status

    def read(self, size=-1):
        if size < 0:
            raise AssertionError("Unbounded HTTP read")
        self.requested_read_bytes += size
        return super().read(size)


class EntryFetchTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="synthetic-entry-request-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.apk = self.root / "synthetic.apk"
        self.apk_bytes = b"synthetic source, never executable"
        self.apk.write_bytes(self.apk_bytes)
        self.output = self.root / "request"
        self.digest = hashlib.sha256(self.apk_bytes).hexdigest()
        for name, value in (("EXPECTED_APK_BYTES", len(self.apk_bytes)),
                            ("EXPECTED_APK_SHA256", self.digest)):
            patcher = patch.object(entry, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def fetch(self, response=None, error=None):
        opener = Mock()
        if error:
            opener.open.side_effect = error
        else:
            opener.open.return_value = response or FakeResponse(b"synthetic config")
        result = entry.fetch_game_entry(self.apk, self.output, opener=opener)
        self.assertEqual(opener.open.call_count, 1)
        return result, opener

    def test_success_is_saved_with_source_provenance_and_fixed_safe_request(self):
        body = b'{"synthetic":"response"}'
        result, opener = self.fetch(FakeResponse(body, content_length=len(body)))
        self.assertEqual(result["status"], "received")
        self.assertTrue(result["upstream_response_received"])
        self.assertEqual(self.output.joinpath("response.bin").read_bytes(), body)
        self.assertEqual(result["response"]["sha256"], hashlib.sha256(body).hexdigest())
        self.assertEqual(result["source"]["sha256"], self.digest)
        self.assertEqual(result["source_library"]["sha256"], entry.SOURCE_LIBRARY_SHA256)
        self.assertEqual(json.loads((self.output / "result.json").read_text()), result)
        request = opener.open.call_args.args[0]
        self.assertEqual(request.get_method(), "GET")
        self.assertIsNone(request.data)
        parsed = urllib.parse.urlsplit(request.full_url)
        self.assertEqual(parsed.scheme, "https")
        self.assertEqual(parsed.netloc, "live-czn-entry2lx2fz.game.playstove.com:13001")
        query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        self.assertEqual(query["device_uid"], [""])
        self.assertEqual(query["publisher_uid"], [""])
        self.assertEqual(query["lang"], ["en"])
        self.assertNotIn("token", query)
        self.assertNotIn("force_review", query)
        self.assertEqual(opener.open.call_args.kwargs, {"timeout": 20})
        self.assertEqual({name.lower() for name, value in request.header_items()},
                         {"x-app-id", "x-app-ns", "user-agent"})

    def test_wrong_hash_size_and_oversized_source_fail_before_output_or_http(self):
        opener = Mock()
        cases = (
            ("EXPECTED_APK_SHA256", "0" * 64, "SHA-256"),
            ("EXPECTED_APK_BYTES", len(self.apk_bytes) + 1, "size"),
            ("MAX_APK_BYTES", 1, "30 MiB"),
        )
        for name, value, message in cases:
            with self.subTest(name=name), patch.object(entry, name, value):
                with self.assertRaisesRegex(entry.FetchError, message):
                    entry.fetch_game_entry(self.apk, self.output, opener=opener)
                self.assertFalse(self.output.exists())
        opener.open.assert_not_called()

    def test_existing_output_and_symlink_are_preserved_before_http(self):
        opener = Mock()
        self.output.mkdir()
        existing = self.output / "result.json"
        existing.write_text("existing user output")
        with self.assertRaisesRegex(entry.FetchError, "already contains"):
            entry.fetch_game_entry(self.apk, self.output, opener=opener)
        self.assertEqual(existing.read_text(), "existing user output")
        opener.open.assert_not_called()
        link = self.root / "output-link"
        try:
            link.symlink_to(self.output, target_is_directory=True)
        except (NotImplementedError, OSError):
            return  # Windows without symlink privilege tests ordinary preservation.
        with self.assertRaisesRegex(entry.FetchError, "symlink"):
            entry.fetch_game_entry(self.apk, link, opener=opener)
        opener.open.assert_not_called()

    def test_declared_large_body_is_rejected_without_reading(self):
        response = FakeResponse(b"private body", content_length=entry.MAX_RESPONSE_BYTES + 1)
        result, _ = self.fetch(response)
        self.assertEqual(result["status"], "response_oversized")
        self.assertFalse(result["response"]["complete"])
        self.assertEqual(response.requested_read_bytes, 0)
        self.assertFalse((self.output / "response.bin").exists())

    def test_stream_is_bounded_even_if_length_missing_or_invalid(self):
        for length in (None, "not a number"):
            with self.subTest(length=length):
                self.output = self.root / ("invalid" if length else "missing")
                response = FakeResponse(b"x" * 100, content_length=length)
                with patch.object(entry, "MAX_RESPONSE_BYTES", 17):
                    result, _ = self.fetch(response)
                self.assertEqual(result["status"], "response_oversized")
                self.assertEqual(response.requested_read_bytes, 18)
                self.assertFalse(result["response"]["complete"])
                self.assertEqual(result["response"]["bytes"], 17)
                self.assertEqual((self.output / "response-prefix.bin").read_bytes(), b"x" * 17)

    def test_incomplete_length_is_recorded_as_unsuccessful(self):
        result, _ = self.fetch(FakeResponse(b"short", content_length=10))
        self.assertEqual(result["status"], "response_length_mismatch")
        self.assertFalse(result["response"]["complete"])

    def test_401_403_and_redirects_are_recorded_without_retry_or_follow(self):
        for status, classification in ((401, "access_rejected"), (403, "access_rejected"),
                                       (302, "redirect_not_followed"), (500, "http_error")):
            with self.subTest(status=status):
                self.output = self.root / str(status)
                headers = Message()
                headers["Location"] = "https://untrusted.invalid/?token=private"
                headers["Set-Cookie"] = "private-auth=secret"
                error = urllib.error.HTTPError(entry.ENDPOINT, status, "synthetic", headers,
                                               io.BytesIO(b"private denial response" * 20))
                with patch.object(entry, "MAX_ERROR_BYTES", 16):
                    result, _ = self.fetch(error=error)
                self.assertEqual(result["status"], classification)
                self.assertEqual(result["http_status"], status)
                self.assertTrue(result["upstream_response_received"])
                self.assertEqual(result["response"]["bytes"], 16)
                self.assertFalse(result["response"]["complete"])
                saved = (self.output / "result.json").read_text()
                self.assertNotIn("private-auth", saved)
                self.assertNotIn("token=private", saved)

    def test_proxy_tunnel_failure_is_distinct_from_upstream_403_and_sanitized(self):
        reason = OSError("Tunnel connection failed: 403 Forbidden; https://proxy-user:password@proxy")
        result, _ = self.fetch(error=urllib.error.URLError(reason))
        self.assertEqual(result["status"], "proxy_tunnel_rejected")
        self.assertIsNone(result["http_status"])
        self.assertFalse(result["upstream_response_received"])
        self.assertNotIn("password", (self.output / "result.json").read_text())
        self.assertEqual(list(self.output.iterdir()), [self.output / "result.json"])

    def test_upstream_403_incomplete_body_keeps_status_and_bounded_partial_artifact(self):
        class BrokenErrorBody(io.BytesIO):
            def __init__(self):
                super().__init__()
                self.calls = 0

            def read(self, size=-1):
                self.calls += 1
                if self.calls == 1:
                    return b"first "
                raise http.client.IncompleteRead(b"partial-response" * 100, 2000)

        error = urllib.error.HTTPError(entry.ENDPOINT, 403, "synthetic", Message(), BrokenErrorBody())
        with patch.object(entry, "MAX_ERROR_BYTES", 16):
            result, _ = self.fetch(error=error)
        self.assertEqual(result["status"], "access_rejected")
        self.assertEqual(result["http_status"], 403)
        self.assertTrue(result["upstream_response_received"])
        self.assertEqual(result["body_read_error"], {"type": "IncompleteRead"})
        self.assertEqual((self.output / "error-response.bin").read_bytes(), b"first partial-re")
        self.assertEqual(result["response"]["bytes"], 16)
        self.assertFalse(result["response"]["complete"])
        self.assertEqual(json.loads((self.output / "result.json").read_text()), result)

    def test_success_body_transport_error_saves_result_without_claiming_complete_response(self):
        response = FakeResponse()
        response.read = Mock(side_effect=http.client.IncompleteRead(b"bounded-prefix" * 100, 2000))
        with patch.object(entry, "MAX_RESPONSE_BYTES", 8):
            result, _ = self.fetch(response)
        self.assertEqual(result["status"], "response_read_error")
        self.assertEqual(result["http_status"], 200)
        self.assertTrue(result["upstream_response_received"])
        self.assertEqual(result["body_read_error"], {"type": "IncompleteRead"})
        self.assertEqual((self.output / "response-prefix.bin").read_bytes(), b"bounded-")
        self.assertFalse(result["response"]["complete"])
        self.assertEqual(json.loads((self.output / "result.json").read_text()), result)

    def test_tls_certificate_failure_is_recorded_without_insecure_retry(self):
        reason = ssl.SSLCertVerificationError("synthetic certificate rejection")
        result, _ = self.fetch(error=urllib.error.URLError(reason))
        self.assertEqual(result["status"], "network_error")
        self.assertEqual(result["network_error_type"], "SSLCertVerificationError")
        self.assertTrue(result["constraints"]["tls_verification"])
        self.assertFalse(result["upstream_response_received"])

    def test_opener_keeps_verified_tls_no_redirect_auth_or_cookie_handlers(self):
        real_context = ssl.create_default_context()
        with patch.object(entry.ssl, "create_default_context", return_value=real_context):
            opener = entry.build_opener()
        https_handlers = [handler for handler in opener.handlers
                          if isinstance(handler, urllib.request.HTTPSHandler)]
        self.assertEqual(len(https_handlers), 1)
        self.assertIs(https_handlers[0]._context, real_context)
        self.assertEqual(real_context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(real_context.check_hostname)
        redirect_handlers = [handler for handler in opener.handlers
                             if isinstance(handler, urllib.request.HTTPRedirectHandler)]
        self.assertEqual(len(redirect_handlers), 1)
        self.assertIsInstance(redirect_handlers[0], entry.NoRedirect)
        self.assertIsNone(redirect_handlers[0].redirect_request(
            entry.build_request(), None, 302, "synthetic", {}, "https://other.invalid"))
        self.assertFalse(any(isinstance(handler, urllib.request.HTTPCookieProcessor)
                             for handler in opener.handlers))
        self.assertFalse(any(isinstance(handler, urllib.request.AbstractBasicAuthHandler)
                             for handler in opener.handlers))

    def test_cli_reports_status_and_hash_but_never_private_response(self):
        private_body = b"credential-like-private-response-that-must-not-be-printed"
        opener = Mock()
        opener.open.return_value = FakeResponse(private_body)
        output = io.StringIO()
        with patch.object(entry, "build_opener", return_value=opener), redirect_stdout(output):
            code = entry.main([str(self.apk), "--output", str(self.output)])
        self.assertEqual(code, 0)
        self.assertIn("Status: received", output.getvalue())
        self.assertIn(hashlib.sha256(private_body).hexdigest(), output.getvalue())
        self.assertNotIn(private_body.decode(), output.getvalue())

    def test_concurrent_response_file_is_preserved(self):
        opener = Mock()

        def concurrent_writer(request, timeout):
            (self.output / "response.bin").write_bytes(b"concurrent user output")
            return FakeResponse(b"new response")

        opener.open.side_effect = concurrent_writer
        with self.assertRaisesRegex(entry.FetchError, "FileExistsError"):
            entry.fetch_game_entry(self.apk, self.output, opener=opener)
        self.assertEqual((self.output / "response.bin").read_bytes(), b"concurrent user output")
        self.assertEqual(opener.open.call_count, 1)


if __name__ == "__main__":
    unittest.main()
