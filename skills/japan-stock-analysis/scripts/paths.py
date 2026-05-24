"""Path resolution centralized for the Skill.

All paths under the Skill itself are resolved from ``__file__`` so that the
Skill keeps working regardless of where users place / symlink it.
Output artifacts go to the user's current working directory (CWD), so each
analysis lands in the project folder the user is working in.

See init_plan.md §3.4 for the policy.
"""

from __future__ import annotations

import os
from pathlib import Path

# scripts/ の親 = Skill ルート
SKILL_ROOT: Path = Path(__file__).resolve().parent.parent

# Skill-internal cache (gitignored). See init_plan.md §3.2.
CACHE_DIR: Path = SKILL_ROOT / "cache"
DOCUMENTS_DIR: Path = CACHE_DIR / "documents"
XBRL_DIR: Path = CACHE_DIR / "xbrl"
DERIVED_DIR: Path = CACHE_DIR / "derived"
PRICES_DIR: Path = CACHE_DIR / "prices"
MAPPINGS_DIR: Path = CACHE_DIR / "mappings"
SPLIT_ADJUST_DIR: Path = CACHE_DIR / "split_adjust"
COMPANY_MAP: Path = CACHE_DIR / "company_map.csv"

# Templates and secret config sit alongside scripts/.
TEMPLATES_DIR: Path = SKILL_ROOT / "templates"
SECRET_PATH: Path = SKILL_ROOT / "secret.json"


OUTPUT_DIR_ENV_VAR = "JAPAN_STOCK_OUTPUT_DIR"


def output_dir() -> Path:
    """Return the artifact output directory.

    Priority:
      1. ``JAPAN_STOCK_OUTPUT_DIR`` env var (escape hatch; must be an existing dir)
      2. ``Path.cwd()`` (last resort)

    Artifacts (HTML report, JSON data) are written to the user's CWD so that
    each project folder accumulates only its own reports. The Skill itself
    must never write reports under SKILL_ROOT — pipeline.py enforces this
    via a sanity check on the resolved output directory.
    """
    override = os.environ.get(OUTPUT_DIR_ENV_VAR)
    if override:
        p = Path(override)
        if p.is_dir():
            return p
    return Path.cwd()


def ensure_cache_dirs() -> None:
    """Create every cache subdirectory if missing. Idempotent."""
    for d in (CACHE_DIR, DOCUMENTS_DIR, XBRL_DIR, DERIVED_DIR, PRICES_DIR, MAPPINGS_DIR, SPLIT_ADJUST_DIR):
        d.mkdir(parents=True, exist_ok=True)
