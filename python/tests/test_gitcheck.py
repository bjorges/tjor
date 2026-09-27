"""Git-metadata tamper detection (#72): every planted pattern is a finding;
everyday git churn is not."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tjor_gitcheck as gc


def _git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


def _repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q")
    _git(path, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "--allow-empty", "-m", "base")
    return path


class TestPredicate:
    @pytest.mark.parametrize("key,value", [
        ("core.hooksPath", ".h"), ("core.fsmonitor", "x"), ("core.sshCommand", "ssh"),
        ("core.pager", "less"), ("core.editor", "vi"), ("core.askPass", "x"),
        ("gpg.program", "gpg"), ("gpg.x509.program", "s"), ("filter.lfs.clean", "c"),
        ("filter.lfs.process", "p"), ("diff.foo.textconv", "cat"), ("diff.foo.command", "x"),
        ("merge.m.driver", "d"), ("mergetool.t.cmd", "c"), ("difftool.t.cmd", "c"),
        ("credential.helper", "store"), ("credential.https://x.helper", "h"),
        ("remote.origin.uploadpack", "u"), ("remote.origin.receivepack", "r"),
        ("remote.origin.proxy", "p"), ("remote.origin.vcs", "hg"),
        ("url.https://evil/.insteadOf", "https://github.com/"), ("include.path", "/x"),
        ("includeIf.gitdir:/x.path", "/y"), ("safe.directory", "*"), ("extensions.worktreeConfig", "true"),
        ("pager.log", "less -R"), ("alias.st", "!sh -c evil"), ("submodule.s.update", "!cmd"),
        ("uploadpack.packObjectsHook", "x"), ("sendemail.sendmailCmd", "x"),
        # v0.21.1 review: every documented key has a case; the missing ones added
        ("core.gitProxy", "p"), ("core.alternateRefsCommand", "c"), ("core.attributesFile", "f"),
        ("sequence.editor", "e"), ("diff.external", "d"), ("interactive.diffFilter", "f"),
        ("browser.firefox.cmd", "ff"), ("url.https://evil/.pushInsteadOf", "https://github.com/"),
        ("sendemail.smtpServerCommand", "cmd"), ("sendemail.work.sendmailCmd", "cmd"),
        ("sendemail.smtpServer", "/usr/sbin/sendmail"), ("imap.tunnel", "ssh x"),
        ("protocol.allow", "always"), ("protocol.ext.allow", "user"), ("init.templateDir", "/t"),
        ("trailer.sign.command", "c"), ("trailer.sign.cmd", "c"), ("guitool.x.cmd", "c"),
        # ext::/fd:: transports execute on every fetch/pull/push/clone
        ("remote.origin.url", "ext::sh -c touch% /tmp/pwned"), ("remote.origin.pushUrl", "EXT::cmd"),
        ("submodule.s.url", "ext::cmd"), ("remote.origin.url", "fd::3"),
    ])
    def test_dangerous(self, key, value):
        assert gc.is_dangerous(key, value)

    @pytest.mark.parametrize("key,value", [
        ("branch.main.remote", "origin"), ("branch.main.merge", "refs/heads/main"),
        ("remote.origin.url", "https://github.com/x/y"), ("remote.origin.fetch", "+refs/*:refs/*"),
        ("remote.origin.push", "HEAD"), ("user.name", "t"), ("user.email", "t@x"),
        ("push.autoSetupRemote", "true"), ("core.bare", "false"), ("core.filemode", "true"),
        ("alias.st", "status"), ("submodule.s.update", "checkout"), ("pull.rebase", "true"),
        ("remote.origin.url", "git@github.com:x/y.git"), ("remote.origin.pushUrl", "ssh://h/x"),
        ("submodule.s.url", "https://github.com/x/s"), ("sendemail.smtpServer", "smtp.example.com"),
        ("sendemail.smtpEncryption", "tls"), ("trailer.sign.key", "Signed-off-by"),
    ])
    def test_benign(self, key, value):
        assert not gc.is_dangerous(key, value)


class TestSnapshotAndDiff:
    def test_baseline_covers_every_root_and_nested(self, tmp_path):
        ws = _repo(tmp_path / "ws"); extra = _repo(tmp_path / "extra"); _repo(extra / "vendor" / "nested")
        snap = gc.snapshot([str(ws), str(extra)])
        wts = {r["worktree"] for r in snap["repos"]}
        assert wts == {str(ws), str(extra), str(extra / "vendor" / "nested")}
        assert str(extra / "vendor" / "nested") in next(r for r in snap["repos"] if r["worktree"] == str(extra))["nested"]

    def test_planted_dangerous_key_reported_with_values(self, tmp_path):
        ws = _repo(tmp_path / "ws"); base = gc.snapshot([str(ws)])
        _git(ws, "config", "core.hooksPath", ".custom-hooks")
        f = gc.diff(base, gc.snapshot([str(ws)]))
        assert [x["kind"] for x in f] == ["dangerous-key"]
        assert f[0]["key"] == "core.hookspath" and f[0]["old"] is None and f[0]["new"] == [".custom-hooks"]

    def test_changed_and_removed_keys_reported(self, tmp_path):
        ws = _repo(tmp_path / "ws"); _git(ws, "config", "core.pager", "less"); base = gc.snapshot([str(ws)])
        _git(ws, "config", "core.pager", "evil"); f = gc.diff(base, gc.snapshot([str(ws)]))
        assert f and f[0]["old"] == ["less"] and f[0]["new"] == ["evil"]
        _git(ws, "config", "--unset", "core.pager"); f = gc.diff(base, gc.snapshot([str(ws)]))
        assert f and f[0]["new"] is None

    def test_push_u_shaped_writes_are_clean(self, tmp_path):
        ws = _repo(tmp_path / "ws"); base = gc.snapshot([str(ws)])
        _git(ws, "config", "remote.origin.url", "https://example.invalid/r")
        _git(ws, "config", "remote.origin.fetch", "+refs/heads/*:refs/remotes/origin/*")
        _git(ws, "config", "branch.main.remote", "origin")
        _git(ws, "config", "branch.main.merge", "refs/heads/main")
        _git(ws, "config", "user.name", "someone")
        assert gc.diff(base, gc.snapshot([str(ws)])) == []

    def test_ext_transport_remote_is_a_finding(self, tmp_path):
        """v0.21.1 review (Critical): `ext::` on a remote url runs a command on
        every fetch/pull/push/clone — it must never sit inside the "push -u is
        quiet" allowance."""
        ws = _repo(tmp_path / "ws"); base = gc.snapshot([str(ws)])
        _git(ws, "config", "remote.evil.url", "ext::sh -c touch% /tmp/pwned")
        f = gc.diff(base, gc.snapshot([str(ws)]))
        assert [(x["kind"], x["key"]) for x in f] == [("dangerous-key", "remote.evil.url")]

    def test_repeated_key_every_value_kept(self, tmp_path):
        """v0.21.1 review: a value slipped BETWEEN two legitimate occurrences of
        a repeatable key must not hide behind a last-value-wins dict."""
        ws = _repo(tmp_path / "ws")
        _git(ws, "config", "--add", "safe.directory", "/a"); _git(ws, "config", "--add", "safe.directory", "/b")
        base = gc.snapshot([str(ws)])
        assert base["repos"][0]["dangerous"]["safe.directory"] == ["/a", "/b"]
        cfg = ws / ".git" / "config"
        cfg.write_text(cfg.read_text().replace("directory = /b", "directory = /evil\n\tdirectory = /b"))
        f = gc.diff(base, gc.snapshot([str(ws)]))
        assert f and f[0]["key"] == "safe.directory" and f[0]["new"] == ["/a", "/evil", "/b"]

    def test_unparseable_config_is_a_finding(self, tmp_path):
        """v0.21.1 review (Critical): a config git cannot parse is UNKNOWN, not
        clean — fail closed, like the hooks path."""
        ws = _repo(tmp_path / "ws"); base = gc.snapshot([str(ws)])
        with open(ws / ".git" / "config", "a") as fh:
            fh.write("[core\n")
        cur = gc.snapshot([str(ws)])
        assert cur["repos"][0]["config_error"] and cur["repos"][0]["dangerous"] == {}
        f = gc.diff(base, cur)
        assert [x["kind"] for x in f] == ["config-unreadable"] and "UNKNOWN" in f[0]["detail"]
        # still a finding when it was ALREADY unreadable at baseline (says so)
        f2 = gc.diff(cur, gc.snapshot([str(ws)]))
        assert f2 and f2[0]["kind"] == "config-unreadable" and "already unreadable" in f2[0]["detail"]
        assert "could NOT see" in gc.render(f2[0])

    def test_bang_alias_reported_plain_alias_not(self, tmp_path):
        ws = _repo(tmp_path / "ws"); base = gc.snapshot([str(ws)])
        _git(ws, "config", "alias.st", "status")
        assert gc.diff(base, gc.snapshot([str(ws)])) == []
        _git(ws, "config", "alias.pwn", "!sh -c evil")
        assert [x["kind"] for x in gc.diff(base, gc.snapshot([str(ws)]))] == ["dangerous-key"]

    def test_include_added(self, tmp_path):
        ws = _repo(tmp_path / "ws"); base = gc.snapshot([str(ws)])
        _git(ws, "config", "include.path", "/tmp/evil.inc")
        kinds = sorted(x["kind"] for x in gc.diff(base, gc.snapshot([str(ws)])))
        assert kinds == ["dangerous-key", "include-added"]

    def test_symlinked_config(self, tmp_path):
        ws = _repo(tmp_path / "ws"); base = gc.snapshot([str(ws)])
        cfg = ws / ".git" / "config"; real = tmp_path / "elsewhere.cfg"; real.write_text(cfg.read_text())
        cfg.unlink(); cfg.symlink_to(real)
        assert "config-symlinked" in {x["kind"] for x in gc.diff(base, gc.snapshot([str(ws)]))}

    def test_worktree_pointer_and_commondir(self, tmp_path):
        main = _repo(tmp_path / "main"); wt = tmp_path / "wt"
        _git(main, "worktree", "add", "-q", str(wt))
        base = gc.snapshot([str(main), str(wt)])
        (wt / ".git").write_text("gitdir: /somewhere/else\n")
        f = gc.diff(base, gc.snapshot([str(main), str(wt)]))
        assert any(x["kind"] == "worktree-pointer" and x["repo"] == str(wt) for x in f)
        # re-target the linked worktree's commondir seen from the main repo
        (main / ".git" / "worktrees" / "wt" / "commondir").write_text("/evil/.git\n")
        f = gc.diff(base, gc.snapshot([str(main), str(wt)]))
        assert any(x["kind"] == "worktree-changed" and x["key"] == "wt" for x in f)

    def test_hooks_dir_turned_symlink(self, tmp_path):
        """v0.21.0 review: a hooks dir replaced by a symlink (the launcher
        refuses to mask through it) is itself a finding at the next check."""
        ws = _repo(tmp_path / "ws"); base = gc.snapshot([str(ws)])
        hooks = ws / ".git" / "hooks"; real = tmp_path / "elsewhere"; real.mkdir()
        import shutil; shutil.rmtree(hooks, ignore_errors=True); hooks.symlink_to(real)
        f = gc.diff(base, gc.snapshot([str(ws)]))
        assert any(x["kind"] == "hooks-symlinked" and x["new"] == str(real) for x in f)

    def test_gitdir_turned_symlink(self, tmp_path):
        ws = _repo(tmp_path / "ws"); base = gc.snapshot([str(ws)])
        real = tmp_path / "real-git"; (ws / ".git").rename(real); (ws / ".git").symlink_to(real)
        assert any(x["kind"] == "gitdir-symlinked" for x in gc.diff(base, gc.snapshot([str(ws)])))

    def test_hook_added(self, tmp_path):
        ws = _repo(tmp_path / "ws"); base = gc.snapshot([str(ws)])
        (ws / ".git" / "hooks").mkdir(exist_ok=True); (ws / ".git" / "hooks" / "pre-commit").write_text("#!/bin/sh\nevil\n")
        assert any(x["kind"] == "hook-changed" and x["key"] == "pre-commit" for x in gc.diff(base, gc.snapshot([str(ws)])))

    def test_nested_repo_planted(self, tmp_path):
        ws = _repo(tmp_path / "ws"); base = gc.snapshot([str(ws)])
        _repo(ws / "src")
        f = gc.diff(base, gc.snapshot([str(ws)]))
        assert any(x["kind"] == "nested-repo-added" and x["path"].endswith("/src") for x in f)

    def test_repo_added_under_plain_root(self, tmp_path):
        """A root that was not a repository at baseline gains one: nothing
        above it to report it as nested, so it is its own finding class."""
        plain = tmp_path / "plain"; plain.mkdir(); base = gc.snapshot([str(plain)])
        assert base["repos"] == []
        _repo(plain)
        assert [x["kind"] for x in gc.diff(base, gc.snapshot([str(plain)]))] == ["repo-added"]

    def test_depth_cap_recorded_and_new_truncation_is_a_finding(self, tmp_path):
        """v0.21.1 review (Critical): a walk cut by the depth cap is never
        silent — recorded in the snapshot (announced at launch) and a NEW
        truncation after the baseline is a finding. A repo planted right at
        the cap is still found; one below an already-truncated spot is the
        documented residual."""
        ws = _repo(tmp_path / "ws")
        base = gc.snapshot([str(ws)], max_depth=3)
        assert base["max_depth"] == 3 and base["incomplete"] == []
        deep = ws / "a" / "b" / "c" / "d"; deep.mkdir(parents=True)
        cur = gc.snapshot([str(ws)], max_depth=3)
        assert cur["incomplete"] == [{"path": str(ws / "a" / "b" / "c"), "reason": "depth-cap 3"}]
        f = gc.diff(base, cur)
        assert [x["kind"] for x in f] == ["discovery-incomplete"] and "UNCHECKED" in f[0]["detail"]
        assert gc.diff(cur, gc.snapshot([str(ws)], max_depth=3)) == []      # known at baseline: not re-reported
        _repo(ws / "a" / "b" / "c")                                          # at the cap: still discovered
        assert any(x["kind"] == "nested-repo-added" for x in gc.diff(cur, gc.snapshot([str(ws)], max_depth=3)))
        # the CLI announces the truncation on stderr before the count
        r = subprocess.run([sys.executable, str(Path(gc.__file__)), "snapshot", "--max-depth", "3", str(ws)], capture_output=True, text=True)
        lines = r.stderr.strip().splitlines()
        assert r.returncode == 0 and lines[-1] == "2" and "discovery incomplete under" in lines[0] and "depth-cap 3" in lines[0]

    def test_unreadable_directory_is_recorded(self, tmp_path):
        if os.geteuid() == 0:
            pytest.skip("root reads everything")
        ws = _repo(tmp_path / "ws"); base = gc.snapshot([str(ws)])
        locked = ws / "locked"; locked.mkdir(); locked.chmod(0)
        try:
            cur = gc.snapshot([str(ws)])
            assert any(e["path"] == str(locked) and e["reason"].startswith("unreadable") for e in cur["incomplete"])
            assert any(x["kind"] == "discovery-incomplete" for x in gc.diff(base, cur))
        finally:
            locked.chmod(0o755)

    def test_worktree_with_common_dir_outside_roots(self, tmp_path):
        """v0.21.0 review test gap: a linked worktree whose common dir lies
        OUTSIDE every root is baselined by its pointer and snapshots without
        error; re-pointing it is still a finding."""
        main = _repo(tmp_path / "outside" / "main"); wt = tmp_path / "roots" / "wt"; wt.parent.mkdir()
        _git(main, "worktree", "add", "-q", str(wt))
        base = gc.snapshot([str(wt)])
        rec = base["repos"][0]
        assert rec["worktree"] == str(wt) and rec["pointer"].startswith("gitdir:") and rec["config"] == str(main / ".git" / "config")
        assert gc.diff(base, gc.snapshot([str(wt)])) == []
        (wt / ".git").write_text("gitdir: /somewhere/else\n")
        assert any(x["kind"] == "worktree-pointer" for x in gc.diff(base, gc.snapshot([str(wt)])))

    def test_repo_missing(self, tmp_path):
        ws = _repo(tmp_path / "ws"); base = gc.snapshot([str(ws)])
        import shutil; shutil.rmtree(ws / ".git")
        assert [x["kind"] for x in gc.diff(base, gc.snapshot([str(ws)]))] == ["repo-missing"]

    def test_render_sanitizes(self, tmp_path):
        line = gc.render({"repo": "/r/\x1b[31mX", "kind": "dangerous-key", "key": "core.hookspath", "old": None, "new": "\x1b]0;x\x07"})
        assert "\x1b" not in line and "HOST git" in line

    def test_json_findings_sanitized_and_url_credentials_redacted(self):
        """v0.21.1 review: the JSON consumer gets the same protection as the
        terminal, and a credential embedded in a URL-shaped key never lands
        in scrollback, a log or a pipe."""
        f = [{"repo": "/r/\x1b[31mX", "kind": "dangerous-key", "key": "url.https://user:ghp_secret@host/.insteadof",
              "old": None, "new": ["https://u:p@h/\x07"]}]
        out = gc.sanitize_findings(f)
        text = json.dumps(out)
        assert "\\u001b" not in text and "\x1b" not in text and "ghp_secret" not in text and "u:p@" not in text
        assert "[redacted:url-credential]@host" in out[0]["key"] and out[0]["new"] == ["https://[redacted:url-credential]@h/^G"]
        assert "ghp_secret" not in gc.render(f[0])

    def test_token_binds_to_the_findings(self):
        a = [{"repo": "/r", "kind": "dangerous-key", "key": "core.hookspath", "old": None, "new": ["x"]}]
        b = [{"repo": "/r", "kind": "dangerous-key", "key": "core.hookspath", "old": None, "new": ["y"]}]
        assert gc.token([]) == "" and len(gc.token(a)) == 12 and gc.token(a) == gc.token(list(a)) and gc.token(a) != gc.token(b)

    def test_cli_roundtrip(self, tmp_path):
        ws = _repo(tmp_path / "ws"); out = tmp_path / "b.json"
        r = subprocess.run([sys.executable, str(Path(gc.__file__)), "snapshot", "--out", str(out), str(ws)], capture_output=True, text=True)
        assert r.returncode == 0 and r.stderr.strip() == "1" and json.loads(out.read_text())["repos"]
        r = subprocess.run([sys.executable, str(Path(gc.__file__)), "check", str(out)], capture_output=True, text=True)
        assert r.returncode == 0 and r.stdout == ""
        _git(ws, "config", "core.fsmonitor", "evil")
        r = subprocess.run([sys.executable, str(Path(gc.__file__)), "check", str(out)], capture_output=True, text=True)
        assert r.returncode == 1 and "core.fsmonitor" in r.stdout and "HOST git" in r.stdout
        assert "git-check token: " in r.stdout
        r = subprocess.run([sys.executable, str(Path(gc.__file__)), "check", str(out), "--json"], capture_output=True, text=True)
        doc = json.loads(r.stdout)
        assert r.returncode == 1 and doc["findings"][0]["kind"] == "dangerous-key" and doc["incomplete"] == []
        r = subprocess.run([sys.executable, str(Path(gc.__file__)), "check", str(out), "--token"], capture_output=True, text=True)
        assert r.returncode == 1 and r.stdout.strip() == doc["token"]
        # covers / roots / rebaseline: the launcher's helpers
        assert subprocess.run([sys.executable, str(Path(gc.__file__)), "covers", str(out), str(ws / "sub")]).returncode == 0
        assert subprocess.run([sys.executable, str(Path(gc.__file__)), "covers", str(out), str(tmp_path / "elsewhere")]).returncode == 1
        r = subprocess.run([sys.executable, str(Path(gc.__file__)), "roots", str(out)], capture_output=True, text=True)
        assert r.stdout.strip() == str(ws)
        assert subprocess.run([sys.executable, str(Path(gc.__file__)), "rebaseline", str(out)]).returncode == 0
        r = subprocess.run([sys.executable, str(Path(gc.__file__)), "check", str(out)], capture_output=True, text=True)
        assert r.returncode == 0 and r.stdout == ""                          # accepted state is the new baseline
