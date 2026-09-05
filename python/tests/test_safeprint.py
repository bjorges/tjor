"""Terminal-escape sanitizer (defends the trust-review + denial-log display).

The threat: untrusted content (a repo `.tjor` file the operator is about to
approve, or an attacker-influenced denied hostname) reaching the terminal as
raw ANSI/OSC/bidi control bytes, so the operator sees something other than what
the content-hash pins. Every such control must be rendered visible; legitimate
text must survive untouched."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tjor_safeprint as sp


class TestNeutralized:
    def test_esc_becomes_visible_caret(self):
        # A CSI colour sequence must not survive as a live escape.
        out = sp.sanitize("\x1b[31mred\x1b[0m")
        assert "\x1b" not in out
        assert out == "^[[31mred^[[0m"

    def test_osc_title_spoof_neutralized(self):
        # OSC (ESC ]) window-title / hyperlink injection.
        out = sp.sanitize("\x1b]0;pwned\x07safe")
        assert "\x1b" not in out and "\x07" not in out
        assert "^[" in out and "^G" in out  # ESC -> ^[, BEL -> ^G

    def test_bidi_override_rendered_visible(self):
        # U+202E RIGHT-TO-LEFT OVERRIDE can visually reorder a line.
        out = sp.sanitize("allow = [‮]evil")
        assert "‮" not in out
        assert "<U+202E>" in out

    def test_zero_width_and_c1_visible(self):
        out = sp.sanitize("a​b\x85c")  # ZWSP + NEL (C1)
        assert "​" not in out and "\x85" not in out
        assert "<U+200B>" in out and "<0x85>" in out

    def test_carriage_return_and_del(self):
        out = sp.sanitize("line\rONE\x7f")
        assert "\r" not in out and "\x7f" not in out
        assert "^M" in out and "^?" in out

    def test_raw_undecodable_bytes_preserved_and_escaped(self):
        # surrogateescape path: a lone 0xFF byte must not crash and must show.
        text = b"host\xffname".decode("utf-8", "surrogateescape")
        out = sp.sanitize(text)
        assert "<0xff>" in out


class TestPreserved:
    def test_plain_text_untouched(self):
        s = "github.com\napi.anthropic.com\n"
        assert sp.sanitize(s) == s

    def test_newline_and_tab_kept(self):
        assert sp.sanitize("a\tb\nc") == "a\tb\nc"

    def test_legit_unicode_passthrough(self):
        s = "naïve café — 日本語 ✓"
        assert sp.sanitize(s) == s

    def test_toml_body_untouched(self):
        body = '[hosts]\nallow = [\n  "github.com",\n]\n'
        assert sp.sanitize(body) == body


class TestCli:
    def test_stdin_filter(self, capsysbinary=None):
        # exercise the file path branch (deterministic across platforms)
        import subprocess

        p = Path(__file__).resolve().parents[1] / "tjor_safeprint.py"
        tmp = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
        f = tmp / "_escape_probe.txt"
        f.parent.mkdir(exist_ok=True)
        f.write_bytes(b"\x1b[2Jclear\n")
        try:
            r = subprocess.run([sys.executable, str(p), str(f)], capture_output=True, text=True)
            assert r.returncode == 0
            assert "\x1b" not in r.stdout
            assert r.stdout == "^[[2Jclear\n"
        finally:
            f.unlink()
