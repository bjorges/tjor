#!/usr/bin/env python3
"""Per-task notes directory (task-notes capability, #69): the launcher's helper
for everything about `--task <id>` that is a path or a filesystem-identity
question. Descriptor-relative, never following a link, so that what was
checked is what is used:

  resolve --template T --task ID      validate the template and the id; print the
                                      intended path, the physical prefix and the
                                      relative part below it (no side effect)
  create --prefix P --relative R      walk below the prefix with openat-style
         [--no-create]                steps (O_DIRECTORY|O_NOFOLLOW), creating a
                                      missing component with mkdirat unless
                                      --no-create; print the directory's identity
  contains A B                        exit 0 when A is B or an ancestor of B by
                                      (st_dev, st_ino), 3 when not, 2 on error
                                      (never 1, Python's own exit for a crash
                                      before or outside _main, so a fault can
                                      never read as "no"). A and B are the
                                      launcher's physical, absolute paths: a
                                      link anywhere on either chain, or a `.`
                                      or `..` component, is an error, never
                                      followed or collapsed
  probe-create DIR / probe-remove DIR NAME
                                      an empty, unpredictable probe file for the
                                      VM-share correspondence check
  scan DIR                            bounded, link-free scan for credential-shaped
                                      names and secret-shaped content; one
                                      `path<TAB>reason` line per finding and a
                                      `partial<TAB>reason` line per bound hit or
                                      entry skipped; exit 0 always

Every error is one line on stderr and a non-zero exit; the launcher refuses the
launch on any of them (an error is never read as "not contained" or "clean").
"""

from __future__ import annotations

import argparse
import os
import re
import secrets
import stat
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import tjor_paths  # noqa: E402
import tjor_safeprint  # noqa: E402
import tjor_secrets  # noqa: E402

# A task id that names a directory or a session: lower-case, dot-free (no `.`,
# `..`, hidden names, no dot in a Compose project name), at most 32 characters
# (it is the session's short name as-is, no truncation).
TASK_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,31}")
PLACEHOLDER = "{task}"
NOT_CONTAINED = 3   # `contains`: a distinct, non-default exit code for "no"; 1 (Python's own) is never "no"
PROBE_PREFIX = ".tjor-share-probe-"
PROBE_NAME = re.compile(r"\.tjor-share-probe-[0-9a-f]{16}")

SCAN_MAX_DEPTH = 8
SCAN_MAX_ENTRIES = 5000
SCAN_MAX_FILE = 256 * 1024
SCAN_MAX_TOTAL = 16 * 1024 * 1024
# Name segments (split on `.`, `_`, `-`) that read as a credential; suffixes;
# the `id_*` SSH key convention. `tokenizer.md` has no such segment.
NAME_SEGMENTS = frozenset({"token", "tokens", "credential", "credentials", "secret", "secrets",
                           "password", "netrc", "npmrc", "kubeconfig"})
NAME_SUFFIXES = (".pem", ".key", ".p12", ".pfx")


class TaskError(Exception):
    """A refusal: one line, printed by the CLI, non-zero exit."""


def _safe(text: str) -> str:
    return tjor_safeprint.sanitize(str(text)).replace("\t", "\\t").replace("\n", "\\n")


# ------------------------------------------------------------ capabilities

def check_capabilities() -> None:
    """The calls this module makes with dir_fd / on a descriptor. CPython lists
    them per platform; where one is missing the feature is unavailable and the
    launcher must refuse rather than fall back to path-based steps."""
    missing = []
    for fn in (os.open, os.mkdir, os.stat, os.unlink):
        if fn not in os.supports_dir_fd:
            missing.append(f"{fn.__name__} with dir_fd")
    if os.stat not in os.supports_follow_symlinks:
        missing.append("stat with follow_symlinks=False")
    if os.scandir not in os.supports_fd:
        missing.append("scandir on a descriptor")
    if missing:
        raise TaskError("this Python cannot do descriptor-relative file operations ("
                        + ", ".join(missing) + "); the task notes directory is unavailable")


# ---------------------------------------------------------------- resolve

def validate_task_id(task: str) -> None:
    if not isinstance(task, str) or not TASK_ID.fullmatch(task):
        raise TaskError(f"task id {_safe(task)!r} must match [a-z0-9][a-z0-9_-]{{0,31}} once it names a "
                        "directory or a session: lower-case, no dot, at most 32 characters")


def _component_ok(name: str) -> bool:
    return name not in ("", ".", "..") and "/" not in name


def split_template(template: str) -> tuple[str, list[str]]:
    """The template's fixed prefix and the components below it (the first of
    which holds the placeholder). Validated component by component: one leading
    separator (POSIX normpath keeps two), no empty, `.` or `..` component, no
    trailing separator, `{task}` exactly once inside one component, no other
    brace."""
    if not isinstance(template, str) or not template:
        raise TaskError("task.notes_dir is empty")
    t = template
    if t == "~" or t.startswith("~/"):
        t = os.path.expanduser(t)
    if not t.startswith("/") or t.startswith("//"):
        raise TaskError(f"task.notes_dir must be an absolute path with one leading '/': {_safe(template)!r}")
    if t.endswith("/"):
        raise TaskError(f"task.notes_dir must not end in '/': {_safe(template)!r}")
    comps = t.split("/")[1:]
    for c in comps:
        if not _component_ok(c):
            raise TaskError(f"task.notes_dir holds an empty, '.' or '..' component: {_safe(template)!r}")
    holders = [i for i, c in enumerate(comps) if PLACEHOLDER in c]
    if len(holders) != 1 or comps[holders[0]].count(PLACEHOLDER) != 1 \
            or "{" in t.replace(PLACEHOLDER, "") or "}" in t.replace(PLACEHOLDER, ""):
        raise TaskError(f"task.notes_dir must hold '{{task}}' exactly once and no other brace: {_safe(template)!r}")
    i = holders[0]
    prefix = "/" + "/".join(comps[:i])
    return prefix, comps[i:]


def resolve(template: str, task: str) -> tuple[str, str, list[str]]:
    """(intended path, physical prefix, relative components). No side effect.
    The prefix must already exist as a directory; tjor never creates it."""
    validate_task_id(task)
    prefix, below = split_template(template)
    rel = [c.replace(PLACEHOLDER, task) for c in below]
    for c in rel:
        if not _component_ok(c):   # cannot happen with the grammar; the check is the guarantee
            raise TaskError(f"task id yields an invalid path component: {_safe(c)!r}")
    if not os.path.isdir(prefix):
        raise TaskError(f"notes root {_safe(prefix)} does not exist or is not a directory (tjor never creates the root; "
                        f"create it, or fix task.notes_dir)")
    physical = os.path.realpath(prefix)
    return os.path.join(prefix, *rel), physical, rel


# ----------------------------------------------------------------- create

def create(prefix: str, relative: list[str], do_create: bool) -> tuple[int, int]:
    """Walk below the prefix one component at a time, each opened relative to
    its parent with O_DIRECTORY|O_NOFOLLOW (a link refuses, a file refuses);
    a missing component is made with mkdir(dir_fd=) when creating. Returns the
    final directory's (st_dev, st_ino)."""
    check_capabilities()
    for c in relative:
        if not _component_ok(c):
            raise TaskError(f"invalid path component {_safe(c)!r}")
    try:
        fd = os.open(prefix, os.O_RDONLY | os.O_DIRECTORY)
    except OSError as exc:
        raise TaskError(f"notes root {_safe(prefix)}: {exc.strerror}") from exc
    cur = prefix
    try:
        for name in relative:
            here = os.path.join(cur, name)
            child = _open_child(fd, name, here)
            if child is None:
                if not do_create:
                    raise TaskError(f"{_safe(here)} does not exist and task.create is false")
                try:
                    os.mkdir(name, 0o777, dir_fd=fd)
                except FileExistsError:
                    pass   # appeared meanwhile: the open below judges what it is
                except OSError as exc:
                    raise TaskError(f"cannot create {_safe(here)}: {exc.strerror}") from exc
                child = _open_child(fd, name, here)
                if child is None:
                    raise TaskError(f"{_safe(here)} vanished right after it was created")
            os.close(fd)
            fd, cur = child, here
        st = os.fstat(fd)
        if not stat.S_ISDIR(st.st_mode):
            raise TaskError(f"{_safe(cur)} is not a directory")
        return st.st_dev, st.st_ino
    finally:
        os.close(fd)


def _open_child(fd: int, name: str, here: str) -> int | None:
    # lstat first, relative and without following: a link is named as a link
    # (macOS answers ENOTDIR to O_DIRECTORY|O_NOFOLLOW on one); the open that
    # follows is still O_NOFOLLOW, so a swap in between is refused, not followed.
    try:
        st = os.stat(name, dir_fd=fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise TaskError(f"{_safe(here)}: {exc.strerror}") from exc
    if stat.S_ISLNK(st.st_mode):
        raise TaskError(f"{_safe(here)} is a symbolic link; tjor will not follow a link below the notes root "
                        f"(replace it with a real directory)")
    if not stat.S_ISDIR(st.st_mode):
        raise TaskError(f"{_safe(here)} exists but is not a directory")
    try:
        return os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
    except FileNotFoundError:
        return None
    except NotADirectoryError as exc:
        raise TaskError(f"{_safe(here)} exists but is not a directory") from exc
    except OSError as exc:
        import errno
        if exc.errno in (errno.ELOOP, errno.EMLINK):
            raise TaskError(f"{_safe(here)} is a symbolic link; tjor will not follow a link below the notes root "
                            f"(replace it with a real directory)") from exc
        raise TaskError(f"{_safe(here)}: {exc.strerror}") from exc


# --------------------------------------------------------------- contains

def _plain_path(path: str, what: str) -> None:
    """The launcher passes physical, absolute paths (`pwd -P`, the resolved
    notes prefix); a `.` or `..` component is refused rather than collapsed
    (shared rule: tjor_paths)."""
    tjor_paths.plain_path(path, what, TaskError)


def _lstat_real_dir(path: str, what: str) -> os.stat_result:
    """lstat a path that must exist and be a real directory: a link is an
    error, never followed (the launcher's paths are physical; a link here
    means something was swapped since), as is anything else (tjor_paths)."""
    st = tjor_paths.lstat_dir(path, what, TaskError)
    if st is None:
        raise TaskError(f"cannot read {what} {_safe(path)}: no such directory")
    return st


def _chain_keys(path: str, what: str) -> list[tuple[int, int]]:
    """The identities of `path` and every directory above it, leaf first,
    each lstat'ed and required to be a real directory."""
    keys: list[tuple[int, int]] = []
    cur = os.path.abspath(path)
    while True:
        st = _lstat_real_dir(cur, what)
        keys.append((st.st_dev, st.st_ino))
        parent = os.path.dirname(cur)
        if parent == cur:
            return keys
        cur = parent


def contains(ancestor: str, path: str) -> bool:
    """True when `ancestor` is `path` or one of its ancestors, judged by
    (st_dev, st_ino) along the parent chain, never by the path string (a
    case-folding or normalising filesystem makes two spellings one directory).
    Both chains are walked without following a link: a link anywhere, a `.`
    or `..` component, or a step whose identity cannot be read raises
    TaskError, so the caller refuses rather than reads "no"."""
    check_capabilities()
    _plain_path(ancestor, "the ancestor")
    _plain_path(path, "the path")
    key = _chain_keys(ancestor, "a directory on the ancestor's chain")[0]
    return key in _chain_keys(path, "a directory on the path's chain")


# ------------------------------------------------------------------ probe

def _open_dir_nofollow(path: str) -> int:
    try:
        return os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as exc:
        raise TaskError(f"{_safe(path)}: {exc.strerror} (a symbolic link is refused)") from exc


def probe_create(directory: str) -> str:
    """An empty 0600 file with an unpredictable name, created O_EXCL relative
    to the directory's descriptor. The launcher binds the directory into a
    throwaway container, which must see this name."""
    check_capabilities()
    fd = _open_dir_nofollow(directory)
    try:
        name = PROBE_PREFIX + secrets.token_hex(8)
        pfd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
        os.close(pfd)
        return name
    except OSError as exc:
        raise TaskError(f"cannot create a share probe in {_safe(directory)}: {exc.strerror}") from exc
    finally:
        os.close(fd)


def probe_remove(directory: str, name: str) -> None:
    check_capabilities()
    if not PROBE_NAME.fullmatch(name):
        raise TaskError(f"refusing to remove {_safe(name)!r}: not a share probe name")
    fd = _open_dir_nofollow(directory)
    try:
        os.unlink(name, dir_fd=fd)
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise TaskError(f"cannot remove the share probe {_safe(name)}: {exc.strerror}") from exc
    finally:
        os.close(fd)


# ------------------------------------------------------------------- scan

def name_reasons(name: str) -> list[str]:
    base = name.lower()
    reasons = []
    segs = [s for s in re.split(r"[._-]+", base) if s]
    hit = [s for s in segs if s in NAME_SEGMENTS]
    if hit:
        reasons.append(f"name has the segment {hit[0]!r}")
    for suffix in NAME_SUFFIXES:
        if base.endswith(suffix):
            reasons.append(f"name ends in {suffix}")
            break
    if base.startswith("id_"):
        reasons.append("name starts with id_ (an SSH key?)")
    return reasons


def scan(root: str) -> tuple[list[tuple[str, str]], list[str]]:
    """(findings, partial): findings are (relative path, reason); partial lists
    every bound hit and every entry skipped, so a scan that saw less than the
    whole tree never reads as clean."""
    check_capabilities()
    findings: list[tuple[str, str]] = []
    partial: list[str] = []
    counters = {"entries": 0, "bytes": 0, "total_said": False}

    def walk(fd: int, rel: str, depth: int) -> bool:
        """False when the entry bound stopped the scan."""
        if depth > SCAN_MAX_DEPTH:
            partial.append(f"{rel}: deeper than {SCAN_MAX_DEPTH} levels, not scanned")
            return True
        try:
            it = os.scandir(fd)
        except OSError as exc:
            partial.append(f"{rel or '.'}: unreadable ({exc.strerror})")
            return True
        with it:
            for entry in it:
                counters["entries"] += 1
                if counters["entries"] > SCAN_MAX_ENTRIES:
                    partial.append(f"more than {SCAN_MAX_ENTRIES} entries, scan stopped")
                    return False
                name = entry.name
                path = f"{rel}/{name}" if rel else name
                try:
                    is_link = entry.is_symlink()
                    is_dir = entry.is_dir(follow_symlinks=False)
                    is_file = entry.is_file(follow_symlinks=False)
                except OSError as exc:
                    partial.append(f"{path}: unreadable ({exc.strerror})")
                    continue
                if is_link:
                    partial.append(f"{path}: symbolic link, skipped")
                    continue
                if is_dir:
                    if name == ".git":
                        continue
                    try:
                        child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                    except OSError as exc:
                        partial.append(f"{path}: unreadable ({exc.strerror})")
                        continue
                    try:
                        if not walk(child, path, depth + 1):
                            return False
                    finally:
                        os.close(child)
                    continue
                if not is_file:
                    partial.append(f"{path}: not a regular file, skipped")
                    continue
                reasons = name_reasons(name) + _content_reasons(fd, name, path, counters, partial)
                for reason in reasons:
                    findings.append((path, reason))
        return True

    fd = _open_dir_nofollow(root)
    try:
        walk(fd, "", 0)
    finally:
        os.close(fd)
    return findings, partial


def _content_reasons(fd: int, name: str, path: str, counters: dict, partial: list[str]) -> list[str]:
    try:
        ffd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    except OSError as exc:
        partial.append(f"{path}: unreadable ({exc.strerror})")
        return []
    try:
        st = os.fstat(ffd)
        if not stat.S_ISREG(st.st_mode):
            partial.append(f"{path}: not a regular file, skipped")
            return []
        if st.st_size > SCAN_MAX_FILE:
            partial.append(f"{path}: larger than {SCAN_MAX_FILE // 1024} KiB, content not scanned")
            return []
        if counters["bytes"] + st.st_size > SCAN_MAX_TOTAL:
            if not counters["total_said"]:
                partial.append(f"{SCAN_MAX_TOTAL // (1024 * 1024)} MiB of content read, further content not scanned")
                counters["total_said"] = True
            return []
        chunks = []
        remaining = st.st_size
        while remaining > 0:
            chunk = os.read(ffd, min(remaining, 65536))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        counters["bytes"] += len(data)
    except OSError as exc:
        partial.append(f"{path}: unreadable ({exc.strerror})")
        return []
    finally:
        os.close(ffd)
    text = data.decode("utf-8", "replace")
    return [f"content looks like a {kind}" for kind in tjor_secrets.kinds_present(text)]


# -------------------------------------------------------------------- CLI

def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="tjor_task", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("resolve"); p.add_argument("--template", required=True); p.add_argument("--task", required=True)
    p = sub.add_parser("create"); p.add_argument("--prefix", required=True); p.add_argument("--relative", required=True)
    p.add_argument("--no-create", action="store_true")
    p = sub.add_parser("contains"); p.add_argument("ancestor"); p.add_argument("path")
    p = sub.add_parser("probe-create"); p.add_argument("directory")
    p = sub.add_parser("probe-remove"); p.add_argument("directory"); p.add_argument("name")
    p = sub.add_parser("scan"); p.add_argument("directory")
    args = parser.parse_args(argv)
    try:
        check_capabilities()
        if args.cmd == "resolve":
            path, physical, rel = resolve(args.template, args.task)
            print(path); print(physical); print("/".join(rel))
        elif args.cmd == "create":
            dev, ino = create(args.prefix, args.relative.split("/"), not args.no_create)
            print(f"{dev}:{ino}")
        elif args.cmd == "contains":
            return 0 if contains(args.ancestor, args.path) else NOT_CONTAINED
        elif args.cmd == "probe-create":
            print(probe_create(args.directory))
        elif args.cmd == "probe-remove":
            probe_remove(args.directory, args.name)
        elif args.cmd == "scan":
            findings, partial = scan(args.directory)
            for path, reason in findings:
                print(f"{_safe(path)}\t{_safe(reason)}")
            for reason in partial:
                print(f"partial\t{_safe(reason)}")
        return 0
    except TaskError as exc:
        print(f"tjor_task: {exc}", file=sys.stderr)
        return 2 if args.cmd == "contains" else 1
    except Exception as exc:  # noqa: BLE001 — fail closed: an unexpected fault is a refusal, never an answer
        print(f"tjor_task: internal error, refusing ({type(exc).__name__}: {exc})", file=sys.stderr)
        return 2 if args.cmd == "contains" else 1


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
