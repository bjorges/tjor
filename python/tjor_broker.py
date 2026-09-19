"""tjor credential broker: per-session, short-TTL credentials the sandbox can
USE but never POSSESS.

The broker runs host-side (on the egress side of the proxy, never reachable
from the agent network). It mints a credential from a configured source,
hands the *current* secret to the proxy, and the proxy injects it into the
``Authorization`` header of intercepted requests toward the credential's
destination host(s) only — the agent sees only a fixed placeholder.

Sources (v0.1):
  - github-app: a GitHub App installation token (~1h, repo/installation-
    scoped), mintable and refreshable from an app id + private key +
    installation id, revocable via the API.
  - pat: a static personal access token passthrough — no TTL benefit, but
    still kept out of the sandbox (injected at the proxy, never written to
    the agent home). For users without an App.

Fail-closed: a source that cannot mint yields no credential (the caller
starts the session without injection and says so) — never a silent
long-lived fallback. This module has NO network/third-party deps; the
github-app JWT is signed with stdlib + the user's key via `openssl` if the
`cryptography` package is absent, and API calls go through urllib.
"""

from __future__ import annotations

import base64
import calendar
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

GITHUB_API = "https://api.github.com"
# Refresh when this close to expiry (seconds), so a long session never runs
# a request against an expired token.
REFRESH_SKEW = 300


@dataclass
class Credential:
    value: str        # the real secret (bearer/basic token)
    expires_at: float # epoch seconds; float('inf') for non-expiring (PAT)
    kind: str         # "github-app" | "pat"
    revoke_url: str = ""  # API URL to revoke, when revocable


class BrokerError(Exception):
    pass


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _sign_rs256(signing_input: bytes, private_key_pem: str) -> bytes:
    """RS256 signature over the App JWT. Uses `cryptography` (the standard,
    audited RSA implementation); only the github-app source needs it — the
    pat source signs nothing."""
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
    except ModuleNotFoundError:
        raise BrokerError(
            "the 'cryptography' package is required to sign the GitHub App JWT "
            "(pip install cryptography); or use the 'pat' source, which needs no signing"
        ) from None
    try:
        key = serialization.load_pem_private_key(private_key_pem.encode(), password=None)
        return key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    except (ValueError, TypeError) as exc:
        raise BrokerError(f"could not load the GitHub App private key: {exc}") from exc


def _app_jwt(app_id: str, private_key_pem: str, now: int) -> str:
    header = _b64url(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    payload = _b64url(
        json.dumps({"iat": now - 60, "exp": now + 540, "iss": app_id}).encode()
    )
    signing_input = f"{header}.{payload}".encode()
    sig = _b64url(_sign_rs256(signing_input, private_key_pem))
    return f"{header}.{payload}.{sig}"


def _api(method: str, url: str, token: str, body: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        return exc.code, (json.loads(raw) if raw else {"message": str(exc)})
    except OSError as exc:
        raise BrokerError(f"GitHub API unreachable: {exc}") from exc


def mint_github_app(
    app_id: str, private_key_pem: str, installation_id: str,
    repositories: list[str] | None, now: int,
) -> Credential:
    jwt = _app_jwt(app_id, private_key_pem, now)
    body: dict = {}
    if repositories:
        body["repositories"] = repositories
    status, data = _api(
        "POST", f"{GITHUB_API}/app/installations/{installation_id}/access_tokens",
        jwt, body or None,
    )
    if status != 201 or "token" not in data:
        raise BrokerError(f"installation-token mint failed ({status}): {data.get('message', data)}")
    # GitHub returns expires_at as ISO 8601 Zulu (UTC). Parse as UTC via
    # calendar.timegm — time.mktime would (mis)interpret it as local time.
    exp = data.get("expires_at", "")
    try:
        expires = calendar.timegm(time.strptime(exp, "%Y-%m-%dT%H:%M:%SZ"))
    except (ValueError, TypeError):
        expires = now + 3600
    return Credential(
        value=data["token"], expires_at=expires, kind="github-app",
        revoke_url=f"{GITHUB_API}/installation/token",
    )


def revoke(cred: Credential) -> bool:
    """Best-effort revoke. Returns True if revoked or nothing to revoke."""
    if cred.kind == "github-app" and cred.revoke_url:
        status, _ = _api("DELETE", cred.revoke_url, cred.value)
        return status in (204, 401, 404)  # gone/expired counts as revoked
    return True  # PAT: nothing to revoke server-side; caller forgets it


def needs_refresh(cred: Credential, now: float) -> bool:
    return cred.expires_at != float("inf") and cred.expires_at - now <= REFRESH_SKEW


class BrokerState:
    """Holds the session's live credential inside the proxy (egress side,
    unreachable from the agent). Mints on first use and refreshes before
    expiry. ``authorization()`` is what the addon injects; it returns None
    fail-closed when no credential can be produced — the addon then strips
    the placeholder and lets the upstream reject, never leaking a stale or
    placeholder secret."""

    def __init__(self, config: dict, minter=mint_github_app, clock=time.time):
        self.config = config
        self._cred: Credential | None = None
        self._minter = minter        # injectable for tests
        self._clock = clock

    def _mint(self) -> None:
        src = self.config.get("source")
        now = int(self._clock())
        if src == "pat":
            token = self.config.get("token")
            if not token:
                raise BrokerError("pat source configured without a token")
            self._cred = Credential(value=token, expires_at=float("inf"), kind="pat")
        elif src == "github-app":
            self._cred = self._minter(
                self.config["app_id"], self.config["private_key"],
                self.config["installation_id"],
                self.config.get("repositories") or None, now,
            )
        else:
            raise BrokerError(f"unknown broker source: {src!r}")

    def credential(self) -> Credential | None:
        now = self._clock()
        if self._cred is None or needs_refresh(self._cred, now):
            try:
                self._mint()
            except BrokerError:
                self._cred = None
        return self._cred

    def authorization(self) -> str | None:
        cred = self.credential()
        if cred is None:
            return None
        # GitHub accepts installation tokens and PATs as `Authorization: token <t>`.
        return f"token {cred.value}"

    def teardown(self) -> bool:
        """Revoke and forget. Returns whether revocation actually succeeded
        (True also when there was nothing to revoke); callers must not report
        success unconditionally."""
        ok = True
        if self._cred is not None:
            ok = revoke(self._cred)
            self._cred = None
        return ok


def load_config(path: str) -> dict:
    with open(path, "rb") as fh:
        return json.loads(fh.read().decode("utf-8"))


class KubeMultiBroker:
    """Per-cluster ServiceAccount bearer tokens for the ``kube`` source
    (#26 single-cluster, #57 multi-cluster). Each configured cluster's token
    is minted host-side at launch and injected only toward that cluster's
    exact API origin (host + port, #49); there is no in-cage refresh (the
    tokens are short-TTL, and a long session relaunches). Unlike the
    GitHub sources, the Kubernetes API server requires the **Bearer** scheme,
    so ``authorization()`` returns ``Bearer <token>`` (not ``token <t>``).

    Config shape (``broker.json``)::

        {"source": "kube", "clusters": [{"origin": "host:port", "token": "..."}]}

    Origins are parsed with the shared broker-host parser (robust IPv6
    bracketing) and canonicalized with the shared host canonicalizer, so a
    lookup by a request's ``(host, port)`` matches exactly what the launcher
    recorded. A single-cluster session is simply the one-entry case.
    """

    def __init__(self, config: dict):
        # Local imports: keep this module's top-level dependency surface clean;
        # these siblings are pure (no third-party deps) and always ship beside
        # the broker in the proxy image and on the test path.
        import tjor_identity
        import tjor_policy

        self._by_origin: dict[tuple[str, int], str] = {}
        clusters = config.get("clusters") or []
        for c in clusters:
            origin, token = c.get("origin"), c.get("token")
            if not origin or not token:
                raise BrokerError(f"kube cluster entry missing origin/token: {c!r}")
            pairs = tjor_identity.parse_broker_hosts(origin)
            if len(pairs) != 1 or pairs[0][1] is None:
                raise BrokerError(f"kube cluster origin must be one host:port: {origin!r}")
            host, port = pairs[0]
            key = (tjor_policy._canon_host(host), int(port))
            if key in self._by_origin:
                raise BrokerError(f"duplicate kube cluster origin: {origin!r}")
            self._by_origin[key] = token
        if not self._by_origin:
            raise BrokerError("kube broker configured with no clusters")

    def authorization(self, host: str, port: int) -> str | None:
        """The Bearer value to inject toward ``host:port``, or None
        (fail-closed) when that origin is not a configured cluster."""
        import tjor_policy

        token = self._by_origin.get((tjor_policy._canon_host(host), int(port)))
        return f"Bearer {token}" if token is not None else None

    def teardown(self) -> bool:
        """Forget the tokens. The SA tokens are short-TTL and have no
        server-side revoke endpoint here, so this just drops them from memory;
        it returns True (nothing left to revoke), matching the pat contract."""
        self._by_origin = {}
        return True


def write_kube_broker_json(path: str, clusters):
    """Write the v2 ``kube`` broker.json atomically at 0600 (proxy-only, never
    world-readable between create and use). ``clusters`` is an iterable of
    ``(origin, token)`` pairs. Kept beside the launcher's ``write_broker_json``
    so the secret is created with the mode, not chmod'd after."""
    import os

    doc = {"source": "kube", "clusters": [{"origin": o, "token": t} for o, t in clusters]}
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(json.dumps(doc))
