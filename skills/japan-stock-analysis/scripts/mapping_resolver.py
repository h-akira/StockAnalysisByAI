"""XBRL element mapping resolver (whitelist + LLM escalation).

Phase P8 implementation. The flow per plan.md §4.4 and SKILL.md §6:

  1. xbrl_extract returns ``ExtractResult.unresolved`` for items the
     whitelist could not pin down.
  2. pipeline.py calls ``build_escalation_payload`` to emit a JSON file
     listing, for each unresolved item, every plausible candidate element
     present in the XBRL (with sample values and contexts) plus a pointer
     to the knowledge document.
  3. The pipeline returns ``status: "needs_mapping"`` with that payload
     path; SKILL.md §6 walks Claude through reading the knowledge,
     selecting one element per item, and running ``mapping_resolver save``.
  4. On the next ``pipeline analyze``, ``load_mapping`` finds the cached
     JSON, ``xbrl_extract`` consumes ``mappings`` via ``extra_mappings``,
     and the analyze succeeds without LLM involvement.

Cache shape (cache/mappings/{sec_code}.json):

    {
      "sec_code": "8306",
      "company_name": "...",
      "accounting_standard": "JGAAP",
      "industry_category": "bank",
      "resolved_at": "2026-05-23T...",
      "resolved_by": "llm",
      "mappings": {
        "NetSales": {"element": "jppfs_cor:OrdinaryIncome",
                     "context": "CurrentYearDuration",
                     "rationale": "..."}
      },
      "unresolved": []
    }
"""

from __future__ import annotations

# Allow running both as `python scripts/mapping_resolver.py` (Skill convention)
# and as `python -m scripts.mapping_resolver` (pytest). When run directly,
# __package__ is empty — add Skill root to sys.path.
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
from scripts.xbrl_extract import ITEM_KEYS, inventory_candidates


def mapping_cache_path(sec_code: str) -> Path:
    return paths.MAPPINGS_DIR / f"{sec_code}.json"


def load_mapping(sec_code: str) -> dict | None:
    """Return the cached mapping dict or None if absent / corrupt."""
    p = mapping_cache_path(sec_code)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def save_mapping(sec_code: str, payload: dict, *, resolved_by: str = "llm") -> Path:
    """Persist a mapping to cache/mappings/{sec_code}.json with audit fields."""
    paths.ensure_cache_dirs()
    enriched = {
        **payload,
        "sec_code": sec_code,
        "resolved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "resolved_by": resolved_by,
    }
    # Ensure structural keys exist even if caller omitted them.
    enriched.setdefault("mappings", {})
    enriched.setdefault("unresolved", [])
    out = mapping_cache_path(sec_code)
    out.write_text(json.dumps(enriched, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def build_escalation_payload(
    sec_code: str,
    zip_path: Path,
    edinet_code: str,
    unresolved: list[str],
    *,
    out_dir: Path | None = None,
) -> Path:
    """Write an escalation payload JSON Claude can read.

    Contents:
      - sec_code, edinet_code, doc_id (from caller context)
      - unresolved_items: the list to assign
      - candidates: every plausible (element, context, sample_value) tuple
        present in the XBRL — Claude picks one per unresolved item
      - knowledge_path: where to find the §4.4 ナレッジ
      - schema_hint: pointer to docs/xbrl_variation_knowledge.md §7
    """
    candidates = inventory_candidates(zip_path, edinet_code)
    payload = {
        "sec_code": sec_code,
        "edinet_code": edinet_code,
        "unresolved_items": [k for k in unresolved if k in ITEM_KEYS],
        "candidates": candidates,
        "knowledge_path": str(paths.SKILL_ROOT / "docs" / "xbrl_variation_knowledge.md"),
        "schema_hint": "See docs/xbrl_variation_knowledge.md §7 for the save format.",
    }
    target_dir = out_dir or paths.output_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    out_path = target_dir / f"mapping_escalation_{sec_code}.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _emit(payload: dict) -> int:
    json.dump(payload, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0 if payload.get("status") == "success" else 1


def _cmd_save(args: argparse.Namespace) -> int:
    src = Path(args.mapping_json)
    if not src.exists():
        return _emit({"status": "error", "reason": f"mapping JSON not found: {src}"})
    try:
        body = json.loads(src.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return _emit({"status": "error", "reason": f"mapping JSON invalid: {e}"})

    # Validate every mapping has the three required fields.
    mappings = body.get("mappings") or {}
    bad = [
        k for k, v in mappings.items()
        if not isinstance(v, dict)
        or "element" not in v or "context" not in v or "rationale" not in v
    ]
    if bad:
        return _emit({
            "status": "error",
            "reason": f"mappings missing element/context/rationale for: {bad}",
        })

    out = save_mapping(args.sec_code, body, resolved_by=args.resolved_by)
    return _emit({
        "status": "success",
        "command": "save",
        "sec_code": args.sec_code,
        "cache_path": str(out),
        "mapped_items": list(mappings.keys()),
        "unresolved": body.get("unresolved", []),
    })


def _cmd_show(args: argparse.Namespace) -> int:
    body = load_mapping(args.sec_code)
    if body is None:
        return _emit({"status": "error", "reason": f"no mapping cached for sec_code {args.sec_code}"})
    json.dump(body, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mapping_resolver",
        description="XBRL element mapping cache (see SKILL.md §6)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_save = sub.add_parser("save", help="Persist a Claude-built mapping JSON to cache")
    p_save.add_argument("--sec-code", required=True)
    p_save.add_argument("--mapping-json", required=True,
                        help="Path to the JSON file (Claude wrote per docs/xbrl_variation_knowledge.md §7)")
    p_save.add_argument("--resolved-by", default="llm",
                        help="Audit tag for who/what produced this mapping (default: llm)")
    p_save.set_defaults(func=_cmd_save)

    p_show = sub.add_parser("show", help="Print the cached mapping for a sec_code")
    p_show.add_argument("--sec-code", required=True)
    p_show.set_defaults(func=_cmd_show)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
