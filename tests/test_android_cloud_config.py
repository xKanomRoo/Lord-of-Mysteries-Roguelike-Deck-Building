"""Keep backend secrets and account credentials out of distributable APKs."""
import base64
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from android_cloud_config import validate_config


class AndroidCloudConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.project = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def write(self, key="sb_publishable_example_public_value", **extra):
        config = {"base_url": "https://example.supabase.co", "public_key": key}
        config.update(extra)
        (self.project / "cloud-config.json").write_text(json.dumps(config))

    def test_offline_and_publishable_config(self):
        self.assertFalse(validate_config(self.project))
        self.write()
        self.assertTrue(validate_config(self.project))

    def test_legacy_anon_accepted_service_role_rejected(self):
        for role, accepted in (("anon", True), ("service_role", False)):
            payload = base64.urlsafe_b64encode(json.dumps({"role": role}).encode()).decode().rstrip("=")
            self.write("eyJhbGciOiJIUzI1NiJ9." + payload + ".test_signature")
            if accepted:
                self.assertTrue(validate_config(self.project))
            else:
                with self.assertRaises(ValueError):
                    validate_config(self.project)

    def test_secret_key_and_extra_credentials_rejected(self):
        self.write("sb_secret_private_key_sentinel_value")
        with self.assertRaises(ValueError):
            validate_config(self.project)
        self.write(password="private_account_password")
        with self.assertRaises(ValueError):
            validate_config(self.project)

    def test_plain_http_userinfo_path_and_oversize_rejected(self):
        for url in ("http://example.supabase.co", "https://user@example.supabase.co", "https://example.supabase.co/auth"):
            self.write(base_url=url)
            with self.assertRaises(ValueError):
                validate_config(self.project)
        (self.project / "cloud-config.json").write_text(" " * 4097)
        with self.assertRaises(ValueError):
            validate_config(self.project)

    def test_cli_rejection_never_prints_supplied_secret(self):
        marker = "sb_secret_do_not_print_0123456789"
        self.write(marker)
        script = Path(__file__).resolve().parents[1] / "tools/android_cloud_config.py"
        result = subprocess.run([sys.executable, str(script), "--project", str(self.project)], text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(marker, result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_duplicate_public_key_cannot_hide_backend_secret_in_apk(self):
        (self.project / "cloud-config.json").write_text(
            '{"base_url":"https://example.supabase.co",'
            '"public_key":"sb_secret_private_original_value",'
            '"public_key":"sb_publishable_accepted_public_value"}')
        with self.assertRaises(ValueError):
            validate_config(self.project)


if __name__ == "__main__":
    unittest.main()
