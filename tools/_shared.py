"""Shared config and DB helpers for all Hermes tools.

Reads from environment variables set in Hermes config or .env.
Exposes get_conn(), get_settings(), and VAULT_ROOT.
"""
import os
import sys
from pathlib import Path

# Make the existing cere-bro app importable from tools/.
# Path: tools/_shared.py -> tools/ -> personal-assistant/ -> personal-projects/ -> cere-bro/
_CEREBRO_ROOT = Path(__file__).resolve().parent.parent.parent / "cere-bro"
if str(_CEREBRO_ROOT) not in sys.path:
    sys.path.insert(0, str(_CEREBRO_ROOT))

from lib.db import get_conn as _get_conn, init_db  # noqa: E402
from lib.config import Settings  # noqa: E402

_settings: Settings | None = None


def get_settings() -> Settings:
    """Return cached settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def get_conn():
    """Return a new SQLite connection to the cerebro database."""
    return _get_conn(get_settings().db_path)


# Vault root path for Obsidian operations (from settings)
VAULT_ROOT = get_settings().vault_root
