"""
config_manager.py

Simple persistent settings manager for Swift Alliance apps.

Stores a small JSON config at ./config.json with keys:
  - schema_path: path to the pain.001 XSD in the repo (relative or absolute)
  - logo_path: path to the uploaded logo file inside ./assets/

Functions:
  - load_config() -> dict
  - save_config(data: dict) -> None

This is intentionally small and synchronous (file-based). It is suitable for
local deployments and the Streamlit demo. For multi-user production use a
centralized configuration store (database, key/value store, or vault).
"""

import json
import os
from typing import Dict, Any

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "config.json")


def _default_config() -> Dict[str, Any]:
    return {
        "schema_path": None,
        "logo_path": None
    }


def load_config() -> Dict[str, Any]:
    """Load config from disk; return defaults if missing or invalid."""
    if not os.path.exists(CONFIG_FILE):
        return _default_config()
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Ensure keys exist
        cfg = _default_config()
        cfg.update({k: data.get(k, cfg[k]) for k in cfg.keys()})
        return cfg
    except Exception:
        # Avoid failing the app for simple config issues
        return _default_config()


def save_config(data: Dict[str, Any]) -> None:
    """Save provided keys (schema_path, logo_path) to the config file."""
    cfg = _default_config()
    cfg.update({k: data.get(k, cfg[k]) for k in cfg.keys()})
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception as e:
        # Quietly fail - caller can show message
        raise