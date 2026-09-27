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
    ])
    def test_dangerous(self, key, value):
        assert gc.is_dangerous(key, value)

    @pytest.mark.parametrize("key,value", [
        ("branch.main.remote", "origin"), ("branch.main.merge", "refs/heads/main"),
        ("remote.origin.url", "https://github.com/x/y"), ("remote.origin.fetch", "+refs/*:refs/*"),
        ("remote.origin.push", "HEAD"), ("user.name", "t"), ("user.email", "t@x"),
        ("push.autoSetupRemote", "true"), ("core.bare", "false"), ("core.filemode", "true"),
        ("alias.st", "status"), ("submodule.s.update", "checkout"), ("pull.rebase", "true"),
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
        assert f[0]["key"] == "core.hookspath" and f[0]["old"] is None and f[0]["new"] == ".custom-hooks"

    def test_changed_and_removed_keys_reported(self, tmp_path):
        ws = _repo(tmp_path / "ws"); _git(ws, "config", "core.pager", "less"); base = gc.snapshot([str(ws)])
        _git(ws, "config", "core.pager", "evil"); f = gc.diff(base, gc.snapshot([str(ws)]))
        assert f and f[0]["old"] == "less" and f[0]["new"] == "evil"
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

    def test_hook_added(self, tmp_path):
        ws = _repo(tmp_path / "ws"); base = gc.snapshot([str(ws)])
        (ws / ".git" / "hooks").mkdir(exist_ok=True); (ws / ".git" / "hooks" / "pre-commit").write_text("#!/bin/sh\nevil\n")
        assert any(x["kind"] == "hook-changed" and x["key"] == "pre-commit" for x in gc.diff(base, gc.snapshot([str(ws)])))

    def test_nested_repo_planted(self, tmp_path):
        ws = _repo(tmp_path / "ws"); base = gc.snapshot([str(ws)])
        _repo(ws / "src")
        f = gc.diff(base, gc.snapshot([str(ws)]))
        assert any(x["kind"] == "nested-repo-added" and x["path"].endswith("/src") for x in f)

    def test_repo_missing(self, tmp_path):
        ws = _repo(tmp_path / "ws"); base = gc.snapshot([str(ws)])
        import shutil; shutil.rmtree(ws / ".git")
        assert [x["kind"] for x in gc.diff(base, gc.snapshot([str(ws)]))] == ["repo-missing"]

    def test_render_sanitizes(self, tmp_path):
        line = gc.render({"repo": "/r/\x1b[31mX", "kind": "dangerous-key", "key": "core.hookspath", "old": None, "new": "\x1b]0;x\x07"})
        assert "\x1b" not in line and "HOST git" in line

    def test_cli_roundtrip(self, tmp_path):
        ws = _repo(tmp_path / "ws"); out = tmp_path / "b.json"
        r = subprocess.run([sys.executable, str(Path(gc.__file__)), "snapshot", "--out", str(out), str(ws)], capture_output=True, text=True)
        assert r.returncode == 0 and r.stderr.strip() == "1" and json.loads(out.read_text())["repos"]
        r = subprocess.run([sys.executable, str(Path(gc.__file__)), "check", str(out)], capture_output=True, text=True)
        assert r.returncode == 0 and r.stdout == ""
        _git(ws, "config", "core.fsmonitor", "evil")
        r = subprocess.run([sys.executable, str(Path(gc.__file__)), "check", str(out)], capture_output=True, text=True)
        assert r.returncode == 1 and "core.fsmonitor" in r.stdout and "HOST git" in r.stdout
        r = subprocess.run([sys.executable, str(Path(gc.__file__)), "check", str(out), "--json"], capture_output=True, text=True)
        assert r.returncode == 1 and json.loads(r.stdout)[0]["kind"] == "dangerous-key"
