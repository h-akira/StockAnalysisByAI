"""Cache administration CLI.

Usage:
    python3 ${CLAUDE_SKILL_DIR}/scripts/cache_admin.py info
    python3 ${CLAUDE_SKILL_DIR}/scripts/cache_admin.py info --sec-code 7203

    # Cheap caches (regenerable without API):
    python3 ${CLAUDE_SKILL_DIR}/scripts/cache_admin.py clear --derived
    python3 ${CLAUDE_SKILL_DIR}/scripts/cache_admin.py clear --prices
    python3 ${CLAUDE_SKILL_DIR}/scripts/cache_admin.py clear --mappings
    python3 ${CLAUDE_SKILL_DIR}/scripts/cache_admin.py clear --split-adjust

    # Expensive caches (require API re-fetch; --confirm gated):
    python3 ${CLAUDE_SKILL_DIR}/scripts/cache_admin.py clear --documents --confirm
    python3 ${CLAUDE_SKILL_DIR}/scripts/cache_admin.py clear --xbrl --confirm

    # Per-sec-code (derived/prices/mappings/split-adjust only; xbrl is doc-keyed):
    python3 ${CLAUDE_SKILL_DIR}/scripts/cache_admin.py clear --sec-code 7203
    python3 ${CLAUDE_SKILL_DIR}/scripts/cache_admin.py clear --sec-code 7203 --types derived,prices

    # Nuclear (--confirm gated):
    python3 ${CLAUDE_SKILL_DIR}/scripts/cache_admin.py clear --all --confirm

See plan.md §4.3 for the rationale behind --confirm gating.
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


# ---------------------------------------------------------------------------
# Cache type registry
# ---------------------------------------------------------------------------

# Cache types that are cheap to regenerate (no EDINET API calls needed).
# Picked up by `clear --derived/--prices/--mappings/--split-adjust` directly
# and by `clear --sec-code` per-company.
CHEAP_TYPES: dict[str, tuple[Path, str]] = {
    "derived": (paths.DERIVED_DIR, "*.csv"),
    "prices": (paths.PRICES_DIR, "*.csv"),
    "mappings": (paths.MAPPINGS_DIR, "*.json"),
    "split-adjust": (paths.SPLIT_ADJUST_DIR, "*.json"),
}

# Expensive caches: clearing forces fresh API calls. Require --confirm.
EXPENSIVE_TYPES: dict[str, tuple[Path, str]] = {
    "documents": (paths.DOCUMENTS_DIR, "*.json"),
    "xbrl": (paths.XBRL_DIR, "*.zip"),
}


# ---------------------------------------------------------------------------
# Info helpers (unchanged from P1)
# ---------------------------------------------------------------------------

def _dir_summary(path: Path, pattern: str = "*") -> dict:
    if not path.exists():
        return {"exists": False, "count": 0, "size_bytes": 0, "latest_mtime": None}
    files = [p for p in path.glob(pattern) if p.is_file()]
    total = sum(p.stat().st_size for p in files)
    latest = max((p.stat().st_mtime for p in files), default=None)
    latest_iso = (
        datetime.fromtimestamp(latest, tz=timezone.utc).isoformat() if latest else None
    )
    return {"exists": True, "count": len(files), "size_bytes": total, "latest_mtime": latest_iso}


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


# ---------------------------------------------------------------------------
# Clear primitives
# ---------------------------------------------------------------------------

def _clear_dir(directory: Path, pattern: str) -> list[str]:
    """Delete every file matching ``pattern`` under ``directory``. Returns paths removed."""
    removed: list[str] = []
    if not directory.exists():
        return removed
    for p in directory.glob(pattern):
        if p.is_file():
            p.unlink()
            removed.append(str(p))
    return removed


def clear_type(type_name: str) -> list[str]:
    """Clear an entire cache type (e.g. 'derived', 'documents'). Returns removed paths."""
    if type_name in CHEAP_TYPES:
        d, pat = CHEAP_TYPES[type_name]
    elif type_name in EXPENSIVE_TYPES:
        d, pat = EXPENSIVE_TYPES[type_name]
    else:
        raise ValueError(f"unknown cache type {type_name!r}")
    return _clear_dir(d, pat)


# Per-sec-code file names per type. xbrl is intentionally absent because it's
# doc-id keyed, not sec-code keyed — sharing across companies is impossible
# anyway but the lookup channel just doesn't exist (plan.md §4.3 note).
_PER_SEC_FILES = {
    "derived": lambda sc: [
        paths.DERIVED_DIR / f"timeseries_{sc}.csv",
        paths.DERIVED_DIR / f"metrics_{sc}.csv",
    ],
    "prices": lambda sc: [paths.PRICES_DIR / f"{sc}.csv"],
    "mappings": lambda sc: [paths.MAPPINGS_DIR / f"{sc}.json"],
    "split-adjust": lambda sc: [paths.SPLIT_ADJUST_DIR / f"{sc}.json"],
}

PER_SEC_TYPES: set[str] = set(_PER_SEC_FILES.keys())


def clear_sec_code(sec_code: str, types: list[str] | None = None) -> list[str]:
    """Clear per-sec-code files for the given types (default: all PER_SEC_TYPES)."""
    selected = types or sorted(PER_SEC_TYPES)
    removed: list[str] = []
    for t in selected:
        if t not in PER_SEC_TYPES:
            raise ValueError(f"unknown per-sec-code type {t!r} (valid: {sorted(PER_SEC_TYPES)})")
        for p in _PER_SEC_FILES[t](sec_code):
            if p.exists():
                p.unlink()
                removed.append(str(p))
    return removed


def clear_all() -> list[str]:
    """Wipe every known cache type (CHEAP + EXPENSIVE + company_map)."""
    removed: list[str] = []
    for t in (*CHEAP_TYPES, *EXPENSIVE_TYPES):
        removed.extend(clear_type(t))
    if paths.COMPANY_MAP.exists():
        paths.COMPANY_MAP.unlink()
        removed.append(str(paths.COMPANY_MAP))
    return removed


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------

def _emit(payload: dict) -> int:
    json.dump(payload, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0 if payload.get("status") == "success" else 1


def _cmd_info(args: argparse.Namespace) -> int:
    info = collect_info(sec_code=args.sec_code)
    json.dump(info, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


def _selected_types(args: argparse.Namespace) -> list[str]:
    """Read the per-type flags off args and return the selected type names."""
    types: list[str] = []
    if args.derived:
        types.append("derived")
    if args.prices:
        types.append("prices")
    if args.mappings:
        types.append("mappings")
    if args.split_adjust:
        types.append("split-adjust")
    if args.documents:
        types.append("documents")
    if args.xbrl:
        types.append("xbrl")
    return types


def _cmd_clear(args: argparse.Namespace) -> int:
    # Mutually-exclusive top-level modes: --all, --sec-code, or one+ --<type>.
    mode_count = sum([bool(args.all), bool(args.sec_code), bool(_selected_types(args))])
    if mode_count == 0:
        return _emit({
            "status": "error",
            "reason": "specify one of: --all / --sec-code <code> / --derived|--prices|--mappings|--split-adjust|--documents|--xbrl",
        })
    if mode_count > 1:
        return _emit({
            "status": "error",
            "reason": "modes are mutually exclusive: --all, --sec-code, and per-type flags cannot be combined",
        })

    # --all
    if args.all:
        if not args.confirm:
            return _emit({
                "status": "error",
                "reason": "--all wipes documents and xbrl caches (expensive API re-fetch). Re-run with --confirm.",
            })
        removed = clear_all()
        return _emit({
            "status": "success", "command": "clear", "mode": "all",
            "removed_count": len(removed), "removed": removed,
        })

    # --sec-code
    if args.sec_code:
        types_arg: list[str] | None = None
        if args.types:
            types_arg = [t.strip() for t in args.types.split(",") if t.strip()]
            unknown = [t for t in types_arg if t not in PER_SEC_TYPES]
            if unknown:
                return _emit({
                    "status": "error",
                    "reason": f"unknown --types value(s): {unknown} (valid: {sorted(PER_SEC_TYPES)})",
                })
        try:
            removed = clear_sec_code(args.sec_code, types_arg)
        except ValueError as e:
            return _emit({"status": "error", "reason": str(e)})
        return _emit({
            "status": "success", "command": "clear", "mode": "sec-code",
            "sec_code": args.sec_code,
            "types": types_arg or sorted(PER_SEC_TYPES),
            "removed_count": len(removed), "removed": removed,
        })

    # Per-type
    selected = _selected_types(args)
    expensive = [t for t in selected if t in EXPENSIVE_TYPES]
    if expensive and not args.confirm:
        return _emit({
            "status": "error",
            "reason": f"clearing {expensive} forces API re-fetch. Re-run with --confirm.",
        })
    removed_all: list[str] = []
    for t in selected:
        removed_all.extend(clear_type(t))
    return _emit({
        "status": "success", "command": "clear", "mode": "types",
        "types": selected,
        "removed_count": len(removed_all), "removed": removed_all,
    })


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cache_admin", description="Cache administration for japan-stock-analysis Skill")
    sub = parser.add_subparsers(dest="command", required=True)

    p_info = sub.add_parser("info", help="Show cache state as JSON")
    p_info.add_argument("--sec-code", help="Show per-sec-code derived/prices/mappings/split-adjust detail")
    p_info.set_defaults(func=_cmd_info)

    p_clear = sub.add_parser("clear", help="Clear caches (see module docstring for the flag matrix)")
    # Cheap types
    p_clear.add_argument("--derived", action="store_true", help="clear timeseries/metrics CSVs")
    p_clear.add_argument("--prices", action="store_true", help="clear yfinance daily-price CSVs")
    p_clear.add_argument("--mappings", action="store_true", help="clear XBRL element mapping JSON (AI judgement)")
    p_clear.add_argument("--split-adjust", action="store_true", help="clear restated-EPS JSON")
    # Expensive types (need --confirm)
    p_clear.add_argument("--documents", action="store_true", help="clear documents_{date}.json (requires --confirm; forces API re-fetch)")
    p_clear.add_argument("--xbrl", action="store_true", help="clear XBRL zips (requires --confirm; forces API re-fetch)")
    # Per-sec-code mode
    p_clear.add_argument("--sec-code", help="clear per-sec-code files (derived/prices/mappings/split-adjust)")
    p_clear.add_argument("--types", help="comma-separated subset of types under --sec-code (e.g. derived,prices)")
    # Nuclear
    p_clear.add_argument("--all", action="store_true", help="wipe every cache including company_map (requires --confirm)")
    # Safety
    p_clear.add_argument("--confirm", action="store_true", help="required for --all, --documents, --xbrl")
    p_clear.set_defaults(func=_cmd_clear)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
