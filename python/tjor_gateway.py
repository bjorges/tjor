#!/usr/bin/env python3
"""LiteLLM gateway (D4) host-side helpers.

The gateway is an optional LiteLLM sidecar on the egress network. Two pieces of
host-side logic support it, kept here so they are pure and unit-tested:

  * `ensure_master_key()` — the per-install gateway credential. Generated once
    with a CSPRNG and persisted 0600 under the user config dir (NOT the session
    dir that feeds the config hash). It is the gateway's authn secret; it lives
    only in the gateway + proxy sidecars (both egress side) and the proxy
    injects it toward the gateway host, so the agent never holds it.
  * `render_config()` — the LiteLLM `config.yaml` (emitted as JSON, which
    LiteLLM's YAML loader accepts) from `[gateway].models`. It carries NO
    secret: provider keys are referenced as `os.environ/<VAR>` and resolved from
    the sidecar env; the master key comes from `LITELLM_MASTER_KEY`, not this
    file.

The launcher calls these; the proxy does the injection (reusing the D2 path).
"""
import json
import os
import pathlib
import secrets
import sys
import tomllib

MASTER_KEY_PREFIX = "sk-tjor-"

# The ONLY paths reachable on the gateway host: OpenAI- and Anthropic-compatible
# inference plus health. Everything else (the whole LiteLLM management API) is
# denied by construction — the gateway host is default-denied (hosts.block) and
# only these are carved back in (paths.allow). Adding a new admin route upstream
# does NOT open it. LiteLLM serves inference both with and without the /v1 prefix.
INFERENCE_PATHS = (
    "/chat/completions", "/v1/chat/completions",
    "/completions", "/v1/completions",
    "/embeddings", "/v1/embeddings",
    "/models", "/v1/models",
    "/messages", "/v1/messages",           # Anthropic-format passthrough
    "/health/liveliness", "/health/readiness",
)


def master_key_path():
    """Where the per-install master key is stored (0600). Overridable via
    TJOR_GATEWAY_KEY_FILE (used by tests); else under the user config dir —
    deliberately NOT the per-session dir, so the key is never in a config hash."""
    override = os.environ.get("TJOR_GATEWAY_KEY_FILE")
    if override:
        return pathlib.Path(override)
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
        os.path.expanduser("~"), ".config"
    )
    return pathlib.Path(base) / "tjor" / "gateway-master.key"


def ensure_master_key(path=None):
    """Return the per-install gateway master key, generating + persisting it
    (0600, atomically) on first use and reusing it thereafter."""
    p = pathlib.Path(path) if path is not None else master_key_path()
    if p.is_file():
        existing = p.read_text().strip()
        if existing:
            return existing
    key = MASTER_KEY_PREFIX + secrets.token_urlsafe(32)
    p.parent.mkdir(parents=True, exist_ok=True)
    # 0600 from creation (os.open with mode), so the secret is never briefly
    # world-readable between write and a separate chmod.
    fd = os.open(str(p), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(key + "\n")
    return key


def rotate_master_key(path=None):
    """Delete the persisted master key and generate a fresh one. The next
    gateway-enabled session picks it up; sessions already running keep the old
    key until relaunched (the proxy + gateway hold the value they started with)."""
    p = pathlib.Path(path) if path is not None else master_key_path()
    if p.is_symlink() or p.exists():
        p.unlink()
    return ensure_master_key(p)


def render_config(models):
    """Render a LiteLLM config (JSON) from `[gateway].models`.

    `models` is a list of dicts, each with a `name` (the model_name the agent
    asks for) and the remaining keys forming `litellm_params` (e.g. `model`,
    `api_key`, `api_base`). Provider secrets must be given as `os.environ/<VAR>`
    references — never literal keys — so this file carries no secret. The master
    key is supplied to LiteLLM via the LITELLM_MASTER_KEY env, not here.
    """
    model_list = []
    for m in models:
        if "name" not in m:
            raise ValueError(f"gateway model missing 'name': {m!r}")
        params = {k: v for k, v in m.items() if k != "name"}
        # Defense in depth for the "this file carries no secret" guarantee: a
        # provider key MUST be an env reference (os.environ/<VAR>), never a
        # literal — otherwise an operator's paste would write a live secret to
        # config.yaml on disk. Refuse a literal rather than silently persist it.
        ak = params.get("api_key")
        if isinstance(ak, str) and ak and not ak.startswith("os.environ/"):
            raise ValueError(
                f"gateway model {m['name']!r}: api_key must be an env reference "
                f"like 'os.environ/OPENAI_API_KEY', not a literal secret"
            )
        model_list.append({"model_name": m["name"], "litellm_params": params})
    return json.dumps({"model_list": model_list}, indent=2) + "\n"


def _toml_str(s):
    """Quote a value as a TOML basic string."""
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def augment_policy(base_toml, gateway_host, inference_paths=INFERENCE_PATHS):
    """Return a policy TOML that makes `gateway_host` an inference-ONLY host on
    top of the base policy: the host joins `hosts.block` (so it is denied for
    every path) and each inference path is added as a `paths.allow` carve-out
    (rescuing only those). Every other path on the gateway — the management API,
    known or future — is denied by construction. The base policy's own
    allow/block/path rules are preserved. Comments are not (this is a generated
    session policy); the result is re-validated by the policy parser downstream.
    """
    data = tomllib.loads(base_toml)
    mode = data.get("mode", "strict-allow")
    hosts = data.get("hosts", {}) if isinstance(data.get("hosts"), dict) else {}
    allow = [h for h in hosts.get("allow", []) if isinstance(h, str)]
    block = [h for h in hosts.get("block", []) if isinstance(h, str)]
    if gateway_host not in block:
        block.append(gateway_host)
    paths = data.get("paths", {}) if isinstance(data.get("paths"), dict) else {}
    p_allow = [(r["host"], r["path"]) for r in paths.get("allow", [])
               if isinstance(r, dict) and "host" in r and "path" in r]
    p_block = [(r["host"], r["path"]) for r in paths.get("block", [])
               if isinstance(r, dict) and "host" in r and "path" in r]
    for pth in inference_paths:
        if (gateway_host, pth) not in p_allow:
            p_allow.append((gateway_host, pth))

    out = [f"mode = {_toml_str(mode)}", "", "[hosts]",
           "allow = [" + ", ".join(_toml_str(h) for h in allow) + "]",
           "block = [" + ", ".join(_toml_str(h) for h in block) + "]", ""]
    for h, p in p_allow:
        out += ["[[paths.allow]]", f"host = {_toml_str(h)}", f"path = {_toml_str(p)}", ""]
    for h, p in p_block:
        out += ["[[paths.block]]", f"host = {_toml_str(h)}", f"path = {_toml_str(p)}", ""]
    return "\n".join(out) + "\n"


def _main(argv):
    if len(argv) == 4 and argv[1] == "augment-policy":
        # augment-policy <base-policy-file> <gateway-host>  -> print augmented TOML
        base = pathlib.Path(argv[2]).read_text()
        sys.stdout.write(augment_policy(base, argv[3]))
        return
    if len(argv) >= 2 and argv[1] == "master-key":
        # master-key [path]  -> ensure + print the key (used by the launcher)
        print(ensure_master_key(argv[2] if len(argv) > 2 else None))
        return
    if len(argv) >= 2 and argv[1] == "rotate-key":
        # rotate-key [path]  -> regenerate + print the new key
        print(rotate_master_key(argv[2] if len(argv) > 2 else None))
        return
    if len(argv) == 3 and argv[1] == "render-config":
        # render-config <models-json>  -> print the LiteLLM config
        sys.stdout.write(render_config(json.loads(argv[2])))
        return
    sys.exit("usage: tjor_gateway.py {master-key [path] | render-config <models-json>}")


if __name__ == "__main__":
    _main(sys.argv)
