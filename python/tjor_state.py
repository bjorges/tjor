#!/usr/bin/env python3
"""Session state root helper (#68, specs: session-lifecycle, session-launch).

One definition of the state TIERS — what `tjor reset` deletes, what
`tjor ls --state` flags and what `tjor prune --creds-only` removes — plus the
launch-time metadata file, the state-root inventory and duration parsing. The
launcher (bin/tjor) calls this and keeps the per-session lock, the container
checks and the audited deletion path (ancestors_are_real_dirs) in bash.

Output contract, read by bash (which has no JSON parser and already splits
docker output on the same byte): `tier` prints absolute paths one per line;
`inventory` prints one record per line, fields separated by US (\\x1f), `-`
where a fact is unknown. Every subcommand builds its whole result before
printing anything, so a failure never leaves a partial listing behind; it then
exits non-zero with a message on stderr (2 for usage, 1 for a runtime error).

Last activity is the newest lstat mtime over a state directory and its whole
contents, never following symbolic links (a planted link never pulls an outside
tree's timestamps in, and nothing behind it is read), floored by the recorded
last launch. A directory that could not be fully read reports unknown — never
"old" — so `tjor prune --older-than` cannot sweep what tjor could not see.
"""
from __future__ import annotations

import json
import os
import re
import stat
import sys
import tempfile
import time

SCHEMA = 1
META_NAME = "meta.json"
LOCKS_DIR = ".locks"   # the launcher's per-session locks live beside the state dirs
US = "\x1f"
UNKNOWN = "-"

# Relative to a session's state directory. `all` is the directory itself.
# A credential path added here is covered by reset, ls --state and prune at
# once (spec: "The credential tier is one set").
TIERS: dict[str, tuple[str, ...]] = {
    "cache": ("home/.cache",),
    "sessions": (
        "home/.local/state",
        "home/.local/share/opencode/storage",
        "home/.local/share/opencode/log",
    ),
    "creds": (
        "broker",                                  # broker config + resolved secret (proxy side)
        "proxy-ca",                                # the session's MITM CA key
        "ca.pem",
        "home/.local/share/opencode/auth.json",    # opencode provider auth
        "home/.config/gh",                         # agent-minted gh tokens (hosts.yml, ADR 0007)
        "home/.claude/.credentials.json",          # Claude Code in-cage login (OAuth tokens)
        "home/.claude.json",                       # Claude Code account record
        "home/.claude/backups",                    # ... and its backups
    ),
    "all": ("",),
}

META_KEYS = ("schema", "session", "workspace", "harness", "profile", "task",
             "created", "last_launch", "launches")

_DURATION = re.compile(r"^(\d+)([dhms])$")
_UNITS = {"d": 86400, "h": 3600, "m": 60, "s": 1}


class StateError(Exception):
    """A runtime failure the CLI reports on stderr with exit 1."""


def tier_paths(name: str, state_dir: str) -> list[str]:
    """Absolute paths of a tier under state_dir; `all` is state_dir itself."""
    if name not in TIERS:
        raise KeyError(name)
    return [os.path.join(state_dir, rel) if rel else state_dir for rel in TIERS[name]]


def parse_duration(text: str) -> int:
    """`Nd`, `Nh`, `Nm`, `Ns` -> seconds. Anything else is a ValueError."""
    m = _DURATION.match(text.strip())
    if not m:
        raise ValueError(f"not a duration (expected <N>d, <N>h, <N>m or <N>s): {text!r}")
    return int(m.group(1)) * _UNITS[m.group(2)]


def read_meta(state_dir: str) -> dict | None:
    """The metadata file, or None when absent, unreadable, or a symlink
    (legacy state reads as unknown; a planted link is never followed)."""
    try:
        fd = os.open(os.path.join(state_dir, META_NAME), os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return None
    try:
        with os.fdopen(fd, encoding="utf-8") as f:
            meta = json.load(f)
    except (OSError, ValueError):
        return None
    return meta if isinstance(meta, dict) else None


def activity(state_dir: str) -> int | None:
    """Last activity of one state directory, as the inventory computes it:
    the full lstat walk floored by the recorded last launch; None if unknown."""
    last = last_activity(state_dir)
    meta = read_meta(state_dir) or {}
    if last is not None and isinstance(meta.get("last_launch"), int):
        last = max(last, meta["last_launch"])
    return last


def lock_try(fd: int, path: str) -> int:
    """Take an exclusive, non-blocking flock on an inherited descriptor.
    The lock belongs to the OPEN FILE DESCRIPTION the launcher keeps open, so
    it outlives this process and the kernel drops it when every descriptor
    on it closes - a crashed holder leaves nothing stale. The descriptor must
    be the regular file at `path` (the launcher opened the path; a symlink
    planted there must never be followed, so the path is lstat'ed and must
    be the same inode as the descriptor). On success the file is emptied
    through the descriptor, so the caller's owner line - appended through
    the same descriptor - is the only content. 0 = acquired, 1 = held
    elsewhere, 2 = the descriptor or the path is not usable."""
    import fcntl
    import stat
    try:
        st = os.lstat(path)
        if not stat.S_ISREG(st.st_mode):
            print(f"tjor_state: lock-try: {path} is not a regular file (a symlink is never followed)", file=sys.stderr)
            return 2
        fst = os.fstat(fd)
        if (st.st_dev, st.st_ino) != (fst.st_dev, fst.st_ino):
            print(f"tjor_state: lock-try: descriptor {fd} is not the file at {path}", file=sys.stderr)
            return 2
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return 1
    except OSError as e:
        print(f"tjor_state: lock-try: {e}", file=sys.stderr)
        return 2
    try:
        os.ftruncate(fd, 0)   # ours now: the previous holder's line goes
    except OSError as e:
        print(f"tjor_state: lock-try: cannot reset {path}: {e}", file=sys.stderr)
        return 2
    return 0


def write_meta(state_dir: str, *, session: str, workspace: str, harness: str,
               profile_name: str = "", profile_dir: str = "", task: str = "",
               now: int | None = None) -> dict:
    """Read-modify-write meta.json atomically: `created` and `launches` carry
    over from an existing readable file; an unreadable one is replaced. The
    temp file is created INSIDE state_dir so os.replace never crosses a
    filesystem. Holds no secret: only the documented keys are written."""
    now = int(time.time()) if now is None else now
    old = read_meta(state_dir) or {}
    created = old.get("created") if isinstance(old.get("created"), int) else now
    launches = old.get("launches") + 1 if isinstance(old.get("launches"), int) else 1
    profile: dict | None = None
    if profile_name:
        profile = {"name": profile_name}
    elif profile_dir:
        profile = {"dir": profile_dir}
    meta = {
        "schema": SCHEMA,
        "session": session,
        "workspace": workspace,
        "harness": harness,
        "profile": profile,
        "task": task or None,
        "created": created,
        "last_launch": now,
        "launches": launches,
    }
    fd, tmp = tempfile.mkstemp(prefix=".meta.", suffix=".tmp", dir=state_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=1, sort_keys=True)
            f.write("\n")
        os.chmod(tmp, 0o644)
        os.replace(tmp, os.path.join(state_dir, META_NAME))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return meta


def last_activity(path: str) -> int | None:
    """Newest lstat mtime over path and everything below it, never following
    symlinks. None when any directory or entry could not be read."""
    errors: list[BaseException] = []
    try:
        newest = os.lstat(path).st_mtime
    except OSError:
        return None
    for dirpath, dirnames, filenames in os.walk(path, topdown=True, onerror=errors.append, followlinks=False):
        for name in dirnames + filenames:
            try:
                newest = max(newest, os.lstat(os.path.join(dirpath, name)).st_mtime)
            except OSError as e:
                errors.append(e)
    return None if errors else int(newest)


def creds_present(state_dir: str) -> list[str]:
    """The credential-tier paths that exist (a dangling symlink counts: reset
    would remove it), relative, in tier order."""
    return [rel for rel in TIERS["creds"] if os.path.lexists(os.path.join(state_dir, rel))]


def inventory(root: str) -> list[dict]:
    """One record per entry of root (sorted by name), skipping the lock dir.
    Nothing behind a symlink entry is read."""
    records: list[dict] = []
    for name in sorted(os.listdir(root)):
        if name == LOCKS_DIR:
            continue
        path = os.path.join(root, name)
        st = os.lstat(path)
        rec = {"id": name, "kind": "other", "workspace": None, "harness": None,
               "last_active": None, "launches": None, "creds": []}
        if stat.S_ISLNK(st.st_mode):
            rec["kind"] = "link"
        elif stat.S_ISDIR(st.st_mode):
            rec["kind"] = "dir"
            meta = read_meta(path) or {}
            rec["workspace"] = meta.get("workspace") if isinstance(meta.get("workspace"), str) else None
            rec["harness"] = meta.get("harness") if isinstance(meta.get("harness"), str) else None
            rec["launches"] = meta.get("launches") if isinstance(meta.get("launches"), int) else None
            rec["last_active"] = activity(path)
            rec["creds"] = creds_present(path)
        records.append(rec)
    return records


def _field(value) -> str:
    if value is None or value == [] or value == "":
        return UNKNOWN
    if isinstance(value, list):
        return ",".join(value)
    return str(value)


def format_record(rec: dict) -> str:
    """The \\x1f-separated line bash reads: id, kind, workspace, harness,
    last_active, launches, creds. A field may not contain US or newline."""
    fields = [rec["id"], rec["kind"], rec["workspace"], rec["harness"],
              rec["last_active"], rec["launches"], rec["creds"]]
    out = [_field(v) for v in fields]
    for v in out:
        if US in v or "\n" in v:
            raise StateError(f"record field contains a separator byte: {rec['id']!r}")
    return US.join(out)


def _opt(argv: list[str], flag: str) -> str:
    if flag in argv:
        i = argv.index(flag)
        if i + 1 >= len(argv):
            raise StateError(f"{flag} needs a value")
        return argv[i + 1]
    return ""


USAGE = ("usage: tjor_state.py tier {cache|sessions|creds|all} STATE_DIR"
         " | duration TEXT"
         " | meta-write STATE_DIR --session ID --workspace PATH --harness NAME"
         " [--profile-name NAME | --profile-dir PATH] [--task ID]"
         " | inventory ROOT | activity STATE_DIR | lock-try FD PATH")


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else ""
    try:
        if cmd == "tier" and len(argv) == 4:
            try:
                paths = tier_paths(argv[2], argv[3])
            except KeyError:
                print(f"tjor_state: unknown tier {argv[2]!r} (cache, sessions, creds, all)", file=sys.stderr)
                return 2
            print("\n".join(paths))
            return 0
        if cmd == "duration" and len(argv) == 3:
            try:
                print(parse_duration(argv[2]))
            except ValueError as e:
                print(f"tjor_state: {e}", file=sys.stderr)
                return 2
            return 0
        if cmd == "meta-write" and len(argv) >= 3:
            session, workspace, harness = (_opt(argv, "--session"), _opt(argv, "--workspace"), _opt(argv, "--harness"))
            if not (session and workspace and harness):
                print(USAGE, file=sys.stderr)
                return 2
            write_meta(argv[2], session=session, workspace=workspace, harness=harness,
                       profile_name=_opt(argv, "--profile-name"), profile_dir=_opt(argv, "--profile-dir"),
                       task=_opt(argv, "--task"))
            return 0
        if cmd == "inventory" and len(argv) == 3:
            lines = [format_record(r) for r in inventory(argv[2])]   # all or nothing
            if lines:
                print("\n".join(lines))
            return 0
        if cmd == "activity" and len(argv) == 3:
            if not os.path.isdir(argv[2]):
                print(f"tjor_state: not a directory: {argv[2]}", file=sys.stderr)
                return 1
            print(_field(activity(argv[2])))
            return 0
        if cmd == "lock-try" and len(argv) == 4 and argv[2].isdigit():
            return lock_try(int(argv[2]), argv[3])
    except (OSError, StateError) as e:
        print(f"tjor_state: {e}", file=sys.stderr)
        return 1
    print(USAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
