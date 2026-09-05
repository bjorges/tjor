#!/usr/bin/env python3
"""Host-side staging for agent profiles (#29).

A profile is a host directory of harness DEFINITIONS (agents/commands/skills)
the operator opts into bringing to a caged session. To do that WITHOUT
importing host credentials, the launcher stages only an allow-list of
definition subdirectories into a per-session dir; only that staged dir is ever
exposed to the container. So an `auth.json` / API key sitting beside the
definitions (e.g. in `~/.opencode`) is never copied and never crosses the cage
boundary — the filtering happens here, on the host, before anything is mounted.

Allow-list, not block-list: an unknown top-level file (including a
future-invented secret filename) is skipped by default, which fails safe.
Symlinks that resolve outside the profile source are refused, so a definition
dir can't smuggle out `~/.ssh/id_rsa` via a planted link.
"""
import os
import pathlib
import shutil
import sys

# Definition subdirectories a profile may contribute (harness conventions vary:
# opencode uses singular agent/command; others differ). Everything else in the
# source — auth.json, *.credentials*, API keys, dotfiles, unknown files — is
# never staged.
ALLOWED = (
    "agent", "agents", "command", "commands", "skill", "skills",
    "prompt", "prompts", "mode", "modes",
)


def _within(base, path):
    """True if `path` (after resolving symlinks) is inside `base`."""
    base = pathlib.Path(base).resolve()
    try:
        pathlib.Path(path).resolve().relative_to(base)
        return True
    except (ValueError, OSError):
        return False


def stage(source, dest):
    """Copy the allow-listed definition subdirs from `source` into `dest`
    (cleared first, so a previous session's profile never lingers). Returns the
    sorted list of relative paths staged. A file whose real path escapes
    `source` (an out-of-tree symlink) is skipped."""
    source = pathlib.Path(source).resolve()
    dest = pathlib.Path(dest)
    if dest.is_symlink() or (dest.exists() and not dest.is_dir()):
        dest.unlink()
    elif dest.is_dir():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)

    staged = []
    for name in ALLOWED:
        top = source / name
        # A top-level allow-listed entry that is a symlink (e.g. agent -> /etc)
        # is refused outright — only a real directory qualifies.
        if top.is_symlink() or not top.is_dir():
            continue
        for root, dirs, files in os.walk(top):  # followlinks=False (default)
            rootp = pathlib.Path(root)
            # Never descend into a symlinked subdirectory.
            dirs[:] = [d for d in dirs if not (rootp / d).is_symlink()]
            for fname in files:
                sp = rootp / fname
                try:
                    real = sp.resolve()
                except OSError:
                    continue
                # Skip anything whose content lives outside the profile source.
                if not real.is_file() or not _within(source, real):
                    continue
                rel = sp.relative_to(source)
                dp = dest / rel
                dp.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(sp, dp)  # copies content, never the symlink
                staged.append(str(rel))
    return sorted(staged)


def _main(argv):
    if len(argv) == 4 and argv[1] == "stage":
        staged = stage(argv[2], argv[3])
        if staged:
            sys.stdout.write("\n".join(staged) + "\n")
        return
    sys.exit("usage: tjor_profile.py stage <source> <dest>")


if __name__ == "__main__":
    _main(sys.argv)
