"""tjor session identity: the vendor-neutral ``x-agent-*`` wire schema.

The schema is CLOSED: exactly the headers below exist. At the proxy, every
outbound ``x-agent-*`` header is checked against the session's registered
identity — mismatched, unknown, or unregistered headers are stripped, so a
session structurally cannot impersonate another. Injection of the identity
set happens only for hosts on the explicit ``identity.inject_hosts``
allowlist (matched with the shared policy host matcher — no second matcher).

Fail-closed: an invalid or missing identity strips every ``x-agent-*``
header from every request.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

sys.path.insert(0, str(Path(__file__).resolve().parent))

import tjor_policy

# wire header -> environment variable carrying the value
SCHEMA: dict[str, str] = {
    "x-agent-session-id": "TJOR_SESSION_ID",
    "x-agent-task-id": "TJOR_TASK_ID",
    "x-agent-harness": "TJOR_HARNESS",
    "x-agent-repo": "TJOR_REPO",
    "x-agent-worktree": "TJOR_WORKTREE",
    "x-agent-parent-session": "TJOR_PARENT_SESSION",
}

_VALUE_RE = re.compile(r"^[\x21-\x7e][\x20-\x7e]{0,254}[\x21-\x7e]$|^[\x21-\x7e]$")


@dataclass
class Identity:
    """valid=False means: no identity claims are trusted — strip everything."""

    valid: bool
    values: dict[str, str] = field(default_factory=dict)  # header name -> value
    errors: list[str] = field(default_factory=list)


def load_identity(env: Mapping[str, str]) -> Identity:
    """Build the session identity from environment variables. The session id
    is mandatory; other fields are optional and omitted when unset. Any
    malformed value invalidates the whole identity (fail-closed)."""
    values: dict[str, str] = {}
    errors: list[str] = []
    for header, var in SCHEMA.items():
        raw = env.get(var, "")
        if not raw:
            continue
        if not _VALUE_RE.match(raw):
            errors.append(f"{var} has a malformed value")
            continue
        values[header] = raw
    if "x-agent-session-id" not in values:
        errors.append("TJOR_SESSION_ID missing or malformed")
    if errors:
        return Identity(valid=False, errors=errors)
    return Identity(valid=True, values=values)


def parse_inject_hosts(raw: str) -> list[str]:
    """Comma/whitespace-separated host globs."""
    return [h for h in re.split(r"[,\s]+", raw.strip()) if h]


def should_inject(inject_hosts: list[str], host: str) -> bool:
    return any(tjor_policy.host_matches(pattern, host) for pattern in inject_hosts)


def transform(
    identity: Identity, existing: Mapping[str, str], inject: bool
) -> tuple[dict[str, str], dict[str, str]]:
    """Decide the fate of a request's ``x-agent-*`` headers.

    ``existing`` maps lowercase header names to values for every x-agent-*
    header currently on the request. Returns ``(final, stripped)``:
    ``final`` is the complete set the request must carry afterwards
    (everything x-agent-* not in it is removed), ``stripped`` the forged or
    unknown headers that were removed (for logging).
    """
    stripped: dict[str, str] = {}
    final: dict[str, str] = {}

    if not identity.valid:
        return {}, dict(existing)

    for name, value in existing.items():
        if identity.values.get(name) == value:
            final[name] = value
        else:
            stripped[name] = value  # unknown header, mismatch, or unregistered field

    if inject:
        final = dict(identity.values)

    return final, stripped
