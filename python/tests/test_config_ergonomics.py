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
        assert tjor_policy.evaluate(pol, "https://example.test/", "GET").allowed
        assert tjor_policy.evaluate(pol, "https://github.com/", "GET").allowed

    def test_add_creates_hosts_when_absent(self, tmp_path):
        p = tmp_path / "policy.toml"
        p.write_text('mode = "strict-allow"\n')
        tjor_policy_edit.add_hosts(str(p), ["a.test"])
        pol = tjor_policy.load_policy(str(p))
        assert pol.valid and tjor_policy.evaluate(pol, "https://a.test/", "GET").allowed

    def test_add_never_lands_in_a_restrict_rule(self, tmp_path):
        # [hosts] has only `block`, and a [[methods.restrict]] with its own
        # `allow` follows: the host must land in a NEW hosts.allow, and the
        # restrict rule must be untouched (openspec policy-ergonomics scenario).
        p = tmp_path / "policy.toml"
        p.write_text(
            'mode = "strict-allow"\n\n[hosts]\nblock = ["bad.test"]\n\n'
            '[[methods.restrict]]\nhost = "api.test"\nallow = ["GET"]\n'
        )
        tjor_policy_edit.add_hosts(str(p), ["that.host"])
        pol = tjor_policy.load_policy(str(p))
        assert pol.valid, pol.errors
        assert "that.host" in pol.host_allow
        assert pol.method_restrict == [("api.test", frozenset({"GET"}))]
        assert tjor_policy.evaluate(pol, "https://that.host/", "GET").allowed
        assert tjor_policy.evaluate(pol, "https://that.host/", "POST").allowed    # the restriction is api.test's

    def test_add_into_existing_allow_with_restrict_after(self, tmp_path):
        p = tmp_path / "policy.toml"
        p.write_text(
            'mode = "strict-allow"\n[hosts]\nallow = [\n  "a.test",\n]\n'
            '[[methods.restrict]]\nhost = "a.test"\nallow = ["GET"]\n'
        )
        tjor_policy_edit.add_hosts(str(p), ["b.test"])
        pol = tjor_policy.load_policy(str(p))
        assert pol.valid and set(pol.host_allow) == {"a.test", "b.test"}
        assert pol.method_restrict == [("a.test", frozenset({"GET"}))]

    def test_crlf_file_keeps_one_hosts_table(self, tmp_path):
        # Windows line endings: `[hosts]\r` must still be recognised as the
        # table (else a second one is appended, a TOML error) and the file
        # keeps its own line endings.
        p = tmp_path / "policy.toml"
        p.write_bytes(b'mode = "strict-allow"\r\n\r\n[hosts]  # the table\r\nallow = [\r\n  "a.test",\r\n]\r\n')
        tjor_policy_edit.add_hosts(str(p), ["b.test"])
        raw = p.read_bytes()
        assert raw.count(b"[hosts]") == 1 and b"\n" not in raw.replace(b"\r\n", b"")
        pol = tjor_policy.load_policy(str(p))
        assert pol.valid and set(pol.host_allow) == {"a.test", "b.test"}
        q = tmp_path / "bare.toml"
        q.write_bytes(b'mode = "strict-allow"\r\n[hosts]\r\nblock = ["x.test"]\r\n')
        tjor_policy_edit.add_hosts(str(q), ["c.test"])
        pol = tjor_policy.load_policy(str(q))
        assert pol.valid and pol.host_allow == ["c.test"] and q.read_bytes().count(b"[hosts]") == 1

    def test_crlf_file_without_a_hosts_table_gains_one_in_its_own_endings(self, tmp_path):
        p = tmp_path / "policy.toml"
        p.write_bytes(b'mode = "strict-allow"\r\n')
        tjor_policy_edit.add_hosts(str(p), ["a.test"])
        raw = p.read_bytes()
        assert b"\n" not in raw.replace(b"\r\n", b"") and raw.count(b"[hosts]") == 1
        pol = tjor_policy.load_policy(str(p))
        assert pol.valid and pol.host_allow == ["a.test"]

    def test_mixed_line_endings_stay_a_valid_policy(self, tmp_path):
        # TOML accepts LF and CRLF side by side; the insert follows the CRLF
        # convention when any is present, and the result parses.
        p = tmp_path / "policy.toml"
        p.write_bytes(b'mode = "strict-allow"\n[hosts]\r\nallow = [\n  "a.test",\r\n]\n')
        tjor_policy_edit.add_hosts(str(p), ["b.test"])
        pol = tjor_policy.load_policy(str(p))
        assert pol.valid, pol.errors
        assert set(pol.host_allow) == {"a.test", "b.test"} and p.read_bytes().count(b"[hosts]") == 1

    def test_indented_next_table_ends_the_hosts_body(self, tmp_path):
        # TOML allows an indented table header; the body of [hosts] ends there
        # too, so the restrict rule's `allow` is never the insertion point.
        p = tmp_path / "policy.toml"
        p.write_text(
            'mode = "strict-allow"\n[hosts]\nblock = ["bad.test"]\n\n'
            '  [[methods.restrict]]\n  host = "api.test"\n  allow = ["GET"]\n'
        )
        tjor_policy_edit.add_hosts(str(p), ["that.host"])
        pol = tjor_policy.load_policy(str(p))
        assert pol.valid, pol.errors
        assert pol.host_allow == ["that.host"] and pol.method_restrict == [("api.test", frozenset({"GET"}))]

    def test_table_header_must_be_a_whole_line(self):
        # The next-table search is anchored on a whole header line: an array
        # continuation line or a key cannot end the [hosts] body early.
        nt = tjor_policy_edit._NEXT_TABLE
        assert nt.search("\n[paths]\n") and nt.search("\n  [[methods.restrict]]  # c\n") and nt.search("\n[hosts]\r\n")
        assert not nt.search('\n["a.test"],\n') and not nt.search("\n[x = 1\n") and not nt.search("\nallow = [\n")

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
        assert not tjor_policy.evaluate(pol, "https://real.test/", "GET").allowed
