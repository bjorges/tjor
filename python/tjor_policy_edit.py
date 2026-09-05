"""Add a host to a policy file's hosts.allow, preserving the rest of the file
(comments included) by a text-surgical insert. Validates the result parses;
refuses to write an unparseable policy."""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import tjor_policy


def add_hosts(path: str, hosts: list[str]) -> None:
    text = Path(path).read_text() if Path(path).is_file() else ""
    # Insert right after the opening bracket of hosts.allow, so existing
    # entries and comments are untouched.
    m = re.search(r"\[hosts\][\s\S]*?allow\s*=\s*\[", text)
    if m:
        insert = "".join(f'\n  "{h}",' for h in hosts)
        text = text[: m.end()] + insert + text[m.end():]
    else:
        block = "".join(f'  "{h}",\n' for h in hosts)
        text = text.rstrip() + f"\n\n[hosts]\nallow = [\n{block}]\n"

    parsed = tjor_policy.parse_policy(text, source=path)
    if not parsed.valid:
        raise SystemExit(f"tjor_policy_edit: refusing to write an invalid policy: {parsed.errors}")

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text)


def _main(argv: list[str]) -> int:
    if len(argv) < 3 or argv[0] != "add":
        print("usage: tjor_policy_edit add <policy-file> <host> [host...]", file=sys.stderr)
        return 2
    add_hosts(argv[1], argv[2:])
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
