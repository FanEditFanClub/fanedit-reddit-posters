"""fanedit-social-render shared helpers: env config, state, logging.

All secrets come from environment variables (set on the Render dashboard).
Nothing here touches the Secure Vault or local Google credentials.
"""
from __future__ import annotations

import json
import os

BASE = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(BASE, "state")


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def req_env(name: str) -> str:
    val = env(name)
    if not val:
        raise RuntimeError(f"environment variable {name} is not set")
    return val


def load_config() -> dict:
    with open(os.path.join(BASE, "config.json")) as f:
        return json.load(f)


def load_state(name: str, default: dict) -> dict:
    path = os.path.join(STATE_DIR, name)
    if not os.path.exists(path):
        return default
    with open(path) as f:
        return json.load(f)


def save_state(name: str, data: dict) -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    tmp = os.path.join(STATE_DIR, name + ".tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, os.path.join(STATE_DIR, name))


def log(msg: str) -> None:
    print(msg, flush=True)
