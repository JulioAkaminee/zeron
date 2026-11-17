#!/usr/bin/env python3
"""Credential gating and cleanup, without Apple credentials or a Mac runner."""
import base64
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "intel-macos-signing.sh"
SECRETS = {
    "MACOS_CERT_P12": base64.b64encode(b"test certificate").decode(),
    "MACOS_CERT_PASSWORD": "test-export-password",
    "AC_API_KEY_P8": "test-private-key",
    "AC_API_KEY_ID": "TESTKEYID",
    "AC_API_ISSUER_ID": "test-issuer",
}
MOCK = r'''#!/usr/bin/env python3
import json, os, pathlib, sys
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ["SIGNING_TEST_LOG"], "a") as log:
    log.write(json.dumps([name, *args]) + "\n")
if name == "security":
    if args[0] == "list-keychains" and "-s" not in args:
        print('    "/tmp/test user/login.keychain-db"')
    elif args[0] == "create-keychain":
        pathlib.Path(args[-1]).touch()
    elif args[0] == "delete-keychain":
        pathlib.Path(args[-1]).unlink()
    elif args[0] == "find-identity":
        if os.environ.get("SIGNING_TEST_BAD_ID"):
            print("0 valid identities found")
        else:
            print('  1) ' + 'A' * 40 + ' "Developer ID Application: Test (TESTTEAM)"')
elif name == "openssl":
    if args[0] == "rand":
        print("b" * 64)
elif name == "xcrun":
    if os.environ.get("SIGNING_TEST_BAD_NOTARY"):
        sys.exit(1)
    print('{}')
'''


class SigningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="intel-signing-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        for command in ("security", "openssl", "xcrun"):
            path = self.bin / command
            path.write_text(MOCK)
            path.chmod(0o755)
        self.env = {key: value for key, value in os.environ.items() if key not in SECRETS}
        self.env.update(
            PATH=str(self.bin) + os.pathsep + os.environ["PATH"],
            RUNNER_TEMP=str(self.root),
            GITHUB_ENV=str(self.root / "github-env"),
            SIGNING_TEST_LOG=str(self.root / "commands.jsonl"),
            REQUIRE_SIGNING="false",
        )

    def run_script(self, action="prepare", **env):
        return subprocess.run(
            ["bash", str(SCRIPT), action], env={**self.env, **env},
            text=True, capture_output=True,
        )

    def commands(self):
        path = self.root / "commands.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def github_env(self):
        path = self.root / "github-env"
        return path.read_text() if path.exists() else ""

    def assert_cleaned(self):
        result = self.run_script("cleanup")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.root / "zeron-intel-signing").exists())
        self.assertIn(["security", "list-keychains", "-d", "user", "-s",
                       "/tmp/test user/login.keychain-db"], self.commands())

    def test_no_credentials_preserves_ad_hoc_without_touching_keychains(self):
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.github_env(), "SIGNING_ENABLED=false\n")
        self.assertEqual(self.commands(), [])

    def test_required_signing_fails_without_credentials(self):
        result = self.run_script(REQUIRE_SIGNING="true")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Missing: MACOS_CERT_P12", result.stderr)
        self.assertEqual(self.commands(), [])

    def test_partial_credentials_fail_before_import(self):
        result = self.run_script(MACOS_CERT_P12=SECRETS["MACOS_CERT_P12"])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("MACOS_CERT_PASSWORD", result.stderr)
        self.assertEqual(self.commands(), [])
        self.assertNotIn(SECRETS["MACOS_CERT_P12"], result.stderr)

    def test_complete_credentials_authenticate_and_cleanup_restores_keychains(self):
        result = self.run_script(**SECRETS)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SIGNING_ENABLED=true", self.github_env())
        self.assertIn("CODESIGN_IDENTITY=" + "A" * 40, self.github_env())
        self.assertTrue(any(cmd[:3] == ["xcrun", "notarytool", "history"] for cmd in self.commands()))
        key = self.root / "zeron-intel-signing/notary.p8"
        self.assertEqual(key.stat().st_mode & 0o777, 0o600)
        self.assertNotIn(SECRETS["AC_API_KEY_P8"], result.stdout + result.stderr)
        self.assertNotIn(SECRETS["MACOS_CERT_PASSWORD"], result.stdout + result.stderr)
        self.assert_cleaned()

    def test_wrong_certificate_is_not_marked_signed_and_can_be_cleaned(self):
        result = self.run_script(**SECRETS, SIGNING_TEST_BAD_ID="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Developer ID Application", result.stderr)
        self.assertNotIn("SIGNING_ENABLED=true", self.github_env())
        self.assert_cleaned()

    def test_notary_authentication_failure_is_not_marked_signed(self):
        result = self.run_script(**SECRETS, SIGNING_TEST_BAD_NOTARY="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("SIGNING_ENABLED=true", self.github_env())
        self.assert_cleaned()

    def test_cleanup_before_preparation_is_harmless(self):
        result = self.run_script("cleanup")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.commands(), [])


if __name__ == "__main__":
    unittest.main()
