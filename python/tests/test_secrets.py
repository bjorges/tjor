"""Discovered-secret detector (#6): each known shape redacts, and NON-secrets
(UUIDs, git SHAs, base64, prose) are left untouched — the false-positive stance
is the point."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tjor_secrets as s


class TestRedactHits:
    @pytest.mark.parametrize("secret,kind", [
        ("AKIAABCDEFGHIJKLMNOP", "aws-access-key-id"),
        ("ASIAABCDEFGHIJKLMNOP", "aws-access-key-id"),
        ("ghp_" + "a" * 36, "github-token"),
        ("gho_" + "b" * 40, "github-token"),
        ("github_pat_" + "A1b2c3d4e5f6g7h8i9j0k1", "github-pat"),
        ("xoxb-1234567890-abcdefghijkl", "slack-token"),
        ("AIza" + "A" * 35, "google-api-key"),
    ])
    def test_each_shape_redacted(self, secret, kind):
        out = s.redact(f"before {secret} after")
        assert secret not in out
        assert f"[redacted:{kind}]" in out
        assert out.startswith("before ") and out.endswith(" after")
        assert s.contains_secret(secret) is True

    def test_pem_private_key_block_fully_redacted(self):
        pem = ("-----BEGIN OPENSSH PRIVATE KEY-----\n"
               "b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAAB\n"
               "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789+/=\n"
               "-----END OPENSSH PRIVATE KEY-----")
        out = s.redact(f"key:\n{pem}\ntail")
        assert "b3BlbnNz" not in out and "BEGIN OPENSSH" not in out
        assert "[redacted:private-key]" in out
        assert out.startswith("key:\n") and out.endswith("\ntail")

    def test_multiple_secrets_all_redacted(self):
        text = f"a AKIAABCDEFGHIJKLMNOP b {'ghp_' + 'z'*36} c"
        out = s.redact(text)
        assert "AKIA" not in out and "ghp_" not in out
        assert out.count("[redacted:") == 2


class TestNoFalsePositives:
    @pytest.mark.parametrize("benign", [
        "123e4567-e89b-12d3-a456-426614174000",          # UUID
        "da39a3ee5e6b4b0d3255bfef95601890afd80709",       # 40-hex git SHA
        "dGhpcyBpcyBqdXN0IGJhc2U2NCBub3QgYSBzZWNyZXQ=",   # plain base64, not a known shape
        "the quick brown fox jumps over the lazy dog",     # prose
        "api.github.com",                                  # a hostname
        "AKIAshort",                                        # AKIA but too short to match
        "ghp_tooshort",                                     # gh prefix but under length
    ])
    def test_benign_unchanged(self, benign):
        assert s.redact(benign) == benign
        assert s.contains_secret(benign) is False

    def test_empty_and_none_safe(self):
        assert s.redact("") == ""
        assert s.contains_secret("") is False


class TestCli:
    def test_redact_filter(self, capsys, monkeypatch):
        monkeypatch.setattr("sys.stdin", __import__("io").StringIO("x AKIAABCDEFGHIJKLMNOP y"))
        assert s._main(["tjor_secrets.py", "redact"]) == 0
        assert "[redacted:aws-access-key-id]" in capsys.readouterr().out

    def test_usage_without_subcommand(self):
        with pytest.raises(SystemExit):
            s._main(["tjor_secrets.py"])
