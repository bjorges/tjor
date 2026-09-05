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


def effective() -> dict:
    config = _load(DEFAULTS)  # defaults must exist; failure here is a broken install
    user = user_config_path()
    if user.is_file():
        config = deep_merge(config, _load(user))
    return config


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
    args = parser.parse_args(argv)

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
