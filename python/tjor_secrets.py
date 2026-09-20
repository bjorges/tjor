#!/usr/bin/env python3
"""Discovered-secret detector (#6): redact already-existing secrets that the
agent may quote from repo content or tool output, so they are not persisted in
the clear in tjor-owned output.

This is the reusable, boundary-agnostic core. It matches only PROVABLY-secret
SHAPES — vendor-token prefixes and PEM private-key blocks — never high-entropy
strings, so UUIDs, git SHAs, base64 blobs, and ordinary prose are returned
unchanged. A false positive in a security tool erodes trust and can corrupt
output, so the bias is deliberately toward under-matching; new shapes are added
here on purpose, not guessed by entropy. See docs/decisions/0010-secret-scrubbing.md
for the risk model, the boundaries considered, and what is (and isn't) wired yet.

Stdlib only — it ships inside the proxy image alongside the other tjor_*.py.
"""
from __future__ import annotations

import re
import sys

_PLACEHOLDER = "[redacted:{kind}]"

# (kind, compiled pattern). Order matters only for overlapping matches; these
# shapes don't overlap. Each is anchored on a distinctive, high-confidence
# prefix/format so a match is a secret, not a coincidence.
_PATTERNS: list[tuple[str, re.Pattern]] = [
    # AWS access key id (long-term AKIA / temporary ASIA) — 16 upper-alnum.
    ("aws-access-key-id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    # GitHub tokens: ghp_/gho_/ghs_/ghr_ (classic, 36+) and github_pat_ (fine-grained).
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,255}\b")),
    ("github-pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{22,255}\b")),
    # Slack tokens: xoxb-/xoxp-/xoxa-/xoxr-/xoxs- …
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    # Google API key.
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    # PEM private-key block (any key type) — redact the WHOLE block, not just a line.
    ("private-key", re.compile(
        r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----.*?-----END (?:[A-Z0-9 ]+ )?PRIVATE KEY-----",
        re.DOTALL)),
]


def redact(text: str) -> str:
    """Return ``text`` with every known secret shape replaced by
    ``[redacted:<kind>]``. Non-secret content is returned unchanged."""
    if not text:
        return text
    for kind, pat in _PATTERNS:
        text = pat.sub(_PLACEHOLDER.format(kind=kind), text)
    return text


def contains_secret(text: str) -> bool:
    """True iff ``text`` contains at least one known secret shape."""
    return bool(text) and any(pat.search(text) for _, pat in _PATTERNS)


def _main(argv: list[str]) -> int:
    # `redact` filter: stdin -> stdout, for shell/manual use.
    if len(argv) >= 2 and argv[1] == "redact":
        sys.stdout.write(redact(sys.stdin.read()))
        return 0
    sys.exit("usage: tjor_secrets.py redact   (redacts stdin -> stdout)")


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
