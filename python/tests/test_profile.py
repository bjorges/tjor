"""Agent-profile host-side staging (#29): the allow-list filter is the
credential-safety guarantee, so these tests pin exactly what is and is NOT
staged — definitions in, auth/secrets/unknowns out, escaping symlinks refused."""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tjor_profile


def _write(p: Path, text="x"):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


class TestStageAllowList:
    def test_definitions_staged(self, tmp_path):
        src = tmp_path / "profile"
        _write(src / "agent" / "reviewer.md", "review carefully")
        _write(src / "command" / "deploy.md")
        _write(src / "skills" / "k8s" / "SKILL.md")
        dest = tmp_path / "staged"
        staged = tjor_profile.stage(src, dest)
        assert "agent/reviewer.md" in staged
        assert "command/deploy.md" in staged
        assert "skills/k8s/SKILL.md" in staged
        assert (dest / "agent" / "reviewer.md").read_text() == "review carefully"

    def test_credentials_and_unknowns_not_staged(self, tmp_path):
        src = tmp_path / "profile"
        _write(src / "agent" / "reviewer.md")
        # things that must NEVER be staged:
        _write(src / "auth.json", '{"token":"SECRET"}')
        _write(src / ".credentials.json", "SECRET")
        _write(src / "opencode.json", '{"apiKey":"SECRET"}')
        _write(src / "secrets" / "key.pem", "SECRET")   # non-allow-listed dir
        _write(src / "agents.bak" / "old.md")            # near-miss dir name
        dest = tmp_path / "staged"
        staged = tjor_profile.stage(src, dest)
        assert staged == ["agent/reviewer.md"]
        # belt: no secret content anywhere under dest
        blob = ""
        for root, _, files in os.walk(dest):
            for f in files:
                blob += (Path(root) / f).read_text()
        assert "SECRET" not in blob

    def test_symlinked_top_level_dir_refused(self, tmp_path):
        # agent -> /etc  must not expose /etc
        src = tmp_path / "profile"
        src.mkdir()
        outside = tmp_path / "outside"
        _write(outside / "passwd", "root:x:0:0")
        (src / "agent").symlink_to(outside)
        staged = tjor_profile.stage(src, tmp_path / "staged")
        assert staged == []

    def test_escaping_symlinked_file_not_followed(self, tmp_path):
        src = tmp_path / "profile"
        _write(src / "agent" / "real.md", "ok")
        secret = tmp_path / "secret.pem"
        _write(secret, "PRIVATE KEY")
        (src / "agent" / "leak.md").symlink_to(secret)   # escapes source
        dest = tmp_path / "staged"
        staged = tjor_profile.stage(src, dest)
        assert staged == ["agent/real.md"]
        assert not (dest / "agent" / "leak.md").exists()

    def test_internal_symlink_allowed(self, tmp_path):
        # a symlink to another file WITHIN the source is fine (user's own content)
        src = tmp_path / "profile"
        _write(src / "agent" / "base.md", "shared body")
        (src / "agent" / "alias.md").symlink_to(src / "agent" / "base.md")
        dest = tmp_path / "staged"
        staged = tjor_profile.stage(src, dest)
        assert "agent/alias.md" in staged
        assert (dest / "agent" / "alias.md").read_text() == "shared body"

    def test_dest_cleared_between_runs(self, tmp_path):
        src1 = tmp_path / "p1"; _write(src1 / "agent" / "a.md")
        src2 = tmp_path / "p2"; _write(src2 / "agent" / "b.md")
        dest = tmp_path / "staged"
        tjor_profile.stage(src1, dest)
        tjor_profile.stage(src2, dest)
        assert (dest / "agent" / "b.md").exists()
        assert not (dest / "agent" / "a.md").exists()   # stale profile gone

    def test_empty_or_no_definitions(self, tmp_path):
        src = tmp_path / "profile"
        _write(src / "README.md")   # nothing allow-listed
        staged = tjor_profile.stage(src, tmp_path / "staged")
        assert staged == []

    def test_credentials_NESTED_in_definition_dir_not_staged(self, tmp_path):
        # The structural allow-list alone would stage these (they're inside an
        # allowed dir); the credential-filename denylist must catch them.
        src = tmp_path / "profile"
        _write(src / "agent" / "reviewer.md", "def")
        _write(src / "agent" / "auth.json", "SECRET")
        _write(src / "agent" / "keys" / "id_rsa", "SECRET")
        _write(src / "skills" / "k8s" / "client.pem", "SECRET")
        _write(src / "command" / ".env", "TOKEN=SECRET")
        _write(src / "agents" / "svc.p12", "SECRET")
        dest = tmp_path / "staged"
        staged = tjor_profile.stage(src, dest)
        assert staged == ["agent/reviewer.md"]
        blob = ""
        for root, _, files in os.walk(dest):
            for f in files:
                blob += (Path(root) / f).read_text()
        assert "SECRET" not in blob

    def test_definition_named_like_secret_still_staged(self, tmp_path):
        # No false positives: the denylist is exact names + key/cert extensions,
        # so a legit definition whose name merely contains "secret"/"auth" and
        # ends in .md is NOT dropped.
        src = tmp_path / "profile"
        _write(src / "agent" / "secret-scanner.md", "def")
        _write(src / "command" / "rotate-credentials.md", "def")
        staged = tjor_profile.stage(src, tmp_path / "staged")
        assert set(staged) == {"agent/secret-scanner.md", "command/rotate-credentials.md"}


class TestCli:
    def test_stage_prints_relative_paths(self, tmp_path, capsys):
        src = tmp_path / "profile"; _write(src / "agent" / "r.md")
        dest = tmp_path / "staged"
        tjor_profile._main(["tjor_profile.py", "stage", str(src), str(dest)])
        assert capsys.readouterr().out.strip() == "agent/r.md"

    def test_bad_usage_exits(self):
        with pytest.raises(SystemExit):
            tjor_profile._main(["tjor_profile.py", "bogus"])
