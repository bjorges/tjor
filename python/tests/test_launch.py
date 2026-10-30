"""Task-aware harness launch helper (#73, spec: harness-launch): the args
rules and the exact collision set, prompt rendering with brace escapes and
the one-word rule, and the read-only coverage check over a state directory
that may not exist yet."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tjor_launch as tl

HELPER = Path(__file__).resolve().parents[1] / "tjor_launch.py"


def _run(*args, stdin=""):
    return subprocess.run([sys.executable, "-I", str(HELPER), *args], input=stdin, capture_output=True, text=True)


# ---- args ----------------------------------------------------------------------

def test_args_pass_verbatim_in_order():
    assert tl.validate_args(["--model", "opus", "-x", "a b", "ü"], "claude", ()) == ["--model", "opus", "-x", "a b", "ü"]


def test_args_empty_list_is_fine():
    assert tl.validate_args([], "opencode", ("continue", "prompt")) == []


@pytest.mark.parametrize("raw,needle", [
    ("notalist", "must be a list"),
    ({"a": 1}, "must be a list"),
    ([1], "entry 1 must be a string"),
    (["ok", ""], "entry 2 is empty"),
    (["a\0b"], "NUL"),
    (["a\nb"], "newline"),
    (["x" * 65537], "longer than 65536"),
    (["--model", "--"], "entry 2 is `--`"),
])
def test_args_refusals_name_position_and_rule(raw, needle):
    with pytest.raises(tl.LaunchError) as exc:
        tl.validate_args(raw, "opencode", ())
    assert needle in str(exc.value)


def test_args_unknown_harness_refused():
    with pytest.raises(tl.LaunchError, match="unknown harness"):
        tl.validate_args([], "foo", ())


@pytest.mark.parametrize("harness,entry", [("opencode", "--continue"), ("claude", "-c"), ("copilot", "--continue")])
def test_args_collide_with_continue_only_while_adding_it(harness, entry):
    assert tl.validate_args([entry], harness, ()) == [entry]           # not adding: the operator's own
    with pytest.raises(tl.LaunchError, match="adding --continue"):
        tl.validate_args([entry], harness, ("continue",))


@pytest.mark.parametrize("harness,entry", [
    ("opencode", "--prompt"), ("opencode", "--prompt=hi there"),
    ("copilot", "-i"), ("copilot", "--interactive"), ("copilot", "--interactive=hi there"),
])
def test_args_collide_with_the_prompt_flag_only_while_adding_it(harness, entry):
    assert tl.validate_args([entry], harness, ()) == [entry]
    with pytest.raises(tl.LaunchError, match="delivering task.prompt"):
        tl.validate_args([entry], harness, ("prompt",))


def test_args_claude_prompt_is_positional_so_nothing_collides():
    assert tl.validate_args(["--prompt", "-i"], "claude", ("prompt",)) == ["--prompt", "-i"]


def test_args_nothing_else_is_inspected():
    # permission-relaxing and conversation-selecting flags pass: tjor does not know the flag sets
    entries = ["--dangerously-skip-permissions", "--resume", "abc", "--session-id", "u", "mcp", "-ic"]
    assert tl.validate_args(entries, "claude", ("continue", "prompt")) == entries


def test_args_cli_prints_one_per_line_and_exits_2_on_refusal():
    r = _run("args", "--harness=claude", stdin=json.dumps(["--model", "opus", "a b"]))
    assert r.returncode == 0 and r.stdout == "--model\nopus\na b\n"
    r = _run("args", "--harness=opencode", "--adding=prompt", stdin=json.dumps(["--prompt=x"]))
    assert r.returncode == 2 and r.stdout == "" and "delivering task.prompt" in r.stderr
    r = _run("args", "--harness=opencode", stdin="not json")
    assert r.returncode == 2 and "not valid JSON" in r.stderr


# ---- render ----------------------------------------------------------------------

def test_render_substitutes_both_placeholders():
    assert tl.render("Task {task}. Notes: {task_dir}.", "a", "/home/me/scratch/tasks/a") == "Task a. Notes: /home/me/scratch/tasks/a."


def test_render_literal_braces():
    assert tl.render('Reply as {{"task": "{task}"}}', "a", None) == 'Reply as {"task": "a"}'
    assert tl.render("{{{task}}} is {task}", "a", None) == "{a} is a"


def test_render_multiline_and_trailing_newline_preserved():
    assert tl.render("Task {task}\nsecond line\n", "a", None) == "Task a\nsecond line\n"


def test_render_dash_leading_label_id_is_data():
    assert tl.render("Task {task} starts.", "-x", None) == "Task -x starts."


@pytest.mark.parametrize("template,needle", [
    ("Task {taks}", "unknown placeholder or stray brace at offset 5"),
    ("Task { x", "stray brace"),
    ("Task } x", "stray '}' at offset 5"),
    ("{task}", "one-word prompt is refused"),
    ("   ", "empty or whitespace-only"),
    ("a{task}b", "one-word prompt"),
])
def test_render_refusals(template, needle):
    with pytest.raises(tl.LaunchError) as exc:
        tl.render(template, "mcp", "/n")
    assert needle in str(exc.value)


def test_render_task_dir_without_notes_refused():
    with pytest.raises(tl.LaunchError, match="no notes directory is configured"):
        tl.render("Task {task} in {task_dir}", "a", None)


def test_render_bounds():
    with pytest.raises(tl.LaunchError, match="more than 65536 bytes"):
        tl.render("x " + "y" * 65536, "a", None)
    with pytest.raises(tl.LaunchError, match="NUL"):
        tl.render("Task {task} x", "a\0b", None)


def test_render_cli_writes_the_prompt_only_and_accepts_attached_dash_values():
    r = _run("render", "--template=Task {task} starts.", "--task=-x")
    assert r.returncode == 0 and r.stdout == "Task -x starts." and r.stderr == ""
    r = _run("render", "--template=Task {task}\n", "--task=a")
    assert r.stdout == "Task a\n"
    r = _run("render", "--template={task}", "--task=mcp")
    assert r.returncode == 2 and r.stdout == "" and "one-word" in r.stderr


# ---- covers ----------------------------------------------------------------------

@pytest.fixture
def roots(tmp_path):
    state_root = tmp_path / "sessions"
    state_root.mkdir()
    return tmp_path, state_root


def _nothing_created(tmp_path, before):
    after = sorted(str(p) for p in tmp_path.rglob("*"))
    assert after == before


def test_covers_missing_state_dir_root_is_the_session_root(roots):
    tmp_path, sr = roots
    before = sorted(str(p) for p in tmp_path.rglob("*"))
    assert tl.covers(str(sr), str(sr), "sid") is True
    assert tl.covers(str(tmp_path), str(sr), "sid") is True            # an ancestor of the session root
    _nothing_created(tmp_path, before)


def test_covers_missing_state_dir_sibling_and_descendant_do_not(roots):
    tmp_path, sr = roots
    (tmp_path / "sessions-other").mkdir()
    (sr / "other").mkdir()
    assert tl.covers(str(tmp_path / "sessions-other"), str(sr), "sid") is False   # component-boundary sibling
    assert tl.covers(str(sr / "other"), str(sr), "sid") is False              # a descendant of the root, not ours


def test_covers_existing_state_dir(roots):
    tmp_path, sr = roots
    (sr / "sid" / "home").mkdir(parents=True)
    assert tl.covers(str(sr / "sid"), str(sr), "sid") is True
    assert tl.covers(str(sr), str(sr), "sid") is True
    assert tl.covers(str(sr / "sid" / "home"), str(sr), "sid") is False      # below the record, not over it
    assert tl.covers(str(tmp_path / "elsewhere"), str(sr), "sid") is False   # missing root, existing state dir


def test_covers_missing_root_that_would_become_the_state_dir(roots):
    tmp_path, sr = roots
    before = sorted(str(p) for p in tmp_path.rglob("*"))
    assert tl.covers(str(sr / "sid"), str(sr), "sid") is True                # both missing, same path
    assert tl.covers(str(sr / "sid" / "notes"), str(sr), "sid") is False     # two missing components
    assert tl.covers(str(tmp_path / "notes" / "a"), str(sr), "sid") is False
    _nothing_created(tmp_path, before)


def test_covers_identity_not_spelling(roots):
    tmp_path, sr = roots
    alias = tmp_path / "alias"
    alias.symlink_to(sr)
    # A root reached through a link is refused outright (the launcher passes
    # physical paths; a link here means something was swapped).
    with pytest.raises(tl.LaunchError, match="symbolic link"):
        tl.covers(str(alias), str(sr), "sid")
    # A root spelled through a LINKED PARENT denotes the same directory (the
    # kernel resolves intermediate components exactly as a bind mount would);
    # the answer is by identity of what the path denotes, never its spelling.
    linked_parent = tmp_path / "lp"
    linked_parent.symlink_to(tmp_path)
    assert tl.covers(str(linked_parent / "sessions"), str(sr), "sid") is True
    assert tl.covers(str(linked_parent / "sessions-other"), str(sr), "sid") is False if (tmp_path / "sessions-other").mkdir() is None else None


def test_covers_case_alias_on_case_insensitive_fs(roots):
    tmp_path, sr = roots
    upper = tmp_path / "SESSIONS"
    try:
        same = os.path.samefile(str(upper), str(sr))
    except OSError:
        same = False
    if not same:
        pytest.skip("case-sensitive filesystem: no alias to test")
    assert tl.covers(str(upper), str(sr), "sid") is True


def test_covers_errors_are_refusals_not_absence(roots, tmp_path):
    _, sr = roots
    f = tmp_path / "file"
    f.write_text("x")
    with pytest.raises(tl.LaunchError, match="not a directory"):
        tl.covers(str(f), str(sr), "sid")
    with pytest.raises(tl.LaunchError, match="does not exist"):
        tl.covers(str(tmp_path), str(tmp_path / "nope"), "sid")
    with pytest.raises(tl.LaunchError, match="one path component"):
        tl.covers(str(tmp_path), str(sr), "a/b")
    (sr / "sid").symlink_to(tmp_path)
    with pytest.raises(tl.LaunchError, match="symbolic link"):
        tl.covers(str(tmp_path), str(sr), "sid")


def test_covers_cli_exit_codes(roots):
    tmp_path, sr = roots
    assert _run("covers", f"--root={sr}", f"--state-root={sr}", "--session=sid").returncode == 0
    assert _run("covers", f"--root={tmp_path}/other", f"--state-root={sr}", "--session=sid").returncode == 1
    r = _run("covers", f"--root={tmp_path}", f"--state-root={tmp_path}/nope", "--session=sid")
    assert r.returncode == 2 and "does not exist" in r.stderr
