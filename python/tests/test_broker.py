"""Unit tests for the credential broker: mint/refresh/revoke and the
BrokerState the proxy uses. GitHub API is stubbed; no network."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tjor_broker as tb


class TestBrokerState:
    def test_pat_source_is_infinite_lived(self):
        st = tb.BrokerState({"source": "pat", "token": "ghp_static"}, clock=lambda: 1000.0)
        cred = st.credential()
        assert cred.value == "ghp_static" and cred.expires_at == float("inf")
        assert st.authorization() == "token ghp_static"

    def test_pat_without_token_fails_closed(self):
        st = tb.BrokerState({"source": "pat"}, clock=lambda: 0.0)
        assert st.credential() is None and st.authorization() is None

    def test_unknown_source_fails_closed(self):
        st = tb.BrokerState({"source": "nope"}, clock=lambda: 0.0)
        assert st.authorization() is None

    def test_github_app_mint_and_refresh(self):
        now = [1000.0]
        calls = []

        def fake_mint(app_id, key, inst, repos, t):
            calls.append(t)
            return tb.Credential(value=f"tok-{len(calls)}", expires_at=t + 3600,
                                 kind="github-app", revoke_url="https://api/revoke")

        st = tb.BrokerState(
            {"source": "github-app", "app_id": "1", "private_key": "k",
             "installation_id": "9", "repositories": ["me/repo"]},
            minter=fake_mint, clock=lambda: now[0],
        )
        assert st.authorization() == "token tok-1"
        # still fresh a minute later — no re-mint
        now[0] = 1060.0
        assert st.authorization() == "token tok-1"
        assert len(calls) == 1
        # near expiry (within REFRESH_SKEW of 3600+1000) — re-mint
        now[0] = 1000.0 + 3600 - tb.REFRESH_SKEW + 1
        assert st.authorization() == "token tok-2"
        assert len(calls) == 2

    def test_mint_failure_fails_closed_then_recovers(self):
        state = {"n": 0}

        def flaky_mint(*a):
            state["n"] += 1
            if state["n"] == 1:
                raise tb.BrokerError("boom")
            return tb.Credential(value="ok", expires_at=a[-1] + 3600, kind="github-app")

        st = tb.BrokerState(
            {"source": "github-app", "app_id": "1", "private_key": "k", "installation_id": "9"},
            minter=flaky_mint, clock=lambda: 0.0,
        )
        assert st.authorization() is None       # first mint failed → fail-closed
        assert st.authorization() == "token ok" # retried on next call


class TestTeardown:
    def test_github_app_teardown_revokes(self, monkeypatch):
        revoked = []
        monkeypatch.setattr(tb, "_api", lambda m, u, t, b=None: (revoked.append((m, u, t)), (204, {}))[1])
        st = tb.BrokerState(
            {"source": "github-app", "app_id": "1", "private_key": "k", "installation_id": "9"},
            minter=lambda *a: tb.Credential("tok", a[-1] + 3600, "github-app",
                                            revoke_url="https://api/installation/token"),
            clock=lambda: 0.0,
        )
        st.authorization()  # mint
        st.teardown()
        assert revoked and revoked[0][0] == "DELETE"

    def test_pat_teardown_forgets_without_api(self, monkeypatch):
        called = []
        monkeypatch.setattr(tb, "_api", lambda *a, **k: called.append(a) or (204, {}))
        st = tb.BrokerState({"source": "pat", "token": "ghp_x"}, clock=lambda: 0.0)
        st.authorization()
        st.teardown()
        assert not called                     # PAT has nothing to revoke server-side
        assert st.authorization() == "token ghp_x"  # re-mints from config after teardown


class TestNeedsRefresh:
    def test_infinite_never_refreshes(self):
        assert not tb.needs_refresh(tb.Credential("x", float("inf"), "pat"), 1e18)

    def test_within_skew_refreshes(self):
        c = tb.Credential("x", 1000.0, "github-app")
        assert tb.needs_refresh(c, 1000.0 - tb.REFRESH_SKEW + 1)
        assert not tb.needs_refresh(c, 1000.0 - tb.REFRESH_SKEW - 100)


class TestJWT:
    def test_app_jwt_structure(self):
        cryptography = pytest.importorskip("cryptography")
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives import serialization

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode()
        jwt = tb._app_jwt("123", pem, 1_700_000_000)
        assert jwt.count(".") == 2
        header, payload, sig = jwt.split(".")
        import base64, json
        def d(s):
            return json.loads(base64.urlsafe_b64decode(s + "=" * (-len(s) % 4)))
        assert d(header)["alg"] == "RS256"
        assert d(payload)["iss"] == "123"

    def test_missing_cryptography_message_is_actionable(self, monkeypatch):
        # Simulate absence: force the import inside _sign_rs256 to fail.
        import builtins
        real_import = builtins.__import__

        def no_crypto(name, *a, **k):
            if name.startswith("cryptography"):
                raise ModuleNotFoundError(name)
            return real_import(name, *a, **k)

        monkeypatch.setattr(builtins, "__import__", no_crypto)
        with pytest.raises(tb.BrokerError, match="cryptography"):
            tb._sign_rs256(b"x", "key")
