#!/usr/bin/env python3
"""Task-aware harness launch (harness-launch capability, #73): the launcher's
helper for the three questions it must answer before it builds the harness
command line and before it writes anything.

  args --harness=NAME [--adding=continue] [--adding=prompt]
        Read `[harness.<name>] args` as the JSON list `tjor_cfg get` prints
        (stdin), validate it, print one entry per line. Entries are non-empty
        strings without NUL or newline, at most 65536 bytes, never `--`; with
        --adding, an entry equal to the flag tjor is adding in this launch
        refuses (exact spellings only; nothing else is inspected).
  render --template=T --task=ID [--task-dir=DIR]
        Render `[task] prompt`: `{task}` and `{task_dir}` by literal
        substitution, `{{`/`}}` for literal braces, any other brace refuses;
        no NUL, at most 65536 bytes, at least one whitespace and one other
        character (a bare word is refused: Claude Code reads a bare positional
        naming one of its subcommands as that subcommand). Prints the prompt
        and nothing else.
  covers --root=P --state-root=R --session=S
        Would the writable root P cover the session's state directory R/S?
        Exit 0 yes, 1 no, 2 cannot tell. Read-only, never following a link,
        never creating anything: identity (st_dev, st_ino) on the parts that
        exist, the one component that may not exist yet by string.

Every option takes the attached form (`--task=-x`), so a dash-leading value
is a value. Every refusal is one line on stderr and exit 2; the launcher
refuses the launch on any of them.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import tjor_safeprint  # noqa: E402

HARNESSES = ("opencode", "claude", "copilot")
MAX_ELEMENT = 65536
# The flags tjor itself adds (spec: "The prompt is delivered in a form each
# harness reads as data"). An `args` entry equal to one of them, while tjor
# is adding it, is a visible mistake rather than two flags.
CONTINUE_FLAGS = ("--continue", "-c")
PROMPT_FLAGS = {
    "opencode": ("--prompt", "--prompt="),
    "claude": (),                       # a positional: nothing to collide with
    "copilot": ("-i", "--interactive", "--interactive="),
}
_WS = re.compile(r"\s")
_NON_WS = re.compile(r"\S")


class LaunchError(Exception):
    """A refusal: one line, printed by the CLI, exit 2."""


def _safe(text: str, limit: int = 80) -> str:
    out = tjor_safeprint.sanitize(str(text)).replace("\t", "\\t").replace("\n", "\\n")
    return out if len(out) <= limit else out[:limit] + "…"


# ------------------------------------------------------------------- args

def validate_args(raw, harness: str, adding: tuple[str, ...]) -> list[str]:
    if harness not in HARNESSES:
        raise LaunchError(f"unknown harness {_safe(harness)!r}: expected one of {', '.join(HARNESSES)}")
    key = f"harness.{harness}.args"
    if not isinstance(raw, list):
        raise LaunchError(f"{key} must be a list of strings (got {type(raw).__name__})")
    out: list[str] = []
    for i, entry in enumerate(raw, 1):
        where = f"{key} entry {i}"
        if not isinstance(entry, str):
            raise LaunchError(f"{where} must be a string (got {type(entry).__name__})")
        if entry == "":
            raise LaunchError(f"{where} is empty")
        if "\0" in entry:
            raise LaunchError(f"{where} holds a NUL byte")
        if "\n" in entry:
            raise LaunchError(f"{where} holds a newline: {_safe(entry)!r}")
        if len(entry.encode("utf-8")) > MAX_ELEMENT:
            raise LaunchError(f"{where} is longer than {MAX_ELEMENT} bytes")
        if entry == "--":
            raise LaunchError(f"{where} is `--`, which would end option parsing inside the configured arguments")
        if "continue" in adding and entry in CONTINUE_FLAGS:
            raise LaunchError(f"{where} is {entry!r}, but tjor is adding --continue for this launch "
                              "(task.resume = \"auto\" with a recorded conversation) — remove the entry or set task.resume")
        if "prompt" in adding:
            flags = PROMPT_FLAGS[harness]
            if entry in flags or any(entry.startswith(f) for f in flags if f.endswith("=")):
                raise LaunchError(f"{where} is {_safe(entry)!r}, but tjor is delivering task.prompt through that flag "
                                  "for this launch — remove the entry or unset task.prompt")
        out.append(entry)
    return out


# ----------------------------------------------------------------- render

def render(template: str, task: str, task_dir: str | None) -> str:
    """Literal substitution of exactly two placeholders with brace escapes.
    Scans left to right so a stray brace is named with its position."""
    key = "task.prompt"
    out: list[str] = []
    i, n = 0, len(template)
    while i < n:
        ch = template[i]
        if ch == "{":
            if template.startswith("{{", i):
                out.append("{"); i += 2; continue
            if template.startswith("{task}", i):
                out.append(task); i += len("{task}"); continue
            if template.startswith("{task_dir}", i):
                if not task_dir:
                    raise LaunchError(f"{key} uses {{task_dir}} but no notes directory is configured (task.notes_dir is empty)")
                out.append(task_dir); i += len("{task_dir}"); continue
            end = template.find("}", i)
            shown = template[i:end + 1] if end != -1 else template[i:i + 20]
            raise LaunchError(f"{key}: unknown placeholder or stray brace at offset {i}: {_safe(shown)!r} "
                              "(only {task} and {task_dir}; write {{ and }} for literal braces)")
        if ch == "}":
            if template.startswith("}}", i):
                out.append("}"); i += 2; continue
            raise LaunchError(f"{key}: stray '}}' at offset {i} (write }}}} for a literal brace)")
        out.append(ch); i += 1
    prompt = "".join(out)
    if "\0" in prompt:
        raise LaunchError(f"{key} renders to a prompt holding a NUL byte")
    if len(prompt.encode("utf-8")) > MAX_ELEMENT:
        raise LaunchError(f"{key} renders to more than {MAX_ELEMENT} bytes")
    if not _NON_WS.search(prompt):
        raise LaunchError(f"{key} renders to an empty or whitespace-only prompt")
    if not _WS.search(prompt):
        raise LaunchError(f"{key} renders to the single word {_safe(prompt)!r}: a one-word prompt is refused "
                          "(Claude Code reads a bare positional that names one of its subcommands as that subcommand, "
                          "`--` notwithstanding; the rule is the same for every harness) — add words to the template")
    return prompt


# ----------------------------------------------------------------- covers

def _lstat_dir(path: str, what: str):
    """lstat a path that must be a real directory. None when absent."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise LaunchError(f"cannot read {what} {_safe(path)}: {exc.strerror}") from exc
    if stat.S_ISLNK(st.st_mode):
        raise LaunchError(f"{what} {_safe(path)} is a symbolic link; it is never followed")
    if not stat.S_ISDIR(st.st_mode):
        raise LaunchError(f"{what} {_safe(path)} exists but is not a directory")
    return st


def _is_ancestor_or_self(key: tuple[int, int], path: str, what: str) -> bool:
    """Does the directory with identity `key` appear on `path`'s parent chain
    (path itself included)? Every step is lstat'ed; a link is an error."""
    cur = os.path.abspath(path)
    while True:
        st = _lstat_dir(cur, what)
        if st is None:
            raise LaunchError(f"{what} {_safe(cur)} vanished while it was being read")
        if (st.st_dev, st.st_ino) == key:
            return True
        parent = os.path.dirname(cur)
        if parent == cur:
            return False
        cur = parent


def covers(root: str, state_root: str, session: str) -> bool:
    """Would a writable root at `root` cover the state directory
    `state_root/session`? The state root exists (the launcher created it); the
    state directory may not yet (a fresh launch); `root` may not yet either
    (the notes directory before creation). Nothing is created or followed."""
    if not session or "/" in session or session in (".", ".."):
        raise LaunchError(f"session id {_safe(session)!r} is not one path component")
    st_r = _lstat_dir(state_root, "the session root")
    if st_r is None:
        raise LaunchError(f"the session root {_safe(state_root)} does not exist")
    key_r = (st_r.st_dev, st_r.st_ino)
    state_dir = os.path.join(state_root, session)
    st_d = _lstat_dir(state_dir, "the state directory")
    st_p = _lstat_dir(root, "the writable root")
    if st_p is not None:
        key_p = (st_p.st_dev, st_p.st_ino)
        # An existing root covers an existing state directory when it is that
        # directory or an ancestor of it; a MISSING state directory lies one
        # component below the session root, so only the root itself or one of
        # its ancestors can contain it.
        target = state_dir if st_d is not None else state_root
        return _is_ancestor_or_self(key_p, target, "a directory above the state root")
    if st_d is not None:
        return False   # every ancestor of an existing directory exists; a missing root is none of them
    # Both missing: the root would be created where the state directory will
    # be only if its deepest existing ancestor IS the session root and the
    # single missing component is the session id.
    cur = os.path.abspath(root)
    missing: list[str] = []
    while True:
        st = _lstat_dir(cur, "a directory above the writable root")
        if st is not None:
            break
        parent = os.path.dirname(cur)
        if parent == cur:
            raise LaunchError(f"no existing ancestor for {_safe(root)}")
        missing.insert(0, os.path.basename(cur))
        cur = parent
    return (st.st_dev, st.st_ino) == key_r and missing == [session]


# ------------------------------------------------------------------- main

def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="tjor_launch", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("args"); p.add_argument("--harness", required=True)
    p.add_argument("--adding", action="append", default=[], choices=("continue", "prompt"))
    p = sub.add_parser("render"); p.add_argument("--template", required=True); p.add_argument("--task", required=True)
    p.add_argument("--task-dir", default=None)
    p = sub.add_parser("covers"); p.add_argument("--root", required=True); p.add_argument("--state-root", required=True)
    p.add_argument("--session", required=True)
    args = parser.parse_args(argv)
    try:
        if args.cmd == "args":
            try:
                raw = json.loads(sys.stdin.read() or "null")
            except ValueError as exc:
                raise LaunchError(f"harness.{args.harness}.args is not valid JSON from the config reader: {exc}") from exc
            for entry in validate_args(raw, args.harness, tuple(args.adding)):
                print(entry)
        elif args.cmd == "render":
            sys.stdout.write(render(args.template, args.task, args.task_dir))
            sys.stdout.flush()
        elif args.cmd == "covers":
            return 0 if covers(args.root, args.state_root, args.session) else 1
        return 0
    except LaunchError as exc:
        print(f"tjor_launch: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
