"""tjor egress policy engine.

The single matcher used by every call site (proxy addon, launcher preview,
debug CLI). Divergent matcher implementations produce silent policy drift,
so no other component may reimplement any part of this logic; the parity
suite asserts identical verdicts across call sites.

Evaluation order (fixed, tested):

  1. Host blocklist. If the host matches a block pattern, only a path-level
     allow carve-out can save the request — and the carve-out fires only if
     EVERY encoded/decoded form of the path matches it.
  2. Path-level blocks. A block fires if ANY form of the path matches.
  3. Default mode: "strict-allow" requires the host to match the allow
     list; "default-allow" permits everything not blocked above.

The allow/block form-asymmetry is deliberate and load-bearing: a block rule
must be impossible to evade by encoding, an allow rule impossible to widen
by it. Symmetric matching on both sides is itself the vulnerability.

Fail-closed: a policy file that is missing, unparseable, has an unknown
key, or a wrong type yields a policy that denies everything.
"""

from __future__ import annotations

import re
import sys
import tomllib
from dataclasses import dataclass, field
from urllib.parse import unquote, urlsplit

MAX_DECODE_ROUNDS = 4

VALID_MODES = ("strict-allow", "default-allow")
_TOP_KEYS = {"mode", "hosts", "paths"}
_HOSTS_KEYS = {"allow", "block"}
_PATHS_KEYS = {"allow", "block"}
_RULE_KEYS = {"host", "path"}


@dataclass(frozen=True)
class Verdict:
    allowed: bool
    rule: str          # which stage decided, e.g. "host-block", "path-allow-carveout"
    pattern: str = ""  # the pattern that matched, when one did

    def as_dict(self) -> dict:
        return {"allowed": self.allowed, "rule": self.rule, "pattern": self.pattern}


@dataclass
class Policy:
    valid: bool
    mode: str = "strict-allow"
    host_allow: list[str] = field(default_factory=list)
    host_block: list[str] = field(default_factory=list)
    path_allow: list[tuple[str, str]] = field(default_factory=list)  # (host glob, path glob)
    path_block: list[tuple[str, str]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _glob_to_re(pattern: str) -> re.Pattern:
    out = []
    for ch in pattern:
        if ch == "*":
            out.append(".*")
        elif ch == "?":
            out.append(".")
        else:
            out.append(re.escape(ch))
    return re.compile("^" + "".join(out) + "$", re.DOTALL)


def _canon_host(host: str) -> str:
    host = host.strip().casefold().rstrip(".")
    if host.startswith("[") and "]" in host:  # bracketed IPv6, possibly with port
        return host[1 : host.index("]")]
    if host.count(":") == 1:  # strip :port
        maybe_host, maybe_port = host.rsplit(":", 1)
        if maybe_port.isdigit():
            return maybe_host
    return host


def host_matches(pattern: str, host: str) -> bool:
    """Glob host match. ``*`` spans any characters including dots, so
    ``*.example.com`` matches every depth of subdomain but not the apex."""
    return bool(_glob_to_re(pattern.strip().casefold().rstrip(".")).match(_canon_host(host)))


def path_matches(pattern: str, path: str) -> bool:
    return bool(_glob_to_re(pattern).match(path))


def remove_dot_segments(path: str) -> str:
    """RFC 3986 §5.2.4."""
    segments: list[str] = []
    leading_slash = path.startswith("/")
    for seg in path.split("/"):
        if seg == "..":
            if segments:
                segments.pop()
        elif seg not in (".", ""):
            segments.append(seg)
    out = "/".join(segments)
    if leading_slash:
        out = "/" + out
    if path.endswith(("/", "/.", "/..")) and not out.endswith("/"):
        out += "/"
    return out or "/"


def path_forms(path: str) -> list[str]:
    """Every form of the path an upstream server might effectively see:
    the raw string, dot-segment-resolved, and each percent-decoding round
    to a fixpoint (bounded). Order is deterministic; entries unique."""
    forms: list[str] = []
    cur = path or "/"
    for _ in range(MAX_DECODE_ROUNDS):
        for f in (cur, remove_dot_segments(cur)):
            if f not in forms:
                forms.append(f)
        decoded = unquote(cur)
        if decoded == cur:
            break
        cur = decoded
    return forms


def _type_err(errors: list[str], where: str) -> None:
    errors.append(f"invalid type at {where}")


def _str_list(value, where: str, errors: list[str]) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        _type_err(errors, where)
        return []
    return value


def _rule_list(value, where: str, errors: list[str]) -> list[tuple[str, str]]:
    rules: list[tuple[str, str]] = []
    if not isinstance(value, list):
        _type_err(errors, where)
        return []
    for i, entry in enumerate(value):
        if (
            not isinstance(entry, dict)
            or set(entry) - _RULE_KEYS
            or not isinstance(entry.get("host"), str)
            or not isinstance(entry.get("path"), str)
        ):
            _type_err(errors, f"{where}[{i}]")
            continue
        rules.append((entry["host"], entry["path"]))
    return rules


def parse_policy(text: str, source: str = "<inline>") -> Policy:
    errors: list[str] = []
    try:
        data = tomllib.loads(text)
    except (tomllib.TOMLDecodeError, ValueError) as exc:
        return Policy(valid=False, errors=[f"{source}: parse error: {exc}"])

    unknown = set(data) - _TOP_KEYS
    if unknown:
        errors.append(f"unknown top-level keys: {sorted(unknown)}")

    mode = data.get("mode", "strict-allow")
    if mode not in VALID_MODES:
        errors.append(f"invalid mode: {mode!r}")

    hosts = data.get("hosts", {})
    if not isinstance(hosts, dict) or set(hosts) - _HOSTS_KEYS:
        _type_err(errors, "hosts")
        hosts = {}
    paths = data.get("paths", {})
    if not isinstance(paths, dict) or set(paths) - _PATHS_KEYS:
        _type_err(errors, "paths")
        paths = {}

    policy = Policy(
        valid=True,
        mode=mode if mode in VALID_MODES else "strict-allow",
        host_allow=_str_list(hosts.get("allow", []), "hosts.allow", errors),
        host_block=_str_list(hosts.get("block", []), "hosts.block", errors),
        path_allow=_rule_list(paths.get("allow", []), "paths.allow", errors),
        path_block=_rule_list(paths.get("block", []), "paths.block", errors),
        errors=errors,
    )
    if errors:
        return Policy(valid=False, errors=[f"{source}: {e}" for e in errors])
    return policy


def load_policy(path: str) -> Policy:
    try:
        with open(path, "rb") as fh:
            text = fh.read().decode("utf-8")
    except OSError as exc:
        return Policy(valid=False, errors=[f"{path}: unreadable: {exc}"])
    except UnicodeDecodeError as exc:
        return Policy(valid=False, errors=[f"{path}: not utf-8: {exc}"])
    return parse_policy(text, source=path)


def evaluate(policy: Policy, url: str) -> Verdict:
    if not policy.valid:
        return Verdict(False, "fail-closed:invalid-policy")

    try:
        split = urlsplit(url if "//" in url else "//" + url)
        host = _canon_host(split.netloc)
        path = split.path or "/"
    except ValueError:
        return Verdict(False, "fail-closed:bad-url")
    if not host or not re.fullmatch(r"[a-z0-9._:\-]+", host):
        return Verdict(False, "fail-closed:bad-url")

    forms = path_forms(path)

    # 1. Host blocklist, with all-forms allow carve-outs.
    for pattern in policy.host_block:
        if host_matches(pattern, host):
            for hpat, ppat in policy.path_allow:
                if host_matches(hpat, host) and all(path_matches(ppat, f) for f in forms):
                    return Verdict(True, "path-allow-carveout", f"{hpat}{ppat}")
            return Verdict(False, "host-block", pattern)

    # 2. Path-level blocks, any-form.
    for hpat, ppat in policy.path_block:
        if host_matches(hpat, host) and any(path_matches(ppat, f) for f in forms):
            return Verdict(False, "path-block", f"{hpat}{ppat}")

    # 3. Default mode.
    if policy.mode == "strict-allow":
        for pattern in policy.host_allow:
            if host_matches(pattern, host):
                return Verdict(True, "host-allow", pattern)
        return Verdict(False, "default-deny")
    return Verdict(True, "default-allow")


def evaluate_connect(policy: Policy, host: str) -> Verdict:
    """Host-level decision at HTTPS CONNECT time, before any TLS interception.

    Path rules cannot be evaluated yet (the path is inside the tunnel), so a
    host that any path-allow carve-out could apply to gets its tunnel opened
    and the full ``evaluate()`` runs on the decrypted request. Everything
    else is decided here, fail-closed.
    """
    if not policy.valid:
        return Verdict(False, "fail-closed:invalid-policy")
    canon = _canon_host(host)
    if not canon or not re.fullmatch(r"[a-z0-9._:\-]+", canon):
        return Verdict(False, "fail-closed:bad-url")

    def carveout_could_apply() -> bool:
        return any(host_matches(hpat, canon) for hpat, _ in policy.path_allow)

    for pattern in policy.host_block:
        if host_matches(pattern, canon):
            if carveout_could_apply():
                return Verdict(True, "connect-defer:carveout", pattern)
            return Verdict(False, "host-block", pattern)

    if policy.mode == "strict-allow":
        for pattern in policy.host_allow:
            if host_matches(pattern, canon):
                return Verdict(True, "host-allow", pattern)
        if carveout_could_apply():
            return Verdict(True, "connect-defer:carveout")
        return Verdict(False, "default-deny")
    return Verdict(True, "default-allow")


def check(policy_path: str, url: str) -> Verdict:
    """One-call convenience used by the CLI and launcher preview."""
    return evaluate(load_policy(policy_path), url)


def _main(argv: list[str]) -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser(prog="tjor_policy", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_check = sub.add_parser("check", help="evaluate a URL against a policy file")
    p_check.add_argument("--policy", required=True)
    p_check.add_argument("--json", action="store_true")
    p_check.add_argument("url")
    p_val = sub.add_parser("validate", help="validate a policy file")
    p_val.add_argument("--policy", required=True)
    args = parser.parse_args(argv)

    if args.cmd == "validate":
        policy = load_policy(args.policy)
        for err in policy.errors:
            print(f"error: {err}", file=sys.stderr)
        print("valid" if policy.valid else "INVALID — all egress will be denied (fail-closed)")
        return 0 if policy.valid else 1

    verdict = check(args.policy, args.url)
    if args.json:
        print(json.dumps(verdict.as_dict()))
    else:
        print(f"{'ALLOW' if verdict.allowed else 'DENY'} {args.url} ({verdict.rule}"
              + (f": {verdict.pattern}" if verdict.pattern else "") + ")")
    return 0 if verdict.allowed else 1


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
