#!/usr/bin/env python3
"""Path hygiene shared by the launcher's helpers (tjor_launch.py and
tjor_task.py). The launcher passes physical, absolute paths (`pwd -P`, a
resolved notes prefix) and the helpers judge filesystem identity along a
chain they walk with lstat. The two rules every such walk needs live here,
so a fix is made once:

  plain_path(path, what, error)   refuse a relative path and any `.` or `..`
                                  component: `L/../x` with `L` a link is `x`
                                  beside `L` lexically, and a walk would
                                  never see `L`
  lstat_dir(path, what, error)    lstat a path that must be a real directory:
                                  None when absent, `error` on a link (never
                                  followed), on a non-directory and on any
                                  other OSError

`error` is the caller's refusal class (LaunchError, TaskError), so each CLI
keeps its own exit-code contract.
"""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import tjor_safeprint  # noqa: E402


def safe(text: str) -> str:
    return tjor_safeprint.sanitize(str(text)).replace("\t", "\\t").replace("\n", "\\n")


def plain_path(path: str, what: str, error: type[Exception]) -> None:
    if not path.startswith("/"):
        raise error(f"{what} {safe(path)} is not an absolute path")
    for comp in path.split("/"):
        if comp in (".", ".."):
            raise error(f"{what} {safe(path)} holds a {comp!r} component; the launcher passes physical paths, "
                        "and a lexical '..' could hide a link above it")


def lstat_dir(path: str, what: str, error: type[Exception]):
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise error(f"cannot read {what} {safe(path)}: {exc.strerror}") from exc
    if stat.S_ISLNK(st.st_mode):
        raise error(f"{what} {safe(path)} is a symbolic link; it is never followed")
    if not stat.S_ISDIR(st.st_mode):
        raise error(f"{what} {safe(path)} exists but is not a directory")
    return st
