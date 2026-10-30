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
  4. Method gate, on an ALLOWED verdict only (#66): a host matched by any
     ``[[methods.restrict]]`` rule admits a method only if every matching
     rule lists it, or a ``[[methods.except]]`` rule admits it on the path
     (all-forms, like an allow). The gate can only turn an allow into
     ``method-block:<METHOD>``; it never widens, and an absent ``methods``
     section leaves every verdict as it was. The method is compared byte
     for byte as sent (no case folding) and must be an HTTP token of at
     most 32 characters, else ``fail-closed:bad-method`` on every host.

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

MAX_DECODE_ROUNDS = 16  # if a path is still decoding after this, it is denied outright

VALID_MODES = ("strict-allow", "default-allow")
_TOP_KEYS = {"mode", "hosts", "paths", "methods"}
_HOSTS_KEYS = {"allow", "block"}
_PATHS_KEYS = {"allow", "block"}
_RULE_KEYS = {"host", "path"}
_METHODS_KEYS = {"restrict", "except"}
_RESTRICT_KEYS = {"host", "allow"}
_EXCEPT_KEYS = {"host", "path", "methods"}
# A method name as written in a policy: exact and upper-case, one to thirty-two
# characters — every registered HTTP method fits (VERSION-CONTROL,
# UPDATEREDIRECTREF). "get" or "GET " is a format error, never normalised: this
# file's other parse errors are loud too, and a policy is written once.
_METHOD_NAME = re.compile(r"[A-Z][A-Z0-9-]{0,31}")
# A request method as the agent sent it: an RFC 9110 token (tchar), ASCII,
# one to thirty-two characters. Compared byte for byte; no folding, no trim.
_METHOD_TOKEN = re.compile(r"[!#$%&'*+\-.^_`|~0-9A-Za-z]{1,32}")


@dataclass(frozen=True)
class Verdict:
    allowed: bool
    rule: str          # which stage decided, e.g. "host-block", "path-allow-carveout"
    pattern: str = ""  # the pattern that matched, when one did

    def as_dict(self) -> dict:
        return {"allowed": self.allowed, "rule": self.rule, "pattern": self.pattern}


@dataclass
class Policy:
    """Parsed egress policy. ``valid=False`` means the source was missing,
    unparseable, or malformed in ANY way — evaluate()/evaluate_connect()
    then deny everything. Never construct a valid=True Policy from
    unvalidated input; go through parse_policy()/load_policy()."""

    valid: bool
    mode: str = "strict-allow"
    host_allow: list[str] = field(default_factory=list)
    host_block: list[str] = field(default_factory=list)
    path_allow: list[tuple[str, str]] = field(default_factory=list)  # (host glob, path glob)
    path_block: list[tuple[str, str]] = field(default_factory=list)
    method_restrict: list[tuple[str, frozenset[str]]] = field(default_factory=list)       # (host glob, allowed methods)
    method_except: list[tuple[str, str, frozenset[str]]] = field(default_factory=list)   # (host glob, path glob, methods)
    errors: list[str] = field(default_factory=list)


def _wildcard_match(pattern: str, text: str) -> bool:
    """Iterative glob match (``*`` spans anything, ``?`` one char).

    Deliberately not regex-based: chained wildcards compiled to ``.*``
    backtrack catastrophically on attacker-influenced paths (ReDoS). This is
    the classic two-pointer algorithm, O(len(pattern) * len(text)) worst
    case, no backtracking blowup.
    """
    pi = ti = 0
    star = -1
    mark = 0
    while ti < len(text):
        if pi < len(pattern) and (pattern[pi] == "?" or pattern[pi] == text[ti]):
            pi += 1
            ti += 1
        elif pi < len(pattern) and pattern[pi] == "*":
            star = pi
            mark = ti
            pi += 1
        elif star != -1:
            pi = star + 1
            mark += 1
            ti = mark
        else:
            return False
    while pi < len(pattern) and pattern[pi] == "*":
        pi += 1
    return pi == len(pattern)


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
    return _wildcard_match(pattern.strip().casefold().rstrip("."), _canon_host(host))


def path_matches(pattern: str, path: str) -> bool:
    """Glob path match against ONE form of a path. Callers are responsible
    for the any-form (block) / all-form (allow) asymmetry over
    :func:`path_forms` — never call this on a raw path alone for a security
    decision. Case-sensitive by design (paths are)."""
    return _wildcard_match(pattern, path)


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


def path_forms(path: str) -> tuple[list[str], bool]:
    """Every form of the path an upstream server might effectively see:
    the raw string, dot-segment-resolved, and each percent-decoding round
    down to the fixpoint. Returns ``(forms, complete)``.

    ``complete`` is False when the path was STILL decoding after
    MAX_DECODE_ROUNDS — meaning the true final form was never inspected.
    Callers must treat an incomplete decode as a denial (fail-closed):
    a bounded window that silently stops decoding is exactly the nested-
    encoding block bypass this function exists to prevent.
    """
    forms: list[str] = []
    cur = path or "/"
    complete = False
    for _ in range(MAX_DECODE_ROUNDS + 1):
        for f in (cur, remove_dot_segments(cur)):
            if f not in forms:
                forms.append(f)
        decoded = unquote(cur)
        if decoded == cur:
            complete = True
            break
        cur = decoded
    return forms, complete


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


def _method_list(value, where: str, errors: list[str]) -> frozenset[str]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        _type_err(errors, where)
        return frozenset()
    bad = [v for v in value if not _METHOD_NAME.fullmatch(v)]
    if bad:
        errors.append(f"invalid method name at {where}: {bad!r} (upper-case token, 1-32 chars)")
        return frozenset()
    return frozenset(value)


def _restrict_list(value, where: str, errors: list[str]) -> list[tuple[str, frozenset[str]]]:
    rules: list[tuple[str, frozenset[str]]] = []
    if not isinstance(value, list):
        _type_err(errors, where)
        return []
    for i, entry in enumerate(value):
        if not isinstance(entry, dict) or set(entry) != _RESTRICT_KEYS or not isinstance(entry.get("host"), str):
            _type_err(errors, f"{where}[{i}]")
            continue
        rules.append((entry["host"], _method_list(entry["allow"], f"{where}[{i}].allow", errors)))
    return rules


def _except_list(value, where: str, errors: list[str]) -> list[tuple[str, str, frozenset[str]]]:
    rules: list[tuple[str, str, frozenset[str]]] = []
    if not isinstance(value, list):
        _type_err(errors, where)
        return []
    for i, entry in enumerate(value):
        if (
            not isinstance(entry, dict)
            or set(entry) != _EXCEPT_KEYS
            or not isinstance(entry.get("host"), str)
            or not isinstance(entry.get("path"), str)
        ):
            _type_err(errors, f"{where}[{i}]")
            continue
        rules.append((entry["host"], entry["path"], _method_list(entry["methods"], f"{where}[{i}].methods", errors)))
    return rules


def parse_policy(text: str, source: str = "<inline>") -> Policy:
    """Parse policy TOML into a Policy, fail-closed.

    Strict by design: unknown keys anywhere (a typo'd ``blokc`` would
    silently weaken the policy), wrong types, and invalid modes all yield
    ``valid=False`` — which downstream means deny-everything — rather than
    a best-effort partial policy.
    """
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
    methods = data.get("methods", {})
    if not isinstance(methods, dict) or set(methods) - _METHODS_KEYS:
        _type_err(errors, "methods")
        methods = {}

    policy = Policy(
        valid=True,
        mode=mode if mode in VALID_MODES else "strict-allow",
        host_allow=_str_list(hosts.get("allow", []), "hosts.allow", errors),
        host_block=_str_list(hosts.get("block", []), "hosts.block", errors),
        path_allow=_rule_list(paths.get("allow", []), "paths.allow", errors),
        path_block=_rule_list(paths.get("block", []), "paths.block", errors),
        method_restrict=_restrict_list(methods.get("restrict", []), "methods.restrict", errors),
        method_except=_except_list(methods.get("except", []), "methods.except", errors),
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


def method_restricted(policy: Policy, host: str) -> bool:
    """True when any ``[[methods.restrict]]`` rule matches the host — the
    proxy's header guards and the CLI's note key on this, not on a verdict.
    An invalid policy restricts every host: it denies everything, and a guard
    that read it as unrestricted would be the one fail-open path."""
    if not policy.valid:
        return True
    canon = _canon_host(host)
    return any(host_matches(hpat, canon) for hpat, _ in policy.method_restrict)


# Denial-log hints (#66): the one classifier and the one hint table for
# `tjor denials` and the teardown recap. A standard method-block token is
# lifted by a policy rule; a non-standard one (`get`, `upgrade`) can be named
# by no rule, so the client is what to fix; a header guard has no exception.
DENIAL_HINTS = {
    "method": ("refused by the method gate (a write to a read-only host): widen with a "
               "[[methods.except]] rule for that path or the restriction's allow list, "
               "not with 'tjor policy add'"),
    "nonstd": ("refused for a non-standard method token (e.g. 'get') that no policy rule "
               "can name: fix the client"),
    "header": ("refused by a header guard (a protocol switch or method-override header on a "
               "read-only host): no rule lifts these; leave the host unrestricted if it needs them"),
}


def denial_kind(rule: str) -> "str | None":
    """``"method"``, ``"nonstd"`` or ``"header"`` for a denial-log rule the
    hints speak to, else None."""
    if rule.startswith("method-block:"):
        return "method" if _METHOD_NAME.fullmatch(rule[len("method-block:"):]) else "nonstd"
    if rule.startswith("header-block:"):
        return "header"
    return None


def denial_kind_counts(path: str) -> dict[str, int]:
    """Count the hinted kinds in a denial log (``host<TAB>rule<TAB>time`` lines;
    anything else, the cap notice included, is skipped)."""
    counts = {kind: 0 for kind in DENIAL_HINTS}
    with open(path, "rb") as fh:
        for raw in fh.read().decode("utf-8", "surrogateescape").splitlines():
            parts = raw.split("\t")
            if len(parts) < 2:
                continue
            kind = denial_kind(parts[1])
            if kind is not None:
                counts[kind] += 1
    return counts


def denial_hints(counts: dict[str, int]) -> list[str]:
    """One ``tjor: <n> <hint>`` line per kind present, in table order."""
    return [f"tjor: {counts[kind]} {hint}" for kind, hint in DENIAL_HINTS.items() if counts.get(kind)]


def evaluate(policy: Policy, url: str, method: str) -> Verdict:
    """The egress decision for one request. Order (fixed, tested):
    invalid policy → deny; unparseable URL/host → deny; a method that is not
    an HTTP token of at most 32 characters → deny; excessive encoding →
    deny; host blocklist (all-forms allow carve-outs may override) →
    any-form path blocks → mode default (strict-allow: host must be
    allowlisted) → the method gate, on an allowed verdict only (deny-only).
    Every path not explicitly allowed ends in a deny. ``method`` has no
    default: a call site that forgets it fails at once instead of judging a
    POST as a GET."""
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
    if not isinstance(method, str) or not _METHOD_TOKEN.fullmatch(method):
        return Verdict(False, "fail-closed:bad-method")

    forms, complete = path_forms(path)
    if not complete:
        # Still percent-decoding after MAX_DECODE_ROUNDS: the final form was
        # never inspected, so no rule can be trusted to have seen it.
        return Verdict(False, "fail-closed:excessive-encoding")

    verdict = _evaluate_stages(policy, host, forms)
    if not verdict.allowed:
        return verdict          # an earlier stage's denial is reported as such, never as the gate's
    return _method_gate(policy, host, forms, method, verdict)


def _method_gate(policy: Policy, host: str, forms: list[str], method: str, verdict: Verdict) -> Verdict:
    """Stage 4 (#66). Intersection over every matching restrict rule (the
    order of tables in a hand-written file must not decide what a host may
    do; deny wins); an exception lifts the denial only when its own host
    pattern matches, it lists the method, and EVERY form of the path matches
    its path pattern (the allow-side asymmetry). An admitted request keeps the
    earlier verdict: the gate never allows on its own."""
    restricts = [(hpat, allow) for hpat, allow in policy.method_restrict if host_matches(hpat, host)]
    if not restricts:
        return verdict
    denying = [hpat for hpat, allow in restricts if method not in allow]
    if not denying:
        return verdict
    for hpat, ppat, methods in policy.method_except:
        if method in methods and host_matches(hpat, host) and all(path_matches(ppat, f) for f in forms):
            return verdict
    return Verdict(False, f"method-block:{method}", denying[0])


def _evaluate_stages(policy: Policy, host: str, forms: list[str]) -> Verdict:
    """Stages 1-3, unchanged by the method gate."""
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


def check(policy_path: str, url: str, method: str = "GET") -> Verdict:
    """One-call convenience used by the CLI and launcher preview. The CLI is
    the one caller with a default method: an operator typing a URL previews
    a read."""
    return evaluate(load_policy(policy_path), url, method)


def _main(argv: list[str]) -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser(prog="tjor_policy", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_check = sub.add_parser("check", help="evaluate a URL against a policy file")
    p_check.add_argument("--policy", required=True)
    p_check.add_argument("--json", action="store_true")
    p_check.add_argument("--method", default="GET",
                         help="the request method to preview, exactly as the client would send it (default GET)")
    p_check.add_argument("url")
    p_val = sub.add_parser("validate", help="validate a policy file")
    p_val.add_argument("--policy", required=True)
    p_hint = sub.add_parser("denial-hints", help="print the per-kind hints for a session denial log")
    p_hint.add_argument("log")
    args = parser.parse_args(argv)

    if args.cmd == "denial-hints":
        try:
            counts = denial_kind_counts(args.log)
        except OSError:
            return 0                       # no log, no hints: the callers treat this as advisory
        for line in denial_hints(counts):
            print(line)
        return 0

    if args.cmd == "validate":
        policy = load_policy(args.policy)
        for err in policy.errors:
            print(f"error: {err}", file=sys.stderr)
        print("valid" if policy.valid else "INVALID — all egress will be denied (fail-closed)")
        return 0 if policy.valid else 1

    policy = load_policy(args.policy)
    verdict = evaluate(policy, args.url, args.method)
    # The header guards (Upgrade / method-override, and a 101 from the host)
    # live in the proxy, not the matcher, so a preview cannot see them; say
    # so on a method-restricted host — a field under --json, prose otherwise.
    # An invalid policy already reads DENY on its own line: no note for it.
    try:
        guarded = policy.valid and method_restricted(
            policy, urlsplit(args.url if "//" in args.url else "//" + args.url).netloc)
    except ValueError:
        guarded = False
    if args.json:
        out = verdict.as_dict()
        out["header_guards"] = guarded
        print(json.dumps(out))
    else:
        print(f"{'ALLOW' if verdict.allowed else 'DENY'} {args.url} ({verdict.rule}"
              + (f": {verdict.pattern}" if verdict.pattern else "") + ")")
        if guarded:
            print("note: this host is method-restricted; the proxy also refuses protocol switches "
                  "(Upgrade, Connection: upgrade, Sec-WebSocket-Version, a 101 from the host) and "
                  "method-override headers there, which this preview cannot see")
    return 0 if verdict.allowed else 1


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
