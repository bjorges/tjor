"""Tests for the boundary results matrix generator (#38): source parsing, the
two-way registry<->source cross-check, deterministic render, and --check drift."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import gen_boundary_matrix as gbm


class TestParsers:
    def test_parse_probes(self):
        names = gbm.parse_probes(
            'x\n@probe("first thing works")\ndef f(): ...\n@probe("second: ok")\n')
        assert names == ["first thing works", "second: ok"]

    def test_parse_landlock_literals_only(self):
        text = (
            'ok()  { echo "ok   $1"; }\n'
            'check() { local msg="$1"; then ok "${msg}"; fi; }\n'
            '    check "outside-tree read is kernel-denied" test x\n'
            '    check "masked .env cannot be unlinked in-cage" bash -c y\n'
            '    ok "invalid mode aborts (exit nonzero)"\n'
            '    bad "not a check"\n'
        )
        names = gbm.parse_landlock(text)
        # literals with `$` (the plumbing) and non-check/ok lines are skipped
        assert names == [
            "outside-tree read is kernel-denied",
            "masked .env cannot be unlinked in-cage",
            "invalid mode aborts (exit nonzero)",
        ]

    def test_parse_landlock_dedupes(self):
        text = 'check "same label"\ncheck "same label"\n'
        assert gbm.parse_landlock(text) == ["same label"]


class TestCrossCheck:
    def test_live_registry_matches_live_suites(self):
        # The shipped REGISTRY must exactly cover the real suite sources.
        assert gbm.cross_check(gbm.parsed_names()) == []

    def test_unmapped_probe_is_flagged(self, monkeypatch):
        names = list(gbm.REGISTRY) + ["a brand new probe nobody mapped"]
        errors = gbm.cross_check(names)
        assert any("not in REGISTRY" in e and "brand new probe" in e for e in errors)

    def test_stale_registry_entry_is_flagged(self):
        names = [n for n in gbm.REGISTRY if n != next(iter(gbm.REGISTRY))]
        dropped = next(iter(gbm.REGISTRY))
        errors = gbm.cross_check(names)
        assert any("no matching probe" in e and dropped in e for e in errors)


class TestRender:
    def test_matrix_lists_boundary_rows_grouped_and_deterministic(self):
        names = gbm.parsed_names()
        out1 = gbm.render(names)
        out2 = gbm.render(names)
        assert out1 == out2  # deterministic
        # a known adversarial guarantee appears; a functional check does not
        assert "Outside-tree read is kernel-denied" in out1
        assert "HTTP_PROXY survives the wrap" not in out1
        # capabilities are grouped as headings
        assert "## cage-network" in out1 and "## kernel-sandbox" in out1

    def test_render_matches_committed_matrix(self):
        # The committed docs/boundary-matrix.md is exactly what the generator emits.
        assert gbm.MATRIX_FILE.read_text() == gbm.render(gbm.parsed_names())


class TestCheckMode:
    def test_check_passes_when_up_to_date(self, capsys):
        assert gbm.main(["gen_boundary_matrix.py", "--check"]) == 0

    def test_check_fails_on_stale_doc(self, tmp_path, monkeypatch, capsys):
        stale = tmp_path / "boundary-matrix.md"
        stale.write_text("# stale\n")
        monkeypatch.setattr(gbm, "MATRIX_FILE", stale)
        assert gbm.main(["gen_boundary_matrix.py", "--check"]) == 1

    def test_check_fails_on_registry_drift(self, monkeypatch, capsys):
        # Simulate a new probe added to the suite without a REGISTRY mapping.
        monkeypatch.setattr(gbm, "parsed_names",
                            lambda: list(gbm.REGISTRY) + ["unmapped adversarial probe"])
        assert gbm.main(["gen_boundary_matrix.py", "--check"]) == 1
        assert "out of sync" in capsys.readouterr().err
