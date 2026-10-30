"""task-notes capability (#69): the per-task notes helper. Every scenario of the
task-notes spec that is a path or identity question maps to a test here; the
launcher's wiring is tests/integration/task_notes_test.sh."""

import os
import stat
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tjor_task as tt


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "scratch" / "tasks").mkdir(parents=True)
    return tmp_path


class TestTemplate:
    def test_valid_template_resolves_and_creates_nothing(self, home):
        path, physical, rel = tt.resolve("~/scratch/tasks/{task}", "a")
        assert path == str(home / "scratch" / "tasks" / "a")
        assert physical == os.path.realpath(home / "scratch" / "tasks") and rel == ["a"]
        assert not (home / "scratch" / "tasks" / "a").exists()

    def test_placeholder_inside_a_component_and_below(self, home):
        path, physical, rel = tt.resolve(str(home / "scratch/tasks/t-{task}/notes"), "a")
        assert path.endswith("/scratch/tasks/t-a/notes") and rel == ["t-a", "notes"]

    @pytest.mark.parametrize("bad", [
        "scratch/tasks/{task}", "~/scratch/tasks", "~/scratch/{task}/{task}", "~/scratch/{task}/x{y}",
        "/safe/tasks/{task}/../../elsewhere", "/safe/tasks/{task}//notes", "//safe/tasks/{task}",
        "/safe/tasks/{task}/", "/safe/./tasks/{task}", "",
    ])
    def test_malformed_templates_refused(self, home, bad):
        with pytest.raises(tt.TaskError):
            tt.resolve(bad.replace("/safe", str(home)), "a")

    def test_missing_prefix_refused_and_never_created(self, home):
        with pytest.raises(tt.TaskError, match="never creates the root"):
            tt.resolve("~/scratch/nope/{task}", "a")
        assert not (home / "scratch" / "nope").exists()

    @pytest.mark.parametrize("bad", [".", "..", ".notes", "JIRA-123", "a" * 33, "", "a b", "a/b", "A"])
    def test_ids_outside_the_grammar_refused(self, home, bad):
        with pytest.raises(tt.TaskError, match="must match"):
            tt.resolve("~/scratch/tasks/{task}", bad)

    @pytest.mark.parametrize("good", ["a", "bug-12345678", "a_b-c", "0", "x" * 32])
    def test_ids_in_the_grammar(self, home, good):
        assert tt.resolve("~/scratch/tasks/{task}", good)[2] == [good]


class TestCreate:
    def test_creates_below_the_prefix_only(self, home):
        prefix = str(home / "scratch" / "tasks")
        dev_ino = tt.create(prefix, ["a", "notes"], True)
        target = home / "scratch" / "tasks" / "a" / "notes"
        assert target.is_dir() and not target.is_symlink()
        st = os.stat(target)
        assert dev_ino == (st.st_dev, st.st_ino)
        # a second run validates without change
        assert tt.create(prefix, ["a", "notes"], False) == dev_ino

    def test_no_create_refuses_missing(self, home):
        with pytest.raises(tt.TaskError, match="task.create is false"):
            tt.create(str(home / "scratch" / "tasks"), ["a"], False)
        assert not (home / "scratch" / "tasks" / "a").exists()

    def test_symlink_below_the_prefix_refused_wherever_it_points(self, home):
        prefix = home / "scratch" / "tasks"
        inside = prefix / "real"; inside.mkdir()
        outside = home / "elsewhere"; outside.mkdir()
        (prefix / "a").symlink_to(inside)
        (prefix / "b").symlink_to(outside)
        for name in ("a", "b"):
            with pytest.raises(tt.TaskError, match="symbolic link"):
                tt.create(str(prefix), [name], True)
        with pytest.raises(tt.TaskError, match="symbolic link"):
            tt.create(str(prefix), ["a", "notes"], True)   # the link is a middle component
        assert not (inside / "notes").exists() and not (outside / "notes").exists()

    def test_file_at_a_component_refused(self, home):
        (home / "scratch" / "tasks" / "a").write_text("x")
        with pytest.raises(tt.TaskError, match="not a directory"):
            tt.create(str(home / "scratch" / "tasks"), ["a", "notes"], True)

    def test_missing_prefix_refused(self, home):
        with pytest.raises(tt.TaskError):
            tt.create(str(home / "nope"), ["a"], True)

    def test_bad_components_refused_before_any_open(self, home):
        for comp in ["..", ".", "", "a/b"]:
            with pytest.raises(tt.TaskError):
                tt.create(str(home / "scratch" / "tasks"), [comp], True)


class TestContains:
    def test_ancestor_self_sibling_descendant(self, home):
        tasks = home / "scratch" / "tasks"; (tasks / "a").mkdir()
        (home / "other").mkdir()
        assert tt.contains(str(home / "scratch"), str(tasks / "a"))
        assert tt.contains(str(tasks / "a"), str(tasks / "a"))
        assert not tt.contains(str(home / "other"), str(tasks / "a"))
        assert not tt.contains(str(tasks / "a"), str(tasks))          # a descendant is not an ancestor

    def test_identity_not_string(self, home):
        tasks = home / "scratch" / "tasks"; (tasks / "a").mkdir()
        alias = home / "alias"; alias.symlink_to(home / "scratch")
        assert tt.contains(str(alias), str(tasks / "a"))               # another spelling of the same directory
        upper = Path(str(home / "scratch").upper())
        if upper.exists() and os.path.samefile(upper, home / "scratch"):   # a case-folding filesystem
            assert tt.contains(str(upper), str(tasks / "a"))

    def test_error_is_an_error_not_a_no(self, home):
        with pytest.raises(tt.TaskError):
            tt.contains(str(home), str(home / "vanished" / "x"))
        with pytest.raises(tt.TaskError):
            tt.contains(str(home / "vanished"), str(home))


class TestProbe:
    def test_create_and_remove(self, home):
        d = home / "scratch" / "tasks" / "a"; d.mkdir()
        name = tt.probe_create(str(d))
        assert tt.PROBE_NAME.fullmatch(name)
        st = os.stat(d / name)
        assert st.st_size == 0 and stat.S_IMODE(st.st_mode) == 0o600
        assert tt.probe_create(str(d)) != name
        tt.probe_remove(str(d), name)
        assert not (d / name).exists()
        tt.probe_remove(str(d), name)                                  # already gone: fine

    def test_remove_refuses_other_names(self, home):
        d = home / "scratch" / "tasks" / "a"; d.mkdir(); (d / "keep").write_text("x")
        for bad in ("../x", "keep", ".tjor-share-probe-zz", ".tjor-share-probe-" + "0" * 15):
            with pytest.raises(tt.TaskError):
                tt.probe_remove(str(d), bad)
        assert (d / "keep").exists()

    def test_linked_directory_refused(self, home):
        real = home / "real"; real.mkdir()
        (home / "scratch" / "tasks" / "a").symlink_to(real)
        with pytest.raises(tt.TaskError, match="symbolic link"):
            tt.probe_create(str(home / "scratch" / "tasks" / "a"))


class TestScan:
    def _dir(self, home):
        d = home / "scratch" / "tasks" / "a"; d.mkdir()
        return d

    def test_names_and_content(self, home):
        d = self._dir(home)
        (d / "deploy.pem").write_text("-----BEGIN")
        (d / "api-token.txt").write_text("x")
        (d / "id_ed25519").write_text("x")
        (d / ".netrc").write_text("x")
        (d / "kubeconfig").write_text("x")
        (d / "sub").mkdir(); (d / "sub" / "notes.md").write_text("token: ghp_" + "a" * 36)
        (d / "tokenizer.md").write_text("about tokenizers")
        (d / "plain.md").write_text("hello")
        findings, partial = tt.scan(str(d))
        found = {p: r for p, r in findings}
        assert "name ends in .pem" in found["deploy.pem"]
        assert found["api-token.txt"].startswith("name has the segment 'token'")
        assert found["id_ed25519"].startswith("name starts with id_")
        assert found[".netrc"].startswith("name has the segment 'netrc'")
        assert found["kubeconfig"].startswith("name has the segment 'kubeconfig'")
        assert found["sub/notes.md"].startswith("content looks like a")
        assert "tokenizer.md" not in found and "plain.md" not in found
        assert partial == []

    def test_clean_directory(self, home):
        d = self._dir(home); (d / "notes.md").write_text("plain")
        assert tt.scan(str(d)) == ([], [])

    def test_links_fifos_and_git_skipped(self, home):
        d = self._dir(home)
        (d / "real.pem").write_text("x")
        (d / "link.pem").symlink_to(d / "real.pem")
        (d / "dirlink").symlink_to(home / "scratch")
        os.mkfifo(d / "pipe.key")
        (d / ".git").mkdir(); (d / ".git" / "secret.pem").write_text("x")
        findings, partial = tt.scan(str(d))
        assert [p for p, _ in findings] == ["real.pem"]
        assert any("link.pem: symbolic link" in p for p in partial)
        assert any("dirlink: symbolic link" in p for p in partial)
        assert any("pipe.key: not a regular file" in p for p in partial)

    def test_bounds_are_reported(self, home, monkeypatch):
        d = self._dir(home)
        monkeypatch.setattr(tt, "SCAN_MAX_ENTRIES", 3)
        for i in range(5):
            (d / f"n{i}.md").write_text("x")
        _, partial = tt.scan(str(d))
        assert any("more than 3 entries" in p for p in partial)
        monkeypatch.setattr(tt, "SCAN_MAX_ENTRIES", 5000)
        monkeypatch.setattr(tt, "SCAN_MAX_FILE", 10)
        (d / "big.md").write_text("y" * 11)
        _, partial = tt.scan(str(d))
        assert any("big.md: larger than" in p for p in partial)
        monkeypatch.setattr(tt, "SCAN_MAX_FILE", 1024 * 1024)
        monkeypatch.setattr(tt, "SCAN_MAX_DEPTH", 1)
        deep = d / "l1" / "l2" / "l3"; deep.mkdir(parents=True); (deep / "x.pem").write_text("x")
        findings, partial = tt.scan(str(d))
        assert any("deeper than 1 levels" in p for p in partial)
        assert not any(p.endswith("x.pem") for p, _ in findings)

    def test_unreadable_file_reported(self, home):
        if os.geteuid() == 0:
            pytest.skip("root reads everything")
        d = self._dir(home)
        f = d / "locked.pem"; f.write_text("x"); f.chmod(0)
        findings, partial = tt.scan(str(d))
        assert ("locked.pem", "name ends in .pem") in findings       # the name still counts
        assert any("locked.pem: unreadable" in p for p in partial)
        f.chmod(0o600)

    def test_hostile_name_is_one_record(self, home, capsys):
        d = self._dir(home)
        (d / "a\tb\x1b[31m.pem").write_text("x")
        assert tt._main(["scan", str(d)]) == 0
        out = capsys.readouterr().out.splitlines()
        assert len(out) == 1 and out[0].endswith("\tname ends in .pem")
        assert "\x1b" not in out[0] and out[0].count("\t") == 1


class TestCapabilities:
    def test_present_here(self):
        tt.check_capabilities()

    @pytest.mark.parametrize("missing", ["open", "mkdir", "stat", "unlink", "follow", "scandir"])
    def test_a_missing_call_fails_closed(self, monkeypatch, missing, home):
        if missing == "follow":
            monkeypatch.setattr(os, "supports_follow_symlinks", set(os.supports_follow_symlinks) - {os.stat})
        elif missing == "scandir":
            monkeypatch.setattr(os, "supports_fd", set(os.supports_fd) - {os.scandir})
        else:
            monkeypatch.setattr(os, "supports_dir_fd", set(os.supports_dir_fd) - {getattr(os, missing)})
        with pytest.raises(tt.TaskError, match="descriptor-relative"):
            tt.check_capabilities()
        with pytest.raises(tt.TaskError):
            tt.create(str(home / "scratch" / "tasks"), ["a"], True)
        assert tt._main(["contains", str(home), str(home)]) == 2
        assert tt._main(["scan", str(home)]) == 1


class TestCli:
    def test_resolve_prints_three_lines_and_errors_exit_1(self, home, capsys):
        assert tt._main(["resolve", "--template", "~/scratch/tasks/{task}", "--task", "a"]) == 0
        out = capsys.readouterr().out.splitlines()
        assert len(out) == 3 and out[0].endswith("/scratch/tasks/a") and out[2] == "a"
        assert tt._main(["resolve", "--template", "~/scratch/tasks/{task}", "--task", "A"]) == 1
        assert "must match" in capsys.readouterr().err

    def test_contains_exit_codes(self, home, capsys):
        (home / "scratch" / "tasks" / "a").mkdir()
        assert tt._main(["contains", str(home / "scratch"), str(home / "scratch" / "tasks" / "a")]) == 0
        assert tt._main(["contains", str(home / "scratch" / "tasks" / "a"), str(home / "scratch")]) == 1
        assert tt._main(["contains", str(home / "nope"), str(home)]) == 2

    def test_create_and_probe_cli(self, home, capsys):
        assert tt._main(["create", "--prefix", str(home / "scratch" / "tasks"), "--relative", "a/notes"]) == 0
        assert ":" in capsys.readouterr().out
        assert tt._main(["create", "--prefix", str(home / "scratch" / "tasks"), "--relative", "b", "--no-create"]) == 1
        d = str(home / "scratch" / "tasks" / "a")
        assert tt._main(["probe-create", d]) == 0
        name = capsys.readouterr().out.strip()
        assert tt._main(["probe-remove", d, name]) == 0 and not os.path.exists(os.path.join(d, name))
