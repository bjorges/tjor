"""tjor configuration: the ONE merge path.

Every entry point (launcher, debug commands, generators) obtains effective
configuration through this module — two scripts merging different subsets
of config sections is the drift failure this design forbids (charter L19).

Layers, later wins (deep merge on tables, replace on scalars/arrays):
  1. built-in defaults   (<repo>/config/tjor.toml)
  2. user config         ($TJOR_USER_CONFIG or ~/.config/tjor/config.toml)
"""

from __future__ import annotations

import json
import os
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULTS = REPO_ROOT / "config" / "tjor.toml"

# Config validation (#39): the built-in defaults define the valid SHAPE. An
# override key absent from that shape is almost always a typo — and for a
# security tool a silently-ignored key fails in the dangerous direction (a
# mistyped `[landlock] mode` or a misspelled policy/broker key reads as the
# default, so the operator believes a stricter setting is applied when it is
# not). validate_layer() flags such keys so a caller can warn loudly.
#
# Two exception kinds keep it free of false positives on genuinely open-ended
# config:
#   OPEN_PATHS   — tables whose CHILD keys are free-form (operator- or
#                  tool-named), so nothing under them is validated.
#   EXTRA_KNOWN  — valid keys that are absent from the (commented-out) defaults
#                  shape; accepted, and their subtree is not validated.
OPEN_PATHS = frozenset({
    "profiles",         # name -> host dir
    "versions",         # tool -> version / and versions.sha256 -> per-arch digest
    "images.digests",   # harness -> image digest
})
EXTRA_KNOWN = frozenset({
    "gateway.models",   # array of tables of free-form LiteLLM params
})


def validate_layer(layer: dict, shape: dict, path: str = "") -> list[str]:
    """Return the dotted paths of keys in `layer` that are not part of `shape`
    (the defaults). Open-ended tables and explicitly-known extra keys are not
    flagged. `layer` is a single override layer (user or repo config), so the
    caller can attribute each unknown key to its source file."""
    if path in OPEN_PATHS:
        return []  # free-form table: accept any child
    unknown: list[str] = []
    for key, value in layer.items():
        dotted = f"{path}.{key}" if path else key
        if dotted in EXTRA_KNOWN:
            continue
        if not isinstance(shape, dict) or key not in shape:
            unknown.append(dotted)
            continue
        if isinstance(value, dict) and isinstance(shape.get(key), dict):
            unknown.extend(validate_layer(value, shape[key], dotted))
    return unknown


def user_config_path() -> Path:
    env = os.environ.get("TJOR_USER_CONFIG")
    if env:
        return Path(env)
    xdg = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    return Path(xdg) / "tjor" / "config.toml"


def deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


class ConfigError(SystemExit):
    """Broken configuration is a hard, *clearly reported* error — never a
    silent skip (that could weaken policy) and never a raw traceback."""

    def __init__(self, message: str):
        super().__init__(f"tjor_cfg: ERROR: {message}")


def _load(path: Path) -> dict:
    try:
        with open(path, "rb") as fh:
            return tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: invalid TOML: {exc}")
    except OSError as exc:
        raise ConfigError(f"{path}: unreadable: {exc}")


def repo_config_path() -> Path | None:
    """The current repo's `.tjor/config.toml`, if TJOR_REPO_ROOT names a repo
    that has one. The launcher exports TJOR_REPO_ROOT (the workspace)."""
    root = os.environ.get("TJOR_REPO_ROOT")
    if not root:
        return None
    p = Path(root) / ".tjor" / "config.toml"
    return p if p.is_file() else None


def effective() -> dict:
    config = _load(DEFAULTS)  # defaults must exist; failure here is a broken install
    user = user_config_path()
    if user.is_file():
        config = deep_merge(config, _load(user))
    # Trust-gated repo layer: a repo `.tjor/config.toml` can widen the
    # boundary, so it applies only after the user approved its content.
    repo = repo_config_path()
    if repo is not None:
        import tjor_trust

        if tjor_trust.is_trusted(repo):
            config = deep_merge(config, _load(repo))
        else:
            print(
                f"tjor_cfg: repo config {repo} present but NOT trusted — ignored "
                "(review + approve with: tjor trust)",
                file=sys.stderr,
            )
    return config


def check(stream=None) -> int:
    """Validate the override layers against the defaults shape and WARN loudly
    (never silently) on unknown keys, naming the source file. Returns the count
    of unknown keys found. Non-blocking by design — a stray key warns but does
    not abort (matching the untrusted-repo-config behavior); the point is that a
    typo can no longer pass unnoticed. Kept out of effective() so the launcher's
    many per-key reads stay quiet; call this once per launch."""
    if stream is None:
        stream = sys.stderr
    shape = _load(DEFAULTS)
    total = 0
    layers = [("user config", user_config_path())]
    repo = repo_config_path()
    if repo is not None:
        # Only a trusted repo layer actually applies (effective() gates it the
        # same way), so only validate what would be merged.
        import tjor_trust

        if tjor_trust.is_trusted(repo):
            layers.append(("repo config", repo))
    for label, path in layers:
        if not path.is_file():
            continue
        unknown = validate_layer(_load(path), shape)
        for key in unknown:
            print(
                f"tjor_cfg: WARNING: unknown config key '{key}' in {label} ({path}) "
                "— ignored (typo? it will fall back to the default)",
                file=stream,
            )
        total += len(unknown)
    return total


def get(config: dict, dotted: str, default=None):
    node = config
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def _main(argv: list[str]) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="tjor_cfg")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_get = sub.add_parser("get")
    p_get.add_argument("key")
    p_get.add_argument("--default", default=None)
    sub.add_parser("dump")
    sub.add_parser("check")
    args = parser.parse_args(argv)

    if args.cmd == "check":
        # Warnings go to stderr; exit 0 so a stray key never blocks a launch.
        check()
        return 0

    config = effective()
    if args.cmd == "dump":
        print(json.dumps(config, indent=2))
        return 0
    value = get(config, args.key, args.default)
    if value is None:
        print(f"tjor_cfg: no value for {args.key}", file=sys.stderr)
        return 1
    if isinstance(value, (dict, list)):
        print(json.dumps(value))
    elif isinstance(value, bool):
        print("true" if value else "false")
    else:
        print(value)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
