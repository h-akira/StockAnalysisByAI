"""End-to-end orchestrator: analyze one or more securities codes.

Subcommand:
    python3 ${CLAUDE_SKILL_DIR}/scripts/pipeline.py analyze --sec-code 7203
    python3 ${CLAUDE_SKILL_DIR}/scripts/pipeline.py analyze --sec-code 7203 6758
    python3 ${CLAUDE_SKILL_DIR}/scripts/pipeline.py analyze --sec-code 7203 --no-yfinance
    python3 ${CLAUDE_SKILL_DIR}/scripts/pipeline.py analyze --sec-code 7203 --limit 1
    python3 ${CLAUDE_SKILL_DIR}/scripts/pipeline.py analyze --sec-code 7203 --output-dir /tmp/reports

Stdout contract: a single JSON object with a top-level ``status`` field.
Possible statuses (see plan.md §4.3):
    success           - everything ran; outputs and any warnings included
    needs_bootstrap   - cache/documents/ has no annual reports for this code
    config_error      - secret.json missing or invalid
    error             - any other failure
"""

from __future__ import annotations

# Make this script runnable both as `python scripts/pipeline.py` (direct,
# the Skill convention with ${CLAUDE_SKILL_DIR}) and as
# `python -m scripts.pipeline` (module form, used by pytest collection).
# When run directly, __package__ is empty — add Skill root to sys.path so
# that `from scripts...` absolute imports resolve.
if __package__ in (None, ""):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse
import json
import sys
from pathlib import Path

from scripts import paths
from scripts.company_map import CompanyMapMissingError, lookup as lookup_company
from scripts.config import ConfigError, load_edinet_config
from scripts.doc_list import (
    DocumentsNotBootstrappedError,
    find_documents_for_sec_code,
    find_missing_windows,
)
from scripts.cache_admin import clear_sec_code
from scripts.html_report import render_report
from scripts.json_export import write_data_json
from scripts.metrics import build_metrics, save_metrics
from scripts.split_adjust import resolve_split_adjust
from scripts.timeseries import build_timeseries, save_timeseries


def _emit(payload: dict) -> int:
    json.dump(payload, sys.stdout, indent=2, ensure_ascii=False, default=str)
    sys.stdout.write("\n")
    return 0 if payload.get("status") == "success" else 1


def _analyze_one(sec_code: str, args: argparse.Namespace, api_key: str) -> dict:
    """Run timeseries + metrics for one sec_code. Returns a per-code result."""
    docs = find_documents_for_sec_code(sec_code)
    missing = find_missing_windows(sec_code, years=args.years)
    if not docs or missing:
        return {
            "sec_code": sec_code,
            "status": "needs_bootstrap",
            "reason": (
                f"No annual reports found for {sec_code} in cache/documents/."
                if not docs else
                f"Bootstrap is incomplete for {sec_code}: {len(missing)} weekday(s) "
                f"in the expected submission window are missing from cache."
            ),
            "missing_weekday_count": len(missing),
            "missing_window_sample": missing[:5] + (["..."] if len(missing) > 5 else []),
            "suggested_command": (
                "python3 ${CLAUDE_SKILL_DIR}/scripts/bootstrap.py fetch-documents "
                f"--years {args.years}"
            ),
        }

    ts_df = build_timeseries(sec_code, api_key, limit=args.limit)
    ts_path = save_timeseries(sec_code, ts_df)

    # Resolve restated-EPS mapping from the latest annual report. Cache key
    # is the latest doc_id, so this is a one-time XBRL pull per fiscal-year
    # change. See plan §3.6 and pre-research Step 7.
    latest_doc = docs[-1]
    split_adjust = resolve_split_adjust(
        sec_code,
        api_key,
        latest_doc_id=latest_doc.doc_id,
        latest_edinet_code=latest_doc.edinet_code,
        latest_period_end=latest_doc.period_end,
    )

    metrics_df, warnings = build_metrics(
        sec_code,
        use_yfinance=not args.no_yfinance,
        split_adjust=split_adjust,
    )
    metrics_path = save_metrics(sec_code, metrics_df)

    return {
        "sec_code": sec_code,
        "fiscal_years": [str(d) for d in ts_df.index],
        "timeseries_csv": str(ts_path),
        "metrics_csv": str(metrics_path),
        "split_adjust_source_doc_id": split_adjust.source_doc_id,
        "warnings": warnings,
        "_docs": docs,                 # internal use: surfaced into report footer
        "_split_adjust": split_adjust,  # internal use: passed to json_export
    }


def cmd_analyze(args: argparse.Namespace) -> int:
    if args.output_dir:
        # Override the CWD-based output_dir for this run. We monkeypatch
        # paths.output_dir so html_report inherits the override transparently.
        forced = Path(args.output_dir).resolve()
        forced.mkdir(parents=True, exist_ok=True)
        paths.output_dir = lambda: forced  # type: ignore[assignment]

    try:
        cfg = load_edinet_config()
    except ConfigError as e:
        return _emit({"status": "config_error", "reason": str(e)})

    # --force-refresh wipes the cheap per-sec-code caches (derived/prices/
    # split-adjust) so the pipeline re-derives them from scratch. mappings is
    # NOT included on purpose — those are AI-judgement results that the user
    # opts into clearing via `cache_admin clear --mappings`.
    if args.force_refresh:
        for sc in args.sec_code:
            clear_sec_code(sc, types=["derived", "prices", "split-adjust"])

    # Validate every sec_code up front; fail fast with a clear message.
    for sc in args.sec_code:
        if lookup_company(sc) is None:
            return _emit({
                "status": "error",
                "reason": f"sec_code {sc!r} not found in company_map.csv. "
                          "Run: python3 ${CLAUDE_SKILL_DIR}/scripts/bootstrap.py refresh-company-map",
            })

    per_code: list[dict] = []
    all_warnings: list[str] = []
    needs_bootstrap = False
    try:
        for sc in args.sec_code:
            r = _analyze_one(sc, args, cfg.api_key)
            per_code.append(r)
            if r.get("status") == "needs_bootstrap":
                needs_bootstrap = True
            for w in r.get("warnings", []) or []:
                all_warnings.append(f"[{sc}] {w}")
    except CompanyMapMissingError as e:
        return _emit({"status": "needs_bootstrap", "reason": str(e)})
    except DocumentsNotBootstrappedError as e:
        return _emit({"status": "needs_bootstrap", "reason": str(e)})

    if needs_bootstrap:
        return _emit({
            "status": "needs_bootstrap",
            "per_code": per_code,
            "suggested_command": "python3 ${CLAUDE_SKILL_DIR}/scripts/bootstrap.py fetch-documents --years 10",
        })

    # Per-code data_{sec_code}.json (CWD output; schema in docs/json_schema.md).
    data_json_paths: dict[str, str] = {}
    source_docs: dict[str, list[str]] = {}
    split_adjust_doc_ids: dict[str, str] = {}
    for r in per_code:
        sc = r["sec_code"]
        json_path = write_data_json(
            sc,
            split_adjust=r.get("_split_adjust"),
            warnings=[w for w in all_warnings if w.startswith(f"[{sc}]")],
        )
        data_json_paths[sc] = str(json_path)
        source_docs[sc] = [d.doc_id for d in r.get("_docs", [])]
        if r.get("split_adjust_source_doc_id"):
            split_adjust_doc_ids[sc] = r["split_adjust_source_doc_id"]

    out_html = render_report(
        args.sec_code,
        warnings=all_warnings,
        source_docs=source_docs,
        split_adjust_doc_ids=split_adjust_doc_ids,
    )

    # Strip internal-only keys before emitting JSON to stdout.
    public_per_code = [
        {k: v for k, v in r.items() if not k.startswith("_")}
        for r in per_code
    ]

    return _emit({
        "status": "success",
        "sec_codes": args.sec_code,
        "outputs": {
            "html": str(out_html),
            "data_json": data_json_paths,
            "per_code": public_per_code,
        },
        "warnings": all_warnings,
        "cache_dir": str(paths.CACHE_DIR),
    })


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pipeline", description="End-to-end analysis pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    p_analyze = sub.add_parser("analyze", help="Analyze 1+ securities codes")
    p_analyze.add_argument("--sec-code", required=True, nargs="+",
                           help="one or more 4-digit codes (e.g. 7203 or 7203 6758)")
    p_analyze.add_argument("--no-yfinance", action="store_true",
                           help="skip yfinance; valuation metrics will be NaN")
    p_analyze.add_argument("--limit", type=int, default=None,
                           help="process only the latest N annual reports per code (debug)")
    p_analyze.add_argument("--output-dir", type=str, default=None,
                           help="override the CWD output dir for the HTML report")
    p_analyze.add_argument("--years", type=int, default=10,
                           help="how many years of submission windows to check for completeness")
    p_analyze.add_argument("--force-refresh", action="store_true",
                           help="discard per-sec-code derived/prices/split-adjust before analyzing")
    p_analyze.set_defaults(func=cmd_analyze)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
