"""tjor repo-config trust store.

A repo may carry `.tjor/config.toml` / `.tjor/policy.toml`, but such a file
can widen the security boundary (allowlist a host, set a broker), so it is
honored only after the user approves its exact current content. Approval is
pinned by content hash in ~/.config/tjor/trusted.toml; editing the file
revokes trust until re-approved.
"""

from __future__ import annotations

import hashlib
import os
import sys
import tomllib
from pathlib import Path


def store_path() -> Path:
    env = os.environ.get("TJOR_TRUST_STORE")
    if env:
        return Path(env)
    xdg = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    return Path(xdg) / "tjor" / "trusted.toml"


def content_hash(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _load_store() -> dict:
    p = store_path()
    if not p.is_file():
        return {}
    try:
        with open(p, "rb") as fh:
            return tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def is_trusted(path: str | Path) -> bool:
    resolved = str(Path(path).resolve())
    try:
        h = content_hash(resolved)
    except OSError:
        return False
    return _load_store().get("trusted", {}).get(resolved) == h


def approve(path: str | Path) -> str:
    resolved = str(Path(path).resolve())
    h = content_hash(resolved)
    store = _load_store()
    trusted = dict(store.get("trusted", {}))
    trusted[resolved] = h
    out = store_path()
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = ["[trusted]"]
    for k, v in sorted(trusted.items()):
        esc = k.replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'"{esc}" = "{v}"')
    tmp = out.with_suffix(".tmp")
    tmp.write_text("\n".join(lines) + "\n")
    os.chmod(tmp, 0o600)
    tmp.replace(out)
    return h


def _main(argv: list[str]) -> int:
    if not argv:
        print("usage: tjor_trust {check|approve|hash} <path>", file=sys.stderr)
        return 2
    cmd, rest = argv[0], argv[1:]
    if cmd == "check":
        return 0 if is_trusted(rest[0]) else 1
    if cmd == "approve":
        print(approve(rest[0]))
        return 0
    if cmd == "hash":
        try:
            print(content_hash(rest[0]))
            return 0
        except OSError as exc:
            print(f"tjor_trust: {exc}", file=sys.stderr)
            return 1
    print(f"tjor_trust: unknown command {cmd!r}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
