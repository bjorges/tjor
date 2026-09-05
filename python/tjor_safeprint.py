#!/usr/bin/env python3
"""Render untrusted bytes safe to print to a terminal.

Escape-sequence-injection defense. Content tjor shows the operator for a TRUST
decision — a repo's `.tjor` config/policy about to be approved — or any
attacker-influenced value echoed to the terminal (a denied hostname in the
session denial log) must never reach the terminal as raw control bytes. ANSI/OSC
escapes (`ESC ...`) can hide, overwrite, or spoof what is displayed; Unicode
bidi overrides (`U+202E ...`) can visually reorder it. Either lets the operator
approve content different from what they believe they saw — defeating the
content-hash trust gate, since the hash pins exactly the bytes that were
misrepresented.

So every C0 control (except newline and tab, which cannot drive an escape
sequence), DEL, the C1 range, and Unicode format/bidi/other-control code points
are rendered as a VISIBLE token (`^[` for ESC, `<U+202E>` for a bidi override);
printable text, including legitimate multi-byte UTF-8, passes through unchanged.
Raw undecodable bytes are preserved via surrogateescape and then escaped, so the
filter never crashes and never silently drops input.
"""
from __future__ import annotations

import sys
import unicodedata


def _escape(ch: str) -> str:
    o = ord(ch)
    if ch in ("\n", "\t"):
        return ch
    # surrogateescape smuggles a raw undecodable byte 0x80..0xFF as U+DC80..U+DCFF
    if 0xDC80 <= o <= 0xDCFF:
        return f"<0x{o - 0xDC00:02x}>"
    if o < 0x20:                     # C0 controls -> caret notation (^[ == ESC)
        return f"^{chr(o + 0x40)}"
    if o == 0x7F:                    # DEL
        return "^?"
    if 0x80 <= o <= 0x9F:            # C1 controls
        return f"<0x{o:02x}>"
    # Cc control, Cf format (incl. bidi overrides/zero-width), lone surrogates,
    # private-use, unassigned — anything that can hide or reorder the display.
    if unicodedata.category(ch) in ("Cc", "Cf", "Cs", "Co", "Cn"):
        return f"<U+{o:04X}>"
    return ch


def sanitize(text: str) -> str:
    """Return text with every terminal-control code point rendered visible."""
    return "".join(_escape(c) for c in text)


def _main(argv: list[str]) -> int:
    # A file argument, else stdin. Decode with surrogateescape so undecodable
    # bytes are preserved (then escaped), never crashing on binary input.
    try:
        if argv:
            with open(argv[0], "rb") as fh:
                data = fh.read()
        else:
            data = sys.stdin.buffer.read()
    except OSError as exc:
        print(f"tjor_safeprint: {exc}", file=sys.stderr)
        return 1
    sys.stdout.write(sanitize(data.decode("utf-8", "surrogateescape")))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
