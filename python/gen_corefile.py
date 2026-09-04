"""Generate the CoreDNS Corefile from the egress policy (charter L21).

Zones are derived from the policy's host allow-list: `*.example.com` and
`example.com` both yield the forwarded zone `example.com`. Every other zone
is answered NXDOMAIN locally — DNS is an egress channel, and unlisted zones
must fail closed, never forward through.

In default-allow mode zones cannot be derived; an explicit `dns.extra_zones`
list in the config is required, otherwise ONLY those zones forward (nothing,
if empty) — loud in output, closed in behavior.

An invalid policy yields a Corefile that forwards nothing at all.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import tjor_cfg
import tjor_policy

_ZONE_RE = re.compile(r"^[a-z0-9.\-]+$")


def zones_from_policy(policy: tjor_policy.Policy, extra_zones: list[str]) -> tuple[list[str], list[str]]:
    """Return (zones, warnings)."""
    warnings: list[str] = []
    zones: list[str] = []

    def add(zone: str, origin: str) -> None:
        zone = zone.strip().casefold().strip(".")
        if not zone:
            return
        if not _ZONE_RE.match(zone):
            warnings.append(f"cannot zone-scope pattern {origin!r}; DNS for it stays closed")
            return
        if zone not in zones:
            zones.append(zone)

    if not policy.valid:
        warnings.append("policy invalid: forwarding NO zones (fail-closed)")
        return [], warnings

    if policy.mode == "strict-allow":
        for pattern in policy.host_allow:
            stripped = pattern.removeprefix("*.")
            if "*" in stripped or "?" in stripped:
                warnings.append(f"cannot zone-scope pattern {pattern!r}; DNS for it stays closed")
                continue
            add(stripped, pattern)
    else:
        warnings.append("default-allow mode: DNS forwards only dns.extra_zones")

    for zone in extra_zones:
        add(zone, zone)
    return zones, warnings


def render(zones: list[str]) -> str:
    blocks = []
    if zones:
        keys = " ".join(f"{z}:53" for z in zones)
        blocks.append(keys + " {\n    forward . /etc/resolv.conf\n    errors\n}\n")
    blocks.append(".:53 {\n    template ANY ANY {\n        rcode NXDOMAIN\n    }\n    errors\n}\n")
    return "\n".join(blocks)


def main(argv: list[str]) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="gen_corefile")
    parser.add_argument("--policy", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    policy = tjor_policy.load_policy(args.policy)
    extra = tjor_cfg.get(tjor_cfg.effective(), "dns.extra_zones", []) or []
    zones, warnings = zones_from_policy(policy, extra)
    for warning in warnings:
        print(f"gen_corefile: {warning}", file=sys.stderr)
    Path(args.out).write_text(render(zones))
    print(f"gen_corefile: forwarding {len(zones)} zone(s): {', '.join(zones) or '(none)'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
