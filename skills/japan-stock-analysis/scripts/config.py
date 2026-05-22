"""Configuration loader.

Loads the EDINET API key from ``secret.json`` placed at the Skill root.
The file format is inherited from the pre-research phase:

    {
      "edinet": {
        "api_key": "<your key>"
      }
    }

If the file is missing or malformed, a ``ConfigError`` is raised with a
message describing the expected path so that the SKILL.md handler can ask
the user to place the file before retrying.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from scripts.paths import SECRET_PATH


class ConfigError(RuntimeError):
    """Raised when secret.json is missing or invalid."""


@dataclass(frozen=True)
class EdinetConfig:
    api_key: str


def load_edinet_config(secret_path: Path | None = None) -> EdinetConfig:
    """Load EDINET API config. Raises ``ConfigError`` on any failure."""
    path = secret_path or SECRET_PATH
    if not path.exists():
        raise ConfigError(
            f"secret.json not found at {path}. "
            "Place a JSON file with {\"edinet\": {\"api_key\": \"...\"}} there."
        )
    try:
        with path.open() as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise ConfigError(f"secret.json at {path} is not valid JSON: {e}") from e

    try:
        api_key = data["edinet"]["api_key"]
    except (KeyError, TypeError) as e:
        raise ConfigError(
            f"secret.json at {path} is missing edinet.api_key. "
            "Expected: {\"edinet\": {\"api_key\": \"...\"}}"
        ) from e

    if not isinstance(api_key, str) or not api_key.strip():
        raise ConfigError(f"secret.json at {path}: edinet.api_key must be a non-empty string.")

    return EdinetConfig(api_key=api_key.strip())


def secret_status() -> dict:
    """Return a non-raising summary of secret.json status for diagnostics."""
    info: dict = {"path": str(SECRET_PATH), "exists": SECRET_PATH.exists()}
    if not info["exists"]:
        info["ok"] = False
        info["reason"] = "missing"
        return info
    try:
        load_edinet_config()
        info["ok"] = True
    except ConfigError as e:
        info["ok"] = False
        info["reason"] = str(e)
    return info
