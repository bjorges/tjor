#!/usr/bin/env python3
"""Git-metadata tamper detection (#72): detect — never prevent — git metadata
written inside the cage that would run code in the operator's HOST git.

The masks (#71) keep `.git/hooks` empty and, opt-in, pin `.git/config`. What
they cannot prevent, this module makes visible: at launch the launcher records
a BASELINE of every git directory under a writable mount root; at harness
exit, at teardown and on demand (`tjor git-check`) the launcher re-snapshots
and diffs. A pending marker written before the agent starts survives crashes
and is cleared only by a clean check or an explicit, token-bound `--ack`.

What is recorded per git directory (a `.git` dir, or a `.git` file resolved
to its worktree's common dir):
  - the DANGEROUS config keys present, EVERY value of each (a key may repeat;
    a value slipped between two legitimate ones must not hide), read with
    `git config --file <f> --no-includes --list -z` (reads only, runs
    nothing, follows no includes). A config git cannot parse is recorded as
    UNREADABLE — a finding, never "no dangerous keys" (fail closed);
  - whether the config file, the `.git` entry and the hooks dir are symlinks;
  - worktree pointers: the `.git` file text, `worktrees/*/{gitdir,commondir}`;
  - a hash of every file in the hooks dir;
  - the nested repositories already present in the working tree.
Per snapshot: where discovery was INCOMPLETE (the depth cap, an unreadable
directory). A new incomplete spot is a finding; one present at baseline is
announced at launch — a truncated walk is never silent.

The dangerous set (lowercase keys) — anything host git would EXECUTE, plus
the keys that redirect where code comes from or widen trust:
  exact:    core.hookspath core.fsmonitor core.sshcommand core.pager
            core.editor core.askpass core.gitproxy core.alternaterefscommand
            core.attributesfile sequence.editor gpg.program diff.external
            interactive.difffilter credential.helper uploadpack.packobjectshook
            sendemail.sendmailcmd sendemail.smtpservercommand imap.tunnel
            protocol.allow init.templatedir include.path
  families: gpg.<fmt>.program  filter.<n>.clean|smudge|process
            diff.<n>.textconv|command  merge.<n>.driver  mergetool.<t>.cmd
            difftool.<t>.cmd  guitool.<t>.cmd  browser.<b>.cmd  pager.<cmd>
            credential.<url>.helper  remote.<r>.uploadpack|receivepack|proxy|vcs
            url.<base>.insteadof|pushinsteadof  includeif.<cond>.path
            protocol.<name>.allow  trailer.<t>.command|cmd
            sendemail.<identity>.sendmailcmd|smtpservercommand
            safe.*  extensions.*
  by value: alias.<a> and submodule.<s>.update when the value starts with "!";
            remote.<r>.url|pushurl and submodule.<s>.url when the value names
            the ext:: or fd:: transport (ext:: runs a command on every fetch,
            pull, push and clone — git refuses it unless protocol.*.allow is
            widened, which is itself in the set; both are reported);
            sendemail.smtpserver when the value is a program path ("/…").
Everything else — branch.*, an https/ssh remote.*.url, remote.*.fetch/push,
user.*, push.*, … — is NOT a finding, so a `push -u` never trips the check.

Honest limits: this narrows the window between a cage write and the operator's
next host-side git command; it does not close it. The walk stops at a depth
cap below each root (recorded, announced) and does not follow symlinks; a
repository planted below a spot that was ALREADY truncated at baseline is
invisible — the launch line names those spots.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tjor_safeprint  # noqa: E402

MAX_DEPTH_DEFAULT = 32

_EXACT = frozenset({
    "core.hookspath", "core.fsmonitor", "core.sshcommand", "core.pager",
    "core.editor", "core.askpass", "core.gitproxy", "core.alternaterefscommand",
    "core.attributesfile", "sequence.editor", "gpg.program", "diff.external",
    "interactive.difffilter", "credential.helper", "uploadpack.packobjectshook",
    "sendemail.sendmailcmd", "sendemail.smtpservercommand", "imap.tunnel",
    "protocol.allow", "init.templatedir", "include.path",
})
# (section, last-segment) families: section.<anything>.last
_FAMILIES = {
    "gpg": {"program"},
    "filter": {"clean", "smudge", "process"},
    "diff": {"textconv", "command"},
    "merge": {"driver"},
    "mergetool": {"cmd"},
    "difftool": {"cmd"},
    "guitool": {"cmd"},
    "browser": {"cmd"},
    "credential": {"helper"},
    "remote": {"uploadpack", "receivepack", "proxy", "vcs"},
    "url": {"insteadof", "pushinsteadof"},
    "includeif": {"path"},
    "protocol": {"allow"},
    "trailer": {"command", "cmd"},
    "sendemail": {"sendmailcmd", "smtpservercommand"},
}
_SECTIONS_ANY = frozenset({"pager", "safe", "extensions"})   # every key under the section
_BANG_SECTIONS = {"alias": None, "submodule": "update"}      # dangerous when the value starts with "!"
# Transport URLs (section, last-segment): dangerous when the value names a
# transport that executes — `ext::<command>` runs it; `fd::` reads a caller's
# descriptor — on every fetch/pull/push/clone touching that remote.
_TRANSPORT_KEYS = {"remote": {"url", "pushurl"}, "submodule": {"url"}}
_TRANSPORT_EXEC = ("ext::", "fd::")


def is_dangerous(key: str, value: str) -> bool:
    """The predicate: does host git EXECUTE, redirect or over-trust because of
    this key (with this value)? Keys are compared lowercase (git lowercases
    section and name; the subsection keeps its case but is not what we match
    on)."""
    k = key.lower()
    if k in _EXACT:
        return True
    parts = key.split(".")
    section = parts[0].lower()
    last = parts[-1].lower()
    if section in _SECTIONS_ANY:
        return True
    if len(parts) >= 3 and section in _FAMILIES and last in _FAMILIES[section]:
        return True
    if section in _BANG_SECTIONS and len(parts) >= 2:
        want = _BANG_SECTIONS[section]
        if (want is None or last == want) and value.lstrip().startswith("!"):
            return True
    if len(parts) >= 3 and section in _TRANSPORT_KEYS and last in _TRANSPORT_KEYS[section]:
        if value.lstrip().lower().startswith(_TRANSPORT_EXEC):
            return True
    if k == "sendemail.smtpserver" and value.lstrip().startswith("/"):
        return True   # a path here is a sendmail-like PROGRAM, not a server
    return False


def _config_pairs(path: Path) -> tuple[dict[str, list[str]], str | None]:
    """(every key -> its values in file order, error) for one config FILE,
    without following includes and without running anything. A file git
    cannot parse (or cannot read) yields NO pairs and the error text: the
    caller records it as unreadable — fail closed, never "no dangerous
    keys" (v0.21.1 review)."""
    try:
        r = subprocess.run(
            ["git", "config", "--file", str(path), "--no-includes", "--list", "-z"],
            capture_output=True, check=False,
        )
    except OSError as e:
        return {}, f"git could not be run: {e}"
    if r.returncode != 0:
        err = r.stderr.decode("utf-8", "replace").strip().splitlines()
        return {}, (err[0] if err else f"git config exited {r.returncode}")
    pairs: dict[str, list[str]] = {}
    for rec in r.stdout.split(b"\0"):
        if not rec:
            continue
        key, _, value = rec.decode("utf-8", "replace").partition("\n")
        pairs.setdefault(key, []).append(value)
    return pairs, None


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
    except OSError:
        return "unreadable"
    return h.hexdigest()


def _link(path: Path) -> str | None:
    """The link target when `path` is a symlink, else None."""
    try:
        return os.readlink(path) if path.is_symlink() else None
    except OSError:
        return "unreadable"


def _resolve_gitdir(worktree: Path) -> tuple[Path | None, str | None]:
    """(git dir, pointer text) for a working tree: a `.git` directory is its
    own git dir (pointer None); a `.git` FILE is `gitdir: <path>` — the
    pointer text is baselined verbatim and the target is resolved
    (relative to the worktree) without asking git to run anything."""
    dotgit = worktree / ".git"
    if dotgit.is_dir():
        return dotgit, None
    if dotgit.is_file():
        try:
            text = dotgit.read_text(errors="replace").strip()
        except OSError:
            return None, None
        if text.startswith("gitdir:"):
            target = text[len("gitdir:"):].strip()
            p = Path(target)
            if not p.is_absolute():
                p = (worktree / p)
            return p.resolve(strict=False), text
        return None, text
    return None, None


def _common_dir(gitdir: Path) -> Path:
    """The common dir: `<gitdir>/commondir` names it for a linked worktree,
    else the git dir is its own common dir."""
    cd = gitdir / "commondir"
    if cd.is_file():
        try:
            rel = cd.read_text(errors="replace").strip()
            p = Path(rel)
            return (gitdir / p).resolve(strict=False) if not p.is_absolute() else p
        except OSError:
            pass
    return gitdir


def discover(roots: list[str], max_depth: int = MAX_DEPTH_DEFAULT) -> tuple[list[Path], list[dict]]:
    """(every working tree — a dir holding a `.git` entry — under the roots,
    roots first, one walk; the spots where the walk was INCOMPLETE). The walk
    never descends INTO a `.git` directory, never follows symlinks, and stops
    `max_depth` levels below a root: a directory at the cap that still has
    subdirectories is recorded as incomplete (reason `depth-cap N`), as is a
    directory the walk could not read — neither is ever silent."""
    found: list[Path] = []
    seen: set[str] = set()
    incomplete: list[dict] = []

    def onerror(err: OSError) -> None:
        where = getattr(err, "filename", None)
        incomplete.append({"path": str(where) if where else "?", "reason": f"unreadable: {err.strerror or err}"})

    for root in roots:
        base = Path(root)
        if not base.is_dir():
            continue
        # Every root is walked, a root that IS a git directory included (a
        # worktree's common dir mounted alongside it, #79): it holds no
        # repositories of its own and yields nothing, and a shape test
        # (HEAD + objects/ + refs/) would be three plantable artifacts that
        # hide a whole subtree with no signal (v0.21.2 review) — the module's
        # own rule is that nothing skipped is ever silent.
        base_depth = len(base.parts)
        for dirpath, dirnames, filenames in os.walk(base, onerror=onerror, followlinks=False):
            d = Path(dirpath)
            if ".git" in dirnames or ".git" in filenames:
                key = str(d)
                if key not in seen:
                    seen.add(key)
                    found.append(d)
            dirnames[:] = sorted(n for n in dirnames if n != ".git")
            if dirnames and len(d.parts) - base_depth >= max_depth:
                incomplete.append({"path": str(d), "reason": f"depth-cap {max_depth}"})
                dirnames[:] = []
    incomplete.sort(key=lambda e: (e["path"], e["reason"]))
    return found, incomplete


def _snapshot_repo(worktree: Path, nested: list[str]) -> dict:
    dotgit = worktree / ".git"
    gitdir, pointer = _resolve_gitdir(worktree)
    entry: dict = {
        "worktree": str(worktree), "pointer": pointer,
        "gitdir": str(gitdir) if gitdir else None, "gitdir_symlink": _link(dotgit),
    }
    if gitdir is None or not gitdir.is_dir():
        entry["config"] = None
        return entry
    common = _common_dir(gitdir)
    cfg = common / "config"
    pairs, cfg_err = _config_pairs(cfg) if cfg.exists() else ({}, None)
    dangerous = {k: v for k, v in pairs.items() if any(is_dangerous(k, x) for x in v)}
    includes = sorted(
        x for k, v in pairs.items()
        if k.lower() == "include.path" or (k.lower().startswith("includeif.") and k.lower().endswith(".path"))
        for x in v
    )
    wt_cfg = gitdir / "config.worktree"
    wt_pairs, wt_err = _config_pairs(wt_cfg) if wt_cfg.exists() else ({}, None)
    dangerous.update({f"[worktree] {k}": v for k, v in wt_pairs.items() if any(is_dangerous(k, x) for x in v)})
    hooks: dict[str, str] = {}
    hdir = common / "hooks"
    if hdir.is_dir():
        for p in sorted(hdir.iterdir()):
            if p.is_file():
                hooks[p.name] = _sha(p)
    worktrees: dict[str, dict] = {}
    wdir = common / "worktrees"
    if wdir.is_dir():
        for w in sorted(wdir.iterdir()):
            if not w.is_dir():
                continue
            rec = {}
            for name in ("gitdir", "commondir"):
                f = w / name
                if f.is_file():
                    try:
                        rec[name] = f.read_text(errors="replace").strip()
                    except OSError:
                        rec[name] = "unreadable"
            worktrees[w.name] = rec
    entry.update({
        "config": str(cfg), "config_symlink": cfg.is_symlink(), "config_exists": cfg.exists(),
        "config_error": cfg_err, "config_worktree_error": wt_err,
        "common": str(common), "dangerous": dangerous, "includes": includes,
        "hooks": hooks, "hooks_symlink": _link(hdir), "worktrees": worktrees, "nested": nested,
    })
    return entry


def snapshot(roots: list[str], max_depth: int = MAX_DEPTH_DEFAULT) -> dict:
    wts, incomplete = discover(roots, max_depth)
    names = [str(w) for w in wts]
    repos = []
    for w in wts:
        prefix = str(w).rstrip("/") + "/"
        repos.append(_snapshot_repo(w, sorted(n for n in names if n.startswith(prefix))))
    return {
        "version": 2, "taken_at": int(time.time()), "roots": [str(Path(r)) for r in roots],
        "max_depth": max_depth, "incomplete": incomplete, "repos": repos,
    }


def diff(baseline: dict, current: dict) -> list[dict]:
    """Findings: each a dict with repo, kind, and the specifics. Only what
    host git would act on — plus the places where this check could NOT
    look (an unparseable config, a new truncation) — benign config churn
    never appears."""
    findings: list[dict] = []
    cur = {r["worktree"]: r for r in current.get("repos", [])}
    base_wts = [b["worktree"] for b in baseline.get("repos", [])]
    for b in baseline.get("repos", []):
        wt = b["worktree"]
        c = cur.get(wt)
        # A re-pointed `.git` file is judged FIRST: it usually also makes the
        # git dir unresolvable, and "pointer changed" is the finding that
        # names the mechanism, not just the symptom.
        if c is not None and b.get("pointer") != c.get("pointer"):
            findings.append({"repo": wt, "kind": "worktree-pointer", "key": ".git", "old": b.get("pointer"), "new": c.get("pointer")})
        if c is None or c.get("config") is None and b.get("config") is not None:
            findings.append({"repo": wt, "kind": "repo-missing", "detail": "baseline repository vanished or lost its git dir"})
            continue
        if b.get("config") is None:
            continue
        if c.get("gitdir_symlink") != b.get("gitdir_symlink"):
            findings.append({"repo": wt, "kind": "gitdir-symlinked", "path": str(Path(wt) / ".git"), "old": b.get("gitdir_symlink"), "new": c.get("gitdir_symlink")})
        # Fail closed: a config this check cannot parse is reported, not
        # counted as clean — its keys are unknown, and host git may still
        # read what it can of the file.
        for which, field in (("config", "config_error"), ("config.worktree", "config_worktree_error")):
            if c.get(field):
                since = " (already unreadable at baseline)" if b.get(field) else ""
                findings.append({"repo": wt, "kind": "config-unreadable", "key": which,
                                 "detail": f"git cannot parse it — its keys are UNKNOWN, not clean{since}: {c[field]}"})
        bd, cd = b.get("dangerous", {}), c.get("dangerous", {})
        for k in sorted(set(bd) | set(cd)):
            if bd.get(k) != cd.get(k):
                findings.append({"repo": wt, "kind": "dangerous-key", "key": k, "old": bd.get(k), "new": cd.get(k)})
        for inc in sorted(set(c.get("includes", [])) - set(b.get("includes", []))):
            findings.append({"repo": wt, "kind": "include-added", "path": inc})
        if c.get("config_symlink") and not b.get("config_symlink"):
            findings.append({"repo": wt, "kind": "config-symlinked", "path": c.get("config")})
        if c.get("hooks_symlink") != b.get("hooks_symlink"):
            findings.append({"repo": wt, "kind": "hooks-symlinked", "path": str(Path(c.get("common") or wt) / "hooks"), "old": b.get("hooks_symlink"), "new": c.get("hooks_symlink")})
        bw, cw = b.get("worktrees", {}), c.get("worktrees", {})
        for name in sorted(set(bw) | set(cw)):
            if bw.get(name) != cw.get(name):
                findings.append({"repo": wt, "kind": "worktree-changed", "key": name, "old": bw.get(name), "new": cw.get(name)})
        bh, ch = b.get("hooks", {}), c.get("hooks", {})
        for name in sorted(set(bh) | set(ch)):
            if bh.get(name) != ch.get(name):
                findings.append({"repo": wt, "kind": "hook-changed", "key": name, "old": bh.get(name), "new": ch.get(name)})
        for n in sorted(set(c.get("nested", [])) - set(b.get("nested", []))):
            findings.append({"repo": wt, "kind": "nested-repo-added", "path": n})
    # A repository that appeared directly under a mounted root that was not
    # itself a repository at baseline (nothing above it to report it as nested).
    base_set = set(base_wts)
    for wt in sorted(cur):
        if wt in base_set or any(wt.startswith(b.rstrip("/") + "/") for b in base_wts):
            continue
        findings.append({"repo": wt, "kind": "repo-added", "detail": "a repository appeared under a mounted root since the baseline"})
    b_inc = {(e.get("path"), e.get("reason")) for e in baseline.get("incomplete", [])}
    for e in current.get("incomplete", []):
        if (e.get("path"), e.get("reason")) not in b_inc:
            findings.append({"repo": e.get("path"), "kind": "discovery-incomplete",
                             "detail": f"{e.get('reason')} — repositories below this point are UNCHECKED (a new truncation since the baseline)"})
    return findings


# Credentials embedded in a URL-shaped key or value (`url.https://u:t@h/.insteadOf`)
# are redacted before anything reaches a terminal, a log or a JSON consumer.
_URL_CRED = re.compile(r"(?<=://)[^/@\s]+@")


def _clean(text: str) -> str:
    return tjor_safeprint.sanitize(_URL_CRED.sub("[redacted:url-credential]@", text))


def _clean_value(v):
    if isinstance(v, str):
        return _clean(v)
    if isinstance(v, list):
        return [_clean_value(x) for x in v]
    if isinstance(v, dict):
        return {_clean(str(k)): _clean_value(x) for k, x in v.items()}
    return v


def sanitize_findings(findings: list[dict]) -> list[dict]:
    """Every string in every finding escape-sanitized and credential-redacted —
    the JSON consumer gets the same protection as the terminal."""
    return [_clean_value(f) for f in findings]


def token(findings: list[dict]) -> str:
    """A short digest of exactly these (sanitized) findings: `--ack` must carry
    it, so an acknowledgement is bound to the state that was reviewed. Empty
    when there is nothing to acknowledge."""
    if not findings:
        return ""
    return hashlib.sha256(json.dumps(findings, sort_keys=True).encode()).hexdigest()[:12]


_INSPECT_KINDS = frozenset({"config-unreadable", "discovery-incomplete"})


def render(f: dict) -> str:
    """One terminal-safe line per finding; every untrusted field sanitized."""
    s = _clean
    parts = [f"git-check FINDING {s(str(f['repo']))}: {f['kind']}"]
    if f.get("key") is not None:
        parts.append(s(str(f["key"])))
    if f.get("path") is not None:
        parts.append(s(str(f["path"])))
    if "old" in f or "new" in f:
        parts.append(f"{s(json.dumps(f.get('old')))} -> {s(json.dumps(f.get('new')))}")
    if f.get("detail"):
        parts.append(s(str(f["detail"])))
    if f["kind"] in _INSPECT_KINDS:
        tail = " — this check could NOT see here; inspect by hand before using this repo outside tjor"
    else:
        tail = " — would run in your HOST git; review before using this repo outside tjor"
    return " ".join(parts) + tail


def _write_atomic(out: str, snap: dict) -> None:
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(out).with_suffix(".tmp")
    tmp.write_text(json.dumps(snap, indent=1, sort_keys=True))
    os.replace(tmp, out)


def _load(path: str) -> dict:
    return json.loads(Path(path).read_text())


def _covers(baseline: dict, path: str) -> bool:
    p = path.rstrip("/") or "/"
    return any(p == r.rstrip("/") or p.startswith(r.rstrip("/") + "/") for r in baseline.get("roots", []))


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) >= 2 else ""
    if cmd == "snapshot":
        out = None
        max_depth = MAX_DEPTH_DEFAULT
        roots: list[str] = []
        i = 2
        while i < len(argv):
            if argv[i] == "--out":
                out = argv[i + 1]; i += 2
            elif argv[i] == "--max-depth":
                max_depth = int(argv[i + 1]); i += 2
            else:
                roots.append(argv[i]); i += 1
        snap = snapshot(roots, max_depth)
        if out:
            _write_atomic(out, snap)
        else:
            print(json.dumps(snap, indent=1, sort_keys=True))
        # stderr: one warning per incomplete spot, then the repo count LAST
        # (the launcher reads the count from the final line).
        for e in snap["incomplete"]:
            print(f"discovery incomplete under {_clean(e['path'])}: {_clean(e['reason'])} — repositories below are not tracked", file=sys.stderr)
        print(f"{len(snap['repos'])}", file=sys.stderr)
        return 0
    if cmd == "rebaseline" and len(argv) == 3:
        old = _load(argv[2])
        _write_atomic(argv[2], snapshot(old.get("roots", []), int(old.get("max_depth", MAX_DEPTH_DEFAULT))))
        return 0
    if cmd == "check" and len(argv) >= 3:
        baseline = _load(argv[2])
        current = snapshot(baseline.get("roots", []), int(baseline.get("max_depth", MAX_DEPTH_DEFAULT)))
        findings = sanitize_findings(diff(baseline, current))
        tok = token(findings)
        if "--token" in argv:
            print(tok)
        elif "--json" in argv:
            print(json.dumps({"findings": findings, "token": tok or None,
                              "incomplete": _clean_value(current["incomplete"])}, indent=1, sort_keys=True))
        else:
            for f in findings:
                print(render(f))
            if findings:
                print(f"git-check token: {tok}")
        return 1 if findings else 0
    if cmd == "covers" and len(argv) == 4:
        return 0 if _covers(_load(argv[2]), argv[3]) else 1
    if cmd == "roots" and len(argv) == 3:
        for r in _load(argv[2]).get("roots", []):
            print(r)
        return 0
    print("usage: tjor_gitcheck.py snapshot [--out FILE] [--max-depth N] ROOT... | check BASELINE [--json|--token] | rebaseline BASELINE | covers BASELINE PATH | roots BASELINE", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
