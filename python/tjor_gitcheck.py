#!/usr/bin/env python3
"""Git-metadata tamper detection (#72): detect — never prevent — git metadata
written inside the cage that would run code in the operator's HOST git.

The masks (#71) keep `.git/hooks` empty and, opt-in, pin `.git/config`. What
they cannot prevent, this module makes visible: at launch the launcher records
a BASELINE of every git directory under a writable mount root; at harness
exit, at teardown and on demand (`tjor git-check`) the launcher re-snapshots
and diffs. A pending marker written before the agent starts survives crashes
and is cleared only by a clean check or an explicit `--ack`.

What is recorded per git directory (a `.git` dir, or a `.git` file resolved
to its worktree's common dir):
  - the DANGEROUS config keys present, read with
    `git config --file <f> --no-includes --list -z` (reads only, runs nothing,
    follows no includes);
  - whether the config file is a symlink;
  - worktree pointers: the `.git` file text, `worktrees/*/{gitdir,commondir}`;
  - a hash of every file in the hooks dir;
  - the nested repositories already present in the working tree.

The dangerous set (lowercase keys) — anything host git would EXECUTE, plus
the keys that redirect where code comes from or widen trust:
  exact:    core.hookspath core.fsmonitor core.sshcommand core.pager
            core.editor core.askpass core.gitproxy core.alternaterefscommand
            core.attributesfile sequence.editor gpg.program diff.external
            interactive.difffilter credential.helper uploadpack.packobjectshook
            sendemail.sendmailcmd include.path
  families: gpg.<fmt>.program  filter.<n>.clean|smudge|process
            diff.<n>.textconv|command  merge.<n>.driver  mergetool.<t>.cmd
            difftool.<t>.cmd  browser.<b>.cmd  pager.<cmd>  credential.<url>.helper
            remote.<r>.uploadpack|receivepack|proxy|vcs
            url.<base>.insteadof|pushinsteadof  includeif.<cond>.path
            safe.*  extensions.*
  by value: alias.<a> and submodule.<s>.update when the value starts with "!"
Everything else — branch.*, remote.*.url/fetch/push, user.*, push.*, … — is
NOT a finding, so a `push -u` never trips the check.

Honest limits: this narrows the window between a cage write and the operator's
next host-side git command; it does not close it. The nested-repo walk is
depth-limited. A repo created mid-session is checked only if it appears under
a baseline root.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tjor_safeprint  # noqa: E402

MAX_DEPTH = 12

_EXACT = frozenset({
    "core.hookspath", "core.fsmonitor", "core.sshcommand", "core.pager",
    "core.editor", "core.askpass", "core.gitproxy", "core.alternaterefscommand",
    "core.attributesfile", "sequence.editor", "gpg.program", "diff.external",
    "interactive.difffilter", "credential.helper", "uploadpack.packobjectshook",
    "sendemail.sendmailcmd", "include.path",
})
# (section, last-segment) families: section.<anything>.last
_FAMILIES = {
    "gpg": {"program"},
    "filter": {"clean", "smudge", "process"},
    "diff": {"textconv", "command"},
    "merge": {"driver"},
    "mergetool": {"cmd"},
    "difftool": {"cmd"},
    "browser": {"cmd"},
    "credential": {"helper"},
    "remote": {"uploadpack", "receivepack", "proxy", "vcs"},
    "url": {"insteadof", "pushinsteadof"},
    "includeif": {"path"},
}
_SECTIONS_ANY = frozenset({"pager", "safe", "extensions"})   # every key under the section
_BANG_SECTIONS = {"alias": None, "submodule": "update"}      # dangerous when the value starts with "!"


def is_dangerous(key: str, value: str) -> bool:
    """The predicate: does host git EXECUTE, redirect or over-trust because of
    this key? Keys are compared lowercase (git lowercases section and name;
    the subsection keeps its case but is not what we match on)."""
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
    return False


def _config_pairs(path: Path) -> dict[str, str]:
    """Every key=value in one config FILE, without following includes and
    without running anything. A file git cannot parse yields no pairs (the
    symlink/existence facts are recorded separately)."""
    try:
        out = subprocess.run(
            ["git", "config", "--file", str(path), "--no-includes", "--list", "-z"],
            capture_output=True, check=False,
        ).stdout
    except OSError:
        return {}
    pairs: dict[str, str] = {}
    for rec in out.split(b"\0"):
        if not rec:
            continue
        text = rec.decode("utf-8", "replace")
        key, _, value = text.partition("\n")
        pairs[key] = value
    return pairs


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
    except OSError:
        return "unreadable"
    return h.hexdigest()


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


def discover(roots: list[str]) -> list[Path]:
    """Every working tree (a dir holding a `.git` entry) under the roots,
    depth-limited, roots first; the walk prunes below each `.git` and does
    not descend INTO a `.git` directory."""
    found: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        base = Path(root)
        if not base.is_dir():
            continue
        base_depth = len(base.parts)
        for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
            d = Path(dirpath)
            if len(d.parts) - base_depth > MAX_DEPTH:
                dirnames[:] = []
                continue
            if ".git" in dirnames or ".git" in filenames:
                key = str(d)
                if key not in seen:
                    seen.add(key)
                    found.append(d)
            dirnames[:] = [n for n in dirnames if n != ".git"]
    return found


def _snapshot_repo(worktree: Path) -> dict:
    gitdir, pointer = _resolve_gitdir(worktree)
    entry: dict = {"worktree": str(worktree), "pointer": pointer, "gitdir": str(gitdir) if gitdir else None}
    if gitdir is None or not gitdir.is_dir():
        entry["config"] = None
        return entry
    common = _common_dir(gitdir)
    cfg = common / "config"
    pairs = _config_pairs(cfg) if cfg.exists() else {}
    dangerous = {k: v for k, v in pairs.items() if is_dangerous(k, v)}
    includes = sorted(v for k, v in pairs.items() if k.lower() == "include.path" or (k.lower().startswith("includeif.") and k.lower().endswith(".path")))
    wt_cfg = gitdir / "config.worktree"
    wt_pairs = _config_pairs(wt_cfg) if wt_cfg.exists() else {}
    dangerous.update({f"[worktree] {k}": v for k, v in wt_pairs.items() if is_dangerous(k, v)})
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
    nested = sorted(str(p) for p in discover([str(worktree)]) if p != worktree)
    entry.update({
        "config": str(cfg), "config_symlink": cfg.is_symlink(), "config_exists": cfg.exists(),
        "common": str(common), "dangerous": dangerous, "includes": includes,
        "hooks": hooks, "worktrees": worktrees, "nested": nested,
    })
    return entry


def snapshot(roots: list[str]) -> dict:
    repos = [_snapshot_repo(w) for w in discover(roots)]
    return {"version": 1, "taken_at": int(time.time()), "roots": [str(Path(r)) for r in roots], "repos": repos}


def diff(baseline: dict, current: dict) -> list[dict]:
    """Findings: each a dict with repo, kind, and the specifics. Only what
    host git would act on; benign config churn never appears."""
    findings: list[dict] = []
    cur = {r["worktree"]: r for r in current.get("repos", [])}
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
        bd, cd = b.get("dangerous", {}), c.get("dangerous", {})
        for k in sorted(set(bd) | set(cd)):
            if bd.get(k) != cd.get(k):
                findings.append({"repo": wt, "kind": "dangerous-key", "key": k, "old": bd.get(k), "new": cd.get(k)})
        for inc in sorted(set(c.get("includes", [])) - set(b.get("includes", []))):
            findings.append({"repo": wt, "kind": "include-added", "path": inc})
        if c.get("config_symlink") and not b.get("config_symlink"):
            findings.append({"repo": wt, "kind": "config-symlinked", "path": c.get("config")})
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
    return findings


def render(f: dict) -> str:
    """One terminal-safe line per finding; every untrusted field sanitized."""
    s = tjor_safeprint.sanitize
    parts = [f"git-check FINDING {s(str(f['repo']))}: {f['kind']}"]
    if f.get("key") is not None:
        parts.append(s(str(f["key"])))
    if f.get("path") is not None:
        parts.append(s(str(f["path"])))
    if "old" in f or "new" in f:
        parts.append(f"{s(json.dumps(f.get('old')))} -> {s(json.dumps(f.get('new')))}")
    if f.get("detail"):
        parts.append(s(str(f["detail"])))
    return " ".join(parts) + " — would run in your HOST git; review before using this repo outside tjor"


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[1] == "snapshot":
        out = None
        roots: list[str] = []
        i = 2
        while i < len(argv):
            if argv[i] == "--out":
                out = argv[i + 1]; i += 2
            else:
                roots.append(argv[i]); i += 1
        snap = snapshot(roots)
        text = json.dumps(snap, indent=1, sort_keys=True)
        if out:
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            tmp = Path(out).with_suffix(".tmp")
            tmp.write_text(text)
            os.replace(tmp, out)
        else:
            print(text)
        print(f"{len(snap['repos'])}", file=sys.stderr)
        return 0
    if len(argv) >= 3 and argv[1] == "check":
        baseline = json.loads(Path(argv[2]).read_text())
        current = snapshot(baseline.get("roots", []))
        findings = diff(baseline, current)
        if "--json" in argv:
            print(json.dumps(findings, indent=1, sort_keys=True))
        else:
            for f in findings:
                print(render(f))
        return 1 if findings else 0
    print("usage: tjor_gitcheck.py snapshot [--out FILE] ROOT... | check BASELINE [--json]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
