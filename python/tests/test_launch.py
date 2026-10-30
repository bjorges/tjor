"""Task-aware harness launch helper (#73, spec: harness-launch): the args
rules and the exact collision set, prompt rendering with brace escapes and
the one-word rule, and the read-only coverage check over a state directory
that may not exist yet."""
import io
import json
import os
import subprocess
import sys
import unicodedata
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
    ("{task}\n", "one-word prompt"),          # surrounding whitespace does not make a sentence
    ("  {task}  ", "one-word prompt"),
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


def test_render_surrogate_escaped_path_is_a_prompt_not_a_traceback():
    out = tl.render("Task {task} in {task_dir}", "a", "/n/\udcff")
    assert out.startswith("Task a in /n/") and "\udcff" in out


def test_render_cli_writes_the_prompt_only_and_accepts_attached_dash_values():
    r = _run("render", "--task=-x", stdin=json.dumps("Task {task} starts."))
    assert r.returncode == 0 and r.stdout == "Task -x starts." and r.stderr == ""
    r = _run("render", "--task=a", stdin=json.dumps("Task {task}" + chr(10)))
    assert r.stdout == "Task a\n"
    r = _run("render", "--task=mcp", stdin=json.dumps("{task}"))
    assert r.returncode == 2 and r.stdout == "" and "one-word" in r.stderr


def test_render_cli_template_type_and_json_are_checked():
    r = _run("render", "--task=a", stdin='["hello world"]')
    assert r.returncode == 2 and "must be a string" in r.stderr
    r = _run("render", "--task=a", stdin="not json")
    assert r.returncode == 2 and "not valid JSON" in r.stderr
    r = _run("render", "--task=a", stdin="")                                    # an empty stdin is not a template
    assert r.returncode == 2 and "must be a string" in r.stderr
    r = _run("render", "--task=a", stdin=json.dumps("Task {task} x" + chr(0)))  # an escaped NUL survives the shell
    assert r.returncode == 2 and "NUL" in r.stderr


def test_render_cli_takes_the_template_on_stdin_not_argv():
    # The template as `tjor_cfg get --json` prints it is ASCII-escaped: a
    # legal prompt of 22,000 `é` is 44 KB of UTF-8 but 132 KB of JSON, over
    # the 128 KiB Linux allows one argv element — so the template travels on
    # stdin, and such a prompt renders rather than failing in execve.
    body = "é" * 22000
    template = json.dumps("Task {task} " + body)
    rendered = f"Task a {body}"
    assert len(template.encode("ascii")) > 131072 and len(rendered.encode("utf-8")) <= tl.MAX_ELEMENT
    r = subprocess.run([sys.executable, "-I", str(HELPER), "render", "--task=a"], input=template.encode("ascii"), capture_output=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout == rendered.encode("utf-8")


def test_render_cli_is_utf8_under_a_c_locale():
    # `-X utf8=0`: since Python 3.7 the C locale switches UTF-8 mode on by
    # itself (PEP 540), which would make this pass with the stream
    # reconfiguration deleted; with it off, the streams default to ASCII and
    # only the helper's own reconfigure keeps a non-ASCII prompt intact.
    env = {**os.environ, "LC_ALL": "C", "LANG": "C", "LANGUAGE": ""}
    env.pop("PYTHONIOENCODING", None); env.pop("PYTHONUTF8", None)
    r = subprocess.run([sys.executable, "-I", "-X", "utf8=0", str(HELPER), "render", "--task=a"],
                       input=json.dumps("Tásk {task} ü").encode("ascii"), capture_output=True, env=env)
    assert r.returncode == 0, r.stderr
    assert r.stdout == "Tásk a ü".encode("utf-8")


def test_main_turns_any_exception_into_a_refusal(monkeypatch, tmp_path):
    def boom(*_a, **_k):
        raise RuntimeError("boom")
    monkeypatch.setattr(tl, "covers", boom)
    assert tl._main(["covers", f"--root={tmp_path}", f"--state-root={tmp_path}", "--session=x"]) == 2
    monkeypatch.setattr(tl, "render", boom)
    monkeypatch.setattr(sys, "stdin", io.StringIO('"Task {task} x"'))
    assert tl._main(["render", "--task=a"]) == 2


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
    # A link ANYWHERE in the root's chain is refused too (the launcher passes
    # physical paths; a link in the chain means something was swapped), the
    # same whether the leaf exists or not.
    linked_parent = tmp_path / "lp"
    linked_parent.symlink_to(tmp_path)
    with pytest.raises(tl.LaunchError, match="symbolic link"):
        tl.covers(str(linked_parent / "sessions"), str(sr), "sid")
    with pytest.raises(tl.LaunchError, match="symbolic link"):
        tl.covers(str(linked_parent / "sessions" / "sid"), str(sr), "sid")
    # ... and when the state directory already exists while the root is
    # missing (a relaunch with a notes directory not yet created): the
    # answer would be "no", but the link in the chain is refused first.
    (sr / "sid").mkdir()
    with pytest.raises(tl.LaunchError, match="symbolic link"):
        tl.covers(str(linked_parent / "notes" / "x"), str(sr), "sid")
    assert tl.covers(str(tmp_path / "notes" / "x"), str(sr), "sid") is False   # the same shape without the link


def test_canonical_caseless_form_is_the_comparison():
    assert tl._may_alias("PROJ-A", "proj-a") and tl._may_alias("séance", "SÉANCE")
    assert tl._may_alias("straße", "STRASSE")          # casefold, not lower: U+00DF ß folds to ss
    assert tl._may_alias("Ω", "ω")                 # U+2126 OHM SIGN → U+03A9 under NFKC, then folded to ω
    # The outer normalisation: casefolding can yield a decomposed or reordered
    # sequence. U+00DF + U+0301 folds to `s`, `s`, U+0301, which composes to
    # `sś` only when normalised again; U+0130 İ + U+0316 (a mark below) folds
    # to `i` + U+0307 + U+0316, which the canonical ordering turns into `i` +
    # U+0316 + U+0307. Both fail without the outer step.
    assert tl._may_alias("ß́", "sś")
    assert tl._may_alias("İ̖", "i̖̇")
    assert unicodedata.normalize("NFKC", "ß́".casefold()) != "ß́".casefold()   # the premise above
    assert not tl._may_alias("proj-a", "proj-b")


def test_covers_missing_component_that_a_folding_filesystem_would_alias(roots):
    tmp_path, sr = roots
    before = sorted(str(p) for p in tmp_path.rglob("*"))
    # Both missing: the notes directory `<root>/PROJ-12345678-A` would be the
    # state directory `proj-12345678-a` on a case-insensitive filesystem;
    # nothing exists to compare identities, so the spelling is judged
    # conservatively (case-folded, Unicode-normalised).
    assert tl.covers(str(sr / "PROJ-12345678-A"), str(sr), "proj-12345678-a") is True
    assert tl.covers(str(sr / "proj-12345678-a"), str(sr), "proj-12345678-a") is True
    assert tl.covers(str(sr / "proj-12345678-a-other"), str(sr), "proj-12345678-a") is False
    assert tl.covers(str(sr / "se\u0301ance"), str(sr), "s\u00e9ance") is True       # NFD vs NFC
    _nothing_created(tmp_path, before)


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


def test_covers_refuses_dot_components_and_relative_paths(roots):
    tmp_path, sr = roots
    # `L/../x` collapses lexically to `x`, so the link L would never be
    # lstat'ed: refused by spelling before any walk, on either path.
    link = tmp_path / "L"
    link.symlink_to(tmp_path / "elsewhere")
    with pytest.raises(tl.LaunchError, match="'\\.\\.' component"):
        tl.covers(f"{link}/../new", str(sr), "sid")
    with pytest.raises(tl.LaunchError, match="'\\.' component"):
        tl.covers(f"{tmp_path}/./new", str(sr), "sid")
    with pytest.raises(tl.LaunchError, match="'\\.\\.' component"):
        tl.covers(str(tmp_path / "new"), f"{link}/../sessions", "sid")
    with pytest.raises(tl.LaunchError, match="not an absolute path"):
        tl.covers("new", str(sr), "sid")
    assert tl.covers(str(tmp_path / "new"), str(sr), "sid") is False       # the same shape, spelled plainly


def test_stdin_is_bounded(monkeypatch, capsys):
    monkeypatch.setattr(tl, "MAX_STDIN", 16)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps("Task {task} " + "x" * 40)))
    assert tl._main(["render", "--task=a"]) == 2
    assert "exceeds 16 characters" in capsys.readouterr().err
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(["--model", "opus", "x" * 40])))
    assert tl._main(["args", "--harness=claude"]) == 2
    assert "exceeds 16 characters" in capsys.readouterr().err
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps("Task {task}.")))
    assert tl._main(["render", "--task=a"]) == 0 and capsys.readouterr().out == "Task a."


def test_stdin_bound_is_inclusive_and_never_truncates(monkeypatch, capsys):
    doc = json.dumps("Task {task}.")
    monkeypatch.setattr(tl, "MAX_STDIN", len(doc))                           # exactly the bound: accepted, whole
    monkeypatch.setattr(sys, "stdin", io.StringIO(doc))
    assert tl._main(["render", "--task=a"]) == 0 and capsys.readouterr().out == "Task a."
    monkeypatch.setattr(tl, "MAX_STDIN", len(doc) - 1)                       # one over: refused, not parsed short
    monkeypatch.setattr(sys, "stdin", io.StringIO(doc))
    assert tl._main(["render", "--task=a"]) == 2
    assert f"exceeds {len(doc) - 1} characters" in capsys.readouterr().err


def test_caseless_form_agrees_with_d146_on_every_code_point():
    # The docstring's claim, checked against the interpreter's own Unicode
    # data (about a third of a second): for every assigned code point c,
    # comparing c with the NFKC spelling of its D146 image gives the same
    # verdict under our NFKC/casefold/NFKC form as under D146 itself
    # (NFKD(casefold(NFKD(casefold(NFD(x)))))).
    N = unicodedata.normalize
    def d146(x):
        return N("NFKD", N("NFKD", N("NFD", x).casefold()).casefold())
    disagreements = []
    for cp in range(0x20, 0x110000):
        if 0xD800 <= cp <= 0xDFFF:
            continue
        c = chr(cp)
        if not unicodedata.name(c, ""):
            continue
        y = N("NFKC", d146(c))
        if tl._may_alias(c, y) != (d146(c) == d146(y)):
            disagreements.append(hex(cp))
    assert disagreements == [], f"Unicode {unicodedata.unidata_version}: {disagreements[:10]}"


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
    assert _run("covers", f"--root={tmp_path}/other", f"--state-root={sr}", "--session=sid").returncode == tl.NOT_COVERED == 3
    r = _run("covers", f"--root={tmp_path}", f"--state-root={tmp_path}/nope", "--session=sid")
    assert r.returncode == 2 and "does not exist" in r.stderr
