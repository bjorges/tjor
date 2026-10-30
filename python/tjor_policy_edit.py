"""Add a host to a policy file's hosts.allow, preserving the rest of the file
(comments included) by a text-surgical insert. Validates the result parses;
refuses to write an unparseable policy."""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import tjor_policy


# Line-anchored, CRLF-tolerant: `$` sits before the `\n`, so a `\r` must be
# allowed in front of it or a file with Windows line endings would read as
# having no `[hosts]` table and gain a second one (a TOML error, loud but a
# regression). A table header may be indented (TOML allows it) and must be a
# whole line: `^\[` alone would also stop at an array continuation line.
# The header match ends BEFORE the `\r` (a lookahead), so an insertion at
# its end keeps the line ending whole.
_HOSTS_HEADER = re.compile(r"^[ \t]*\[hosts\][ \t]*(?:#[^\r\n]*)?(?=\r?$)", re.M)
_NEXT_TABLE = re.compile(r"^[ \t]*\[\[?[^\[\]\r\n]+\]\]?[ \t]*(?:#[^\r\n]*)?\r?$", re.M)
_ALLOW_OPEN = re.compile(r"^[ \t]*allow[ \t]*=[ \t]*\[", re.M)


def add_hosts(path: str, hosts: list[str]) -> None:
    text = Path(path).read_text(newline="") if Path(path).is_file() else ""
    nl = "\r\n" if "\r\n" in text else "\n"        # keep the file's own line endings
    # Three shapes of file (#66, design D9). Only the `[hosts]` table's own
    # `allow` list is an insertion point: a `[[methods.restrict]]` rule has an
    # `allow` list too, and the old "first `allow = [` after `[hosts]`" search
    # could land in it. The table's keys end at the next table header.
    header = _HOSTS_HEADER.search(text)
    if header is None:
        block = "".join(f'  "{h}",{nl}' for h in hosts)
        text = text.rstrip() + f"{nl}{nl}[hosts]{nl}allow = [{nl}{block}]{nl}"
    else:
        body_start = header.end()
        nxt = _NEXT_TABLE.search(text, body_start)
        body_end = nxt.start() if nxt else len(text)
        opening = _ALLOW_OPEN.search(text, body_start, body_end)
        if opening:
            # Insert right after the opening bracket, so existing entries and
            # comments are untouched.
            insert = "".join(f'{nl}  "{h}",' for h in hosts)
            text = text[: opening.end()] + insert + text[opening.end():]
        else:
            # The table exists without an allow list: add the key right after
            # the header (a second [hosts] table would be a TOML error).
            block = "".join(f'  "{h}",{nl}' for h in hosts)
            text = text[:body_start] + f"{nl}allow = [{nl}{block}]" + text[body_start:]

    parsed = tjor_policy.parse_policy(text, source=path)
    if not parsed.valid:
        raise SystemExit(f"tjor_policy_edit: refusing to write an invalid policy: {parsed.errors}")

    # Semantic verification (not just "it parses"): the regex insert can land
    # inside a triple-quoted string — e.g. a documentation/example block — that
    # happens to precede the real [hosts] table. The result is VALID TOML whose
    # true allow-list is unchanged, so the operator would believe a host was
    # added while the boundary is untouched. Re-parse and confirm each host is
    # actually in the effective hosts.allow; refuse loudly if not.
    effective = tomllib.loads(text).get("hosts", {}).get("allow", [])
    missing = [h for h in hosts if h not in effective]
    if missing:
        raise SystemExit(
            "tjor_policy_edit: edit did NOT change the effective hosts.allow for "
            f"{missing} — refusing to write. The allow-list insertion point could "
            "not be located safely (a multi-line string may precede [hosts]); add "
            "the host(s) to hosts.allow by hand."
        )

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, newline="")                 # as composed: no newline translation


def _main(argv: list[str]) -> int:
    if len(argv) < 3 or argv[0] != "add":
        print("usage: tjor_policy_edit add <policy-file> <host> [host...]", file=sys.stderr)
        return 2
    add_hosts(argv[1], argv[2:])
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
