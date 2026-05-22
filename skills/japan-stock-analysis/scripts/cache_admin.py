"""Cache administration CLI.

Phase P1 scope: only the ``info`` subcommand is implemented. The ``clear``
subcommands are stubbed and will be filled in during Phase P6 (see plan.md
§5 Phase table and §4.3 for the full command surface).

Usage:
    python3 ${CLAUDE_SKILL_DIR}/scripts/cache_admin.py info
    python3 ${CLAUDE_SKILL_DIR}/scripts/cache_admin.py info --sec-code 7203
"""

from __future__ import annotations

# Allow running both as `python scripts/cache_admin.py` (direct, the Skill
# convention with ${CLAUDE_SKILL_DIR}) and as `python -m scripts.cache_admin`
# (module form, used by pytest). When run directly, __package__ is empty —
# add Skill root to sys.path so absolute `from scripts...` imports resolve.
if __package__ in (None, ""):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from scripts import paths
from scripts.config import secret_status


def _dir_summary(path: Path, pattern: str = "*") -> dict:
    """Summarize a cache directory: file count, total size, latest mtime."""
    if not path.exists():
        return {"exists": False, "count": 0, "size_bytes": 0, "latest_mtime": None}
    files = [p for p in path.glob(pattern) if p.is_file()]
    total = sum(p.stat().st_size for p in files)
    latest = max((p.stat().st_mtime for p in files), default=None)
    latest_iso = (
        datetime.fromtimestamp(latest, tz=timezone.utc).isoformat() if latest else None
    )
    return {
        "exists": True,
        "count": len(files),
        "size_bytes": total,
        "latest_mtime": latest_iso,
    }


def _file_summary(path: Path) -> dict:
    if not path.exists():
        return {"exists": False, "size_bytes": 0, "mtime": None}
    st = path.stat()
    return {
        "exists": True,
        "size_bytes": st.st_size,
        "mtime": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
    }


def collect_info(sec_code: str | None = None) -> dict:
    """Build a structured snapshot of the cache state."""
    info: dict = {
        "skill_root": str(paths.SKILL_ROOT),
        "cache_dir": str(paths.CACHE_DIR),
        "output_dir": str(paths.output_dir()),
        "secret": secret_status(),
        "company_map": _file_summary(paths.COMPANY_MAP),
        "documents": _dir_summary(paths.DOCUMENTS_DIR, "*.json"),
        "xbrl": _dir_summary(paths.XBRL_DIR, "*.zip"),
        "derived": _dir_summary(paths.DERIVED_DIR, "*.csv"),
        "prices": _dir_summary(paths.PRICES_DIR, "*.csv"),
        "mappings": _dir_summary(paths.MAPPINGS_DIR, "*.json"),
        "split_adjust": _dir_summary(paths.SPLIT_ADJUST_DIR, "*.json"),
    }
    if sec_code:
        info["sec_code"] = sec_code
        info["per_sec_code"] = {
            "timeseries": _file_summary(paths.DERIVED_DIR / f"timeseries_{sec_code}.csv"),
            "metrics": _file_summary(paths.DERIVED_DIR / f"metrics_{sec_code}.csv"),
            "prices": _file_summary(paths.PRICES_DIR / f"{sec_code}.csv"),
            "mappings": _file_summary(paths.MAPPINGS_DIR / f"{sec_code}.json"),
            "split_adjust": _file_summary(paths.SPLIT_ADJUST_DIR / f"{sec_code}.json"),
        }
    return info


def _cmd_info(args: argparse.Namespace) -> int:
    info = collect_info(sec_code=args.sec_code)
    json.dump(info, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


def _cmd_clear(args: argparse.Namespace) -> int:
    # TODO(P6): implement type-based and sec-code-based clear with --confirm gating.
    # See plan.md §4.3 for the full flag surface (--derived, --prices, --mappings,
    # --documents, --xbrl, --sec-code, --types, --all, --confirm).
    sys.stderr.write("cache_admin clear is not implemented yet (planned for Phase P6).\n")
    return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cache_admin", description="Cache administration for japan-stock-analysis Skill")
    sub = parser.add_subparsers(dest="command", required=True)

    p_info = sub.add_parser("info", help="Show cache state as JSON")
    p_info.add_argument("--sec-code", help="Show per-sec-code derived/prices/mappings detail")
    p_info.set_defaults(func=_cmd_info)

    p_clear = sub.add_parser("clear", help="Clear caches (P6)")
    p_clear.set_defaults(func=_cmd_clear)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
