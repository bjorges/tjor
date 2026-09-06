#!/usr/bin/env python3
"""Host-side staging for agent profiles (#29).

A profile is a host directory of harness DEFINITIONS (agents/commands/skills)
the operator opts into bringing to a caged session. The launcher stages only a
structural allow-list of definition subdirectories into a per-session dir; only
that staged dir is ever exposed to the container. Filtering happens here, on the
host, before anything is mounted.

The guarantee, stated precisely:
  * The allow-list is STRUCTURAL — only the definition subdirectories are
    staged, so a credential/config file at the profile ROOT (an `auth.json`,
    `opencode.json`, dotfile, etc., e.g. sitting beside the dirs in
    `~/.opencode`) is never copied. An unknown top-level file is skipped by
    default, which fails safe.
  * As defense in depth, well-known credential filenames and key/cert
    extensions are refused at ANY depth (`agent/auth.json`, `skills/x/id_rsa`,
    `*.pem`) — see `_is_credential_file`.
  * Symlinks whose target resolves outside the profile source are refused, so a
    definition dir can't smuggle out `~/.ssh/id_rsa` via a planted link.

What this does NOT guarantee: tjor cannot tell a definition file from a secret
by content, so a secret deliberately named like a definition (`agent/notes.md`
holding a token) inside a definition dir would pass. A profile is instructions
the agent runs; treat it as trusted content you authored, and do not place
secrets inside a definition directory.
"""
import os
import pathlib
import shutil
import sys

# Definition subdirectories a profile may contribute (harness conventions vary:
# opencode uses singular agent/command; others differ). Everything else at the
# profile ROOT — auth.json, config files, dotfiles, unknown files — is never
# staged (structural allow-list).
ALLOWED = (
    "agent", "agents", "command", "commands", "skill", "skills",
    "prompt", "prompts", "mode", "modes",
)

# Defense in depth WITHIN an allowed subdir: the allow-list is structural (dir
# names), so a credential file nested inside a definition dir — agent/auth.json,
# skills/x/id_rsa — would otherwise be staged. tjor can't tell a definition file
# from a secret by content, but it can refuse well-known credential filenames
# and key/cert extensions at ANY depth. This is a denylist (the structural
# allow-list is the primary gate); a secret deliberately named like a definition
# still can't be distinguished, so the honest guarantee is "definition dirs
# only, minus known credential files" — not "no secret can ever pass".
_CRED_NAMES = frozenset({
    "auth.json", "credentials", "credentials.json", ".credentials.json",
    ".netrc", ".git-credentials", ".npmrc", ".pypirc", ".env", ".dockercfg",
    ".dockerconfigjson", "token.json", ".htpasswd", ".pgpass", ".boto",
    "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519",
    # cloud-provider credential files
    "service-account.json", "application_default_credentials.json",
    "client_secret.json", "clientsecret.json", "gcloud-credentials.json",
    "azureauth.json", "kubeconfig",
})
# Suffixes: private keys, certs, keystores; `-key.json` catches `<name>-key.json`
# service-account exports without matching every `.json` definition file.
_CRED_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".jks", ".keystore", ".ppk",
                  ".crt", ".cer", ".pkcs12", "-key.json")


def _is_credential_file(name):
    """True for well-known credential/secret filenames (case-insensitive)."""
    low = name.lower()
    return low in _CRED_NAMES or low.endswith(_CRED_SUFFIXES)


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
                # Defense in depth: refuse a known credential filename nested
                # anywhere inside a definition dir (agent/auth.json, .../id_rsa).
                if _is_credential_file(fname):
                    continue
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
