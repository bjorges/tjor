"""Session state helper (#68): one tier definition, atomic metadata, an
inventory that never follows a symlink and never calls unreadable state old."""
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tjor_state as ts

HELPER = Path(__file__).resolve().parents[1] / "tjor_state.py"


def _run(*args):
    return subprocess.run([sys.executable, "-I", str(HELPER), *args], capture_output=True, text=True)


# ---- tiers ------------------------------------------------------------------

def test_creds_tier_is_the_documented_set(tmp_path):
    expected = {
        "broker", "proxy-ca", "ca.pem",
        "home/.local/share/opencode/auth.json",
        "home/.config/gh",
        "home/.claude/.credentials.json",
        "home/.claude.json",
        "home/.claude/backups",
    }
    assert set(ts.TIERS["creds"]) == expected
    assert set(ts.tier_paths("creds", str(tmp_path))) == {str(tmp_path / p) for p in expected}


def test_reset_tiers_match_the_launcher_history(tmp_path):
    # The cache and sessions tiers are exactly what cmd_reset's bash case held.
    assert ts.tier_paths("cache", str(tmp_path)) == [str(tmp_path / "home/.cache")]
    assert ts.tier_paths("sessions", str(tmp_path)) == [
        str(tmp_path / "home/.local/state"),
        str(tmp_path / "home/.local/share/opencode/storage"),
        str(tmp_path / "home/.local/share/opencode/log"),
    ]


def test_all_tier_is_the_directory_itself(tmp_path):
    assert ts.tier_paths("all", str(tmp_path)) == [str(tmp_path)]


def test_tier_cli_prints_absolute_paths_and_rejects_unknown(tmp_path):
    r = _run("tier", "creds", str(tmp_path))
    assert r.returncode == 0
    assert r.stdout.splitlines() == ts.tier_paths("creds", str(tmp_path))
    r = _run("tier", "secrets", str(tmp_path))
    assert r.returncode != 0 and r.stdout == "" and "unknown tier" in r.stderr


# ---- duration ---------------------------------------------------------------

@pytest.mark.parametrize("text,seconds", [("30d", 30 * 86400), ("12h", 12 * 3600), ("5m", 300), ("45s", 45), ("0d", 0)])
def test_duration_units(text, seconds):
    assert ts.parse_duration(text) == seconds
    r = _run("duration", text)
    assert r.returncode == 0 and r.stdout.strip() == str(seconds)


@pytest.mark.parametrize("text", ["30", "-1d", "1w", "", "d", "1.5h", "1 d"])
def test_duration_rejects(text):
    with pytest.raises(ValueError):
        ts.parse_duration(text)
    r = _run("duration", text)
    assert r.returncode != 0 and r.stdout == "" and "not a duration" in r.stderr


# ---- meta-write -------------------------------------------------------------

def test_meta_first_write(tmp_path):
    meta = ts.write_meta(str(tmp_path), session="repo-abcd1234-a", workspace="/w", harness="opencode",
                         profile_name="rev", task="T-1", now=1000)
    on_disk = json.loads((tmp_path / "meta.json").read_text())
    assert on_disk == meta
    assert on_disk == {
        "schema": 1, "session": "repo-abcd1234-a", "workspace": "/w", "harness": "opencode",
        "profile": {"name": "rev"}, "task": "T-1", "created": 1000, "last_launch": 1000, "launches": 1,
    }
    assert set(on_disk) == set(ts.META_KEYS)


def test_meta_relaunch_keeps_created_bumps_launches_updates_task(tmp_path):
    ts.write_meta(str(tmp_path), session="s", workspace="/w", harness="opencode", task="T-1", now=1000)
    ts.write_meta(str(tmp_path), session="s", workspace="/w", harness="claude", profile_dir="/p", task="T-2", now=2000)
    m = json.loads((tmp_path / "meta.json").read_text())
    assert m["created"] == 1000 and m["last_launch"] == 2000 and m["launches"] == 2
    assert m["task"] == "T-2" and m["harness"] == "claude" and m["profile"] == {"dir": "/p"}


def test_meta_no_profile_no_task_are_null(tmp_path):
    m = ts.write_meta(str(tmp_path), session="s", workspace="/w", harness="opencode", now=1)
    assert m["profile"] is None and m["task"] is None


def test_meta_unreadable_existing_file_is_rewritten(tmp_path):
    (tmp_path / "meta.json").write_text("{not json")
    m = ts.write_meta(str(tmp_path), session="s", workspace="/w", harness="opencode", now=5)
    assert m["launches"] == 1 and m["created"] == 5
    assert json.loads((tmp_path / "meta.json").read_text())["launches"] == 1


def test_meta_temp_file_lives_in_the_state_dir(tmp_path, monkeypatch):
    seen = {}
    real_mkstemp = ts.tempfile.mkstemp
    real_replace = ts.os.replace

    def spy_mkstemp(*a, **kw):
        seen["dir"] = kw.get("dir")
        return real_mkstemp(*a, **kw)

    def spy_replace(src, dst):
        seen["src"], seen["dst"] = src, dst
        return real_replace(src, dst)

    monkeypatch.setattr(ts.tempfile, "mkstemp", spy_mkstemp)
    monkeypatch.setattr(ts.os, "replace", spy_replace)
    ts.write_meta(str(tmp_path), session="s", workspace="/w", harness="opencode", now=1)
    assert seen["dir"] == str(tmp_path)
    assert Path(seen["src"]).parent == tmp_path and seen["dst"] == str(tmp_path / "meta.json")
    assert not list(tmp_path.glob(".meta.*"))   # no temp file left behind


def test_meta_cli_requires_identity(tmp_path):
    r = _run("meta-write", str(tmp_path), "--session", "s")
    assert r.returncode == 2 and not (tmp_path / "meta.json").exists()
    r = _run("meta-write", str(tmp_path), "--session", "s", "--workspace", "/w", "--harness", "opencode", "--task", "T")
    assert r.returncode == 0
    assert json.loads((tmp_path / "meta.json").read_text())["task"] == "T"


def test_meta_cli_fails_loudly_when_the_dir_is_missing(tmp_path):
    r = _run("meta-write", str(tmp_path / "nope"), "--session", "s", "--workspace", "/w", "--harness", "opencode")
    assert r.returncode == 1 and "tjor_state:" in r.stderr


# ---- inventory --------------------------------------------------------------

def _deep_file(base: Path, depth: int, name="h1") -> Path:
    p = base
    for i in range(depth):
        p = p / f"d{i}"
    p.mkdir(parents=True)
    f = p / name
    f.write_text("x")
    return f


def _set_mtime(p: Path, t: int):
    os.utime(p, (t, t), follow_symlinks=False)


def test_inventory_legacy_dir_uses_deep_file_time(tmp_path):
    root = tmp_path / "sessions"
    legacy = root / "repo-aaaaaaaa"
    f = _deep_file(legacy / "home" / ".local" / "share" / "opencode" / "storage", 6)   # 11 levels down
    for p in [legacy, *legacy.rglob("*")]:
        _set_mtime(p, 1_000)
    _set_mtime(f, 5_000)
    (legacy / "home" / ".local" / "share" / "opencode" / "auth.json").write_text("t")
    _set_mtime(legacy / "home" / ".local" / "share" / "opencode" / "auth.json", 900)
    _set_mtime(legacy / "home" / ".local" / "share" / "opencode", 900)
    [rec] = ts.inventory(str(root))
    assert rec["id"] == "repo-aaaaaaaa" and rec["kind"] == "dir"
    assert rec["workspace"] is None and rec["harness"] is None and rec["launches"] is None
    assert rec["last_active"] == 5_000
    assert rec["creds"] == ["home/.local/share/opencode/auth.json"]


def test_inventory_current_dir_floors_by_last_launch(tmp_path):
    root = tmp_path / "sessions"
    cur = root / "repo-bbbbbbbb-x"
    (cur / "home").mkdir(parents=True)
    ts.write_meta(str(cur), session="repo-bbbbbbbb-x", workspace="/work", harness="claude", now=9_000)
    for p in [cur, *cur.rglob("*")]:
        _set_mtime(p, 100)
    [rec] = ts.inventory(str(root))
    assert rec["workspace"] == "/work" and rec["harness"] == "claude" and rec["launches"] == 1
    assert rec["last_active"] == 9_000
    assert rec["creds"] == []


def test_inventory_symlink_entry_is_reported_and_never_followed(tmp_path, monkeypatch):
    root = tmp_path / "sessions"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    canary = outside / "canary"
    canary.write_text("x")
    (root / "planted").symlink_to(outside)
    touched = []
    real_lstat = os.lstat

    def spy_lstat(p, *a, **kw):
        touched.append(os.fspath(p))
        return real_lstat(p, *a, **kw)

    monkeypatch.setattr(ts.os, "lstat", spy_lstat)
    monkeypatch.setattr(ts.os, "stat", lambda *a, **kw: pytest.fail("os.stat follows symlinks and must not be used"))
    [rec] = ts.inventory(str(root))
    assert rec == {"id": "planted", "kind": "link", "workspace": None, "harness": None,
                   "last_active": None, "launches": None, "creds": []}
    assert str(canary) not in touched and str(outside) not in touched


def test_inventory_other_entry_is_reported(tmp_path):
    root = tmp_path / "sessions"
    root.mkdir()
    (root / "stray.txt").write_text("x")
    [rec] = ts.inventory(str(root))
    assert rec["id"] == "stray.txt" and rec["kind"] == "other" and rec["last_active"] is None


@pytest.mark.skipif(os.geteuid() == 0, reason="root can read anything")
def test_inventory_unreadable_subdir_is_unknown_not_stale(tmp_path):
    root = tmp_path / "sessions"
    d = root / "repo-cccccccc"
    (d / "home" / "readable").mkdir(parents=True)
    locked = d / "home" / "locked"
    locked.mkdir()
    (locked / "secret").write_text("x")
    for p in [d, *d.rglob("*")]:
        _set_mtime(p, 1_000)
    _set_mtime(d / "home" / "readable", 7_000)
    locked.chmod(0)
    try:
        [rec] = ts.inventory(str(root))
    finally:
        locked.chmod(stat.S_IRWXU)
    assert rec["last_active"] is None


@pytest.mark.skipif(os.geteuid() == 0, reason="root can read anything")
def test_inventory_unreadable_dir_with_metadata_is_still_unknown(tmp_path):
    # The floor is a lower bound; with an incomplete walk the honest answer is
    # unknown (never age-eligible), not "at least the last launch".
    root = tmp_path / "sessions"
    d = root / "repo-dddddddd"
    (d / "home" / "locked").mkdir(parents=True)
    ts.write_meta(str(d), session="s", workspace="/w", harness="opencode", now=9_000)
    (d / "home" / "locked").chmod(0)
    try:
        [rec] = ts.inventory(str(root))
    finally:
        (d / "home" / "locked").chmod(stat.S_IRWXU)
    assert rec["last_active"] is None and rec["workspace"] == "/w"


def test_inventory_skips_the_lock_dir(tmp_path):
    root = tmp_path / "sessions"
    (root / ".locks" / "repo-x").mkdir(parents=True)
    (root / "repo-x").mkdir()
    assert [r["id"] for r in ts.inventory(str(root))] == ["repo-x"]


def test_inventory_cli_format_and_sorting(tmp_path):
    root = tmp_path / "sessions"
    (root / "b-dir" / "broker").mkdir(parents=True)
    (root / "a-dir" / "home").mkdir(parents=True)
    ts.write_meta(str(root / "a-dir"), session="a-dir", workspace="/w a", harness="opencode", task="T", now=50)
    r = _run("inventory", str(root))
    assert r.returncode == 0
    lines = r.stdout.splitlines()
    assert [ln.split(ts.US)[0] for ln in lines] == ["a-dir", "b-dir"]
    a = lines[0].split(ts.US)
    assert a[1] == "dir" and a[2] == "/w a" and a[3] == "opencode" and a[5] == "1" and a[6] == "-"
    assert int(a[4]) >= 50
    b = lines[1].split(ts.US)
    assert b[2] == "-" and b[6] == "broker"


def test_inventory_cli_prints_nothing_when_it_fails_midway(tmp_path, monkeypatch, capsys):
    root = tmp_path / "sessions"
    (root / "a").mkdir(parents=True)
    (root / "b").mkdir()
    calls = {"n": 0}
    real = ts.last_activity

    def flaky(path):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("disk went away")
        return real(path)

    monkeypatch.setattr(ts, "last_activity", flaky)
    assert ts.main(["tjor_state.py", "inventory", str(root)]) == 1
    out = capsys.readouterr()
    assert out.out == "" and "disk went away" in out.err


def test_inventory_cli_missing_root_fails(tmp_path):
    r = _run("inventory", str(tmp_path / "nope"))
    assert r.returncode == 1 and r.stdout == ""


def test_usage_exit_code():
    r = _run()
    assert r.returncode == 2 and r.stdout == "" and "usage:" in r.stderr
