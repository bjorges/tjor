"""Trust store, trust-gated repo config layer, and policy-edit (#22/#23)."""

import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tjor_cfg
import tjor_policy
import tjor_policy_edit
import tjor_trust


class TestTrustStore:
    def test_untrusted_then_approve_then_edit(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TJOR_TRUST_STORE", str(tmp_path / "trusted.toml"))
        f = tmp_path / "policy.toml"
        f.write_text('mode = "strict-allow"\n')
        assert not tjor_trust.is_trusted(f)
        tjor_trust.approve(f)
        assert tjor_trust.is_trusted(f)
        f.write_text('mode = "default-allow"\n')       # edit revokes trust
        assert not tjor_trust.is_trusted(f)

    def test_store_is_0600(self, tmp_path, monkeypatch):
        store = tmp_path / "trusted.toml"
        monkeypatch.setenv("TJOR_TRUST_STORE", str(store))
        f = tmp_path / "c.toml"; f.write_text("x = 1\n")
        tjor_trust.approve(f)
        assert oct(store.stat().st_mode)[-3:] == "600"

    def test_missing_file_untrusted(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TJOR_TRUST_STORE", str(tmp_path / "t.toml"))
        assert not tjor_trust.is_trusted(tmp_path / "nope.toml")


class TestRepoConfigLayer:
    def setup_repo(self, tmp_path, monkeypatch, port=7777):
        monkeypatch.setenv("TJOR_TRUST_STORE", str(tmp_path / "trusted.toml"))
        monkeypatch.setenv("TJOR_USER_CONFIG", str(tmp_path / "nouser.toml"))
        repo = tmp_path / "repo"; (repo / ".tjor").mkdir(parents=True)
        (repo / ".tjor" / "config.toml").write_text(f"[proxy]\nport = {port}\n")
        monkeypatch.setenv("TJOR_REPO_ROOT", str(repo))
        importlib.reload(tjor_cfg)
        return repo

    def test_untrusted_repo_config_ignored(self, tmp_path, monkeypatch, capsys):
        self.setup_repo(tmp_path, monkeypatch)
        cfg = tjor_cfg.effective()
        assert tjor_cfg.get(cfg, "proxy.port") == 8080          # default, not the repo's 7777
        assert "NOT trusted" in capsys.readouterr().err

    def test_trusted_repo_config_layers(self, tmp_path, monkeypatch):
        repo = self.setup_repo(tmp_path, monkeypatch)
        tjor_trust.approve(repo / ".tjor" / "config.toml")
        cfg = tjor_cfg.effective()
        assert tjor_cfg.get(cfg, "proxy.port") == 7777
        assert tjor_cfg.get(cfg, "versions.opencode")           # defaults still present

    def teardown_method(self):
        importlib.reload(tjor_cfg)


class TestPolicyEdit:
    def test_add_host_preserves_and_allows(self, tmp_path):
        p = tmp_path / "policy.toml"
        p.write_text(
            'mode = "strict-allow"\n\n[hosts]\nallow = [\n  "github.com",  # keep this comment\n]\n'
        )
        tjor_policy_edit.add_hosts(str(p), ["example.test"])
        text = p.read_text()
        assert "keep this comment" in text                       # comment preserved
        pol = tjor_policy.load_policy(str(p))
        assert pol.valid
        assert tjor_policy.evaluate(pol, "https://example.test/").allowed
        assert tjor_policy.evaluate(pol, "https://github.com/").allowed

    def test_add_creates_hosts_when_absent(self, tmp_path):
        p = tmp_path / "policy.toml"
        p.write_text('mode = "strict-allow"\n')
        tjor_policy_edit.add_hosts(str(p), ["a.test"])
        pol = tjor_policy.load_policy(str(p))
        assert pol.valid and tjor_policy.evaluate(pol, "https://a.test/").allowed

    def test_refuses_to_write_invalid(self, tmp_path):
        p = tmp_path / "policy.toml"
        p.write_text("mode = [broken\n")                          # unparseable
        with pytest.raises(SystemExit):
            tjor_policy_edit.add_hosts(str(p), ["a.test"])

    def test_refuses_silent_noop_into_multiline_string(self, tmp_path):
        # A triple-quoted string that CONTAINS "[hosts]\nallow = [" precedes the
        # real table. The regex would insert into the string → valid TOML whose
        # real allow-list is untouched. Must fail loudly, not silently no-op.
        p = tmp_path / "policy.toml"
        p.write_text(
            'note = """\n'
            'example:\n'
            '[hosts]\n'
            'allow = [\n'
            '  "doc.example",\n'
            ']\n'
            '"""\n\n'
            'mode = "strict-allow"\n\n'
            '[hosts]\n'
            'allow = [\n  "github.com",\n]\n'
        )
        with pytest.raises(SystemExit):
            tjor_policy_edit.add_hosts(str(p), ["real.test"])
        # and the real allow-list was NOT changed by the refused write
        pol = tjor_policy.load_policy(str(p))
        assert not tjor_policy.evaluate(pol, "https://real.test/").allowed
