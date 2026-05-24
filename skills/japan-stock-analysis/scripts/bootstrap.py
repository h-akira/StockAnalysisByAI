"""Bootstrap: heavy initial fetch of company_map and documents_index.

Strategy (see init_plan.md §3.5):
    documents.json is a per-date API with no company/docType filter, so the
    cache primary key is the date itself. We pull every weekday in the past
    N years into cache/documents/{YYYY-MM-DD}.json. Existing files are
    skipped so subsequent runs only fill gaps.

Subcommands:
    fetch-documents --years N [--chunk K/M] [--sleep S]
        Pull documents.json for every weekday in the past N years.
        --chunk K/M runs only the K-th of M equal-sized slices (0-indexed)
        so that a long sweep (e.g. 2,500-request 10-year scan ~40 min at
        1s sleep) can be spread out, paused, or resumed. EDINET API has
        no documented hard rate limit; 1-second spacing has been
        pre-research-validated as stable. 429/5xx errors are retried
        internally with exponential backoff.
    refresh-company-map
        Re-download the EDINET company-master ZIP and rebuild company_map.csv.
    init [--years N]
        End-to-end first-time setup: refresh-company-map then fetch-documents.

Inherits from pre-research:
    - fetch_docs() / 404-as-empty behavior: step2_doc_list.py
    - company-map ZIP layout (cp932, 2-row preamble): step1_company_map.py
"""

from __future__ import annotations

# Allow running both as `python scripts/bootstrap.py` (direct, the Skill
# convention with ${CLAUDE_SKILL_DIR}) and as `python -m scripts.bootstrap`
# (module form, used by pytest). When run directly, __package__ is empty —
# add Skill root to sys.path so absolute `from scripts...` imports resolve.
if __package__ in (None, ""):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse
import csv
import io
import json
import sys
import time
import zipfile
from datetime import date, timedelta
from pathlib import Path

import requests

from scripts import paths
from scripts.config import ConfigError, load_edinet_config

BASE_URL = "https://disclosure.edinet-fsa.go.jp/api/v2/documents.json"
EDINET_CODE_ZIP = "https://disclosure2dl.edinet-fsa.go.jp/searchdocument/codelist/Edinetcode.zip"

# Politeness interval. 1.0 s has been validated in pre-research; raise if 429.
DEFAULT_SLEEP_SECONDS = 1.0

# company_map.csv schema (kept in sync with pre-research/edinet/step1_company_map.py).
COMPANY_MAP_FIELDS = ["sec_code", "edinet_code", "filer_name", "listing", "fiscal_month", "industry"]


# ---------------------------------------------------------------------------
# Date enumeration
# ---------------------------------------------------------------------------

def build_weekdays(years: int, today: date | None = None) -> list[date]:
    """Return every weekday (Mon-Fri) in the past ``years`` years up to today.

    Anchored on ``today`` (or ``date.today()`` if None) and walking backward
    ``years`` full years. Weekends are excluded because EDINET returns 404
    for them — we'd waste API calls and clutter the cache directory.
    """
    if years <= 0:
        raise ValueError("years must be positive")
    anchor = today or date.today()
    start = anchor.replace(year=anchor.year - years) + timedelta(days=1)
    dates: list[date] = []
    d = start
    while d <= anchor:
        if d.weekday() < 5:
            dates.append(d)
        d += timedelta(days=1)
    return dates


def chunk_dates(dates: list[date], k: int, m: int) -> list[date]:
    """Return the k-th of m roughly-equal slices of ``dates`` (0-indexed)."""
    if m <= 0 or k < 0 or k >= m:
        raise ValueError(f"invalid chunk spec: k={k}, m={m}")
    n = len(dates)
    start = (n * k) // m
    end = (n * (k + 1)) // m
    return dates[start:end]


def parse_chunk_spec(spec: str) -> tuple[int, int]:
    """Parse 'K/M' into (k, m). Validates k < m and both non-negative."""
    if "/" not in spec:
        raise argparse.ArgumentTypeError(f"--chunk must be K/M, got {spec!r}")
    k_s, m_s = spec.split("/", 1)
    try:
        k, m = int(k_s), int(m_s)
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"--chunk values must be integers: {spec!r}") from e
    if m <= 0 or k < 0 or k >= m:
        raise argparse.ArgumentTypeError(f"--chunk K/M requires 0 <= K < M, got {spec!r}")
    return k, m


# ---------------------------------------------------------------------------
# EDINET API
# ---------------------------------------------------------------------------

def fetch_documents_json(
    api_key: str,
    target_date: date,
    *,
    timeout: float = 30.0,
    max_retries: int = 3,
    backoff_seconds: float = 5.0,
) -> dict | None:
    """Fetch documents.json for one date. Returns None on 404 (no filings).

    Retries with exponential backoff on HTTP 429 (rate limit) and 5xx errors.
    Other errors propagate as requests.RequestException to the caller, which
    counts them via --max-errors and may abort the whole run.
    """
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            resp = requests.get(
                BASE_URL,
                params={"date": target_date.isoformat(), "type": 2, "Subscription-Key": api_key},
                timeout=timeout,
            )
        except requests.RequestException as e:
            # Network-level failure (DNS/connection/timeout); retry transiently.
            last_exc = e
            if attempt + 1 < max_retries:
                time.sleep(backoff_seconds * (2 ** attempt))
                continue
            raise

        if resp.status_code == 404:
            return None
        if resp.status_code == 429 or 500 <= resp.status_code < 600:
            if attempt + 1 < max_retries:
                time.sleep(backoff_seconds * (2 ** attempt))
                continue
            resp.raise_for_status()
        resp.raise_for_status()
        return resp.json()
    # Loop exhausted without return — only reachable through network exception path.
    raise last_exc if last_exc else RuntimeError("fetch_documents_json: retry loop exhausted")


def documents_cache_path(target_date: date) -> Path:
    return paths.DOCUMENTS_DIR / f"{target_date.isoformat()}.json"


def fetch_and_cache(api_key: str, target_date: date, *, force: bool = False) -> str:
    """Fetch one date and write the JSON to cache. Returns one of:
    'skipped' (already cached), 'empty' (404), 'fetched'.
    """
    out_path = documents_cache_path(target_date)
    if out_path.exists() and not force:
        return "skipped"
    payload = fetch_documents_json(api_key, target_date)
    if payload is None:
        # Persist an explicit empty marker so subsequent runs don't retry.
        # Empty days still happen on holidays even within Mon-Fri.
        payload = {"metadata": {"status": "404", "date": target_date.isoformat()}, "results": []}
    out_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return "fetched"


# ---------------------------------------------------------------------------
# company_map.csv
# ---------------------------------------------------------------------------

def download_company_master() -> list[dict]:
    """Download EDINET company-master ZIP and parse the inner CSV (cp932)."""
    resp = requests.get(EDINET_CODE_ZIP, timeout=60)
    resp.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        csv_name = next(n for n in zf.namelist() if n.endswith(".csv"))
        raw = zf.read(csv_name).decode("cp932")
    lines = raw.splitlines()
    # The CSV has a one-line preamble before the real header (see pre-research
    # step1_company_map.py for full notes on the format).
    reader = csv.DictReader(lines[1:])
    return list(reader)


def build_company_map(rows: list[dict]) -> list[dict]:
    """Filter to entries that have both a securities code and an EDINET code."""
    out: list[dict] = []
    for row in rows:
        sec = row.get("証券コード", "").strip().strip('"')
        edinet = row.get("ＥＤＩＮＥＴコード", "").strip().strip('"')
        if not sec or not edinet:
            continue
        out.append({
            "sec_code": sec,
            "edinet_code": edinet,
            "filer_name": row.get("提出者名", "").strip().strip('"'),
            "listing": row.get("上場区分", "").strip().strip('"'),
            "fiscal_month": row.get("決算日", "").strip().strip('"'),
            "industry": row.get("提出者業種", "").strip().strip('"'),
        })
    out.sort(key=lambda r: r["sec_code"])
    return out


def save_company_map(rows: list[dict]) -> None:
    paths.ensure_cache_dirs()
    with paths.COMPANY_MAP.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COMPANY_MAP_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def _emit(payload: dict) -> None:
    json.dump(payload, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


def cmd_refresh_company_map(_args: argparse.Namespace) -> int:
    # company-master ZIP lives on disclosure2dl.* and does not require an API key.
    try:
        rows = download_company_master()
        mapping = build_company_map(rows)
        save_company_map(mapping)
    except requests.RequestException as e:
        _emit({"status": "error", "command": "refresh-company-map", "reason": str(e)})
        return 1
    _emit({
        "status": "success",
        "command": "refresh-company-map",
        "raw_rows": len(rows),
        "listed_entries": len(mapping),
        "output": str(paths.COMPANY_MAP),
    })
    return 0


def cmd_fetch_documents(args: argparse.Namespace) -> int:
    try:
        cfg = load_edinet_config()
    except ConfigError as e:
        _emit({"status": "error", "command": "fetch-documents", "reason": str(e)})
        return 1

    paths.ensure_cache_dirs()
    all_dates = build_weekdays(args.years)
    if args.chunk:
        k, m = parse_chunk_spec(args.chunk)
        target_dates = chunk_dates(all_dates, k, m)
        chunk_info = {"chunk": f"{k}/{m}", "total_weekdays": len(all_dates), "this_chunk": len(target_dates)}
    else:
        target_dates = all_dates
        chunk_info = {"chunk": None, "total_weekdays": len(all_dates), "this_chunk": len(target_dates)}

    counters = {"fetched": 0, "skipped": 0, "errors": 0}
    errors: list[dict] = []

    for i, d in enumerate(target_dates, start=1):
        result: str | None = None
        try:
            result = fetch_and_cache(cfg.api_key, d, force=args.force)
            counters[result] += 1
        except requests.RequestException as e:
            counters["errors"] += 1
            errors.append({"date": d.isoformat(), "reason": str(e)})
            if len(errors) >= args.max_errors:
                _emit({
                    "status": "aborted",
                    "command": "fetch-documents",
                    "reason": f"reached --max-errors={args.max_errors}",
                    "counters": counters,
                    "errors": errors,
                    **chunk_info,
                })
                return 1
        # Politeness: only sleep when we actually called the API (skipped = cache hit).
        if result != "skipped":
            time.sleep(args.sleep)
        if i % 20 == 0:
            sys.stderr.write(
                f"  [{i}/{len(target_dates)}] fetched={counters['fetched']} "
                f"skipped={counters['skipped']} errors={counters['errors']}\n"
            )

    _emit({
        "status": "success",
        "command": "fetch-documents",
        "counters": counters,
        "errors": errors,
        **chunk_info,
    })
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    rc = cmd_refresh_company_map(args)
    if rc != 0:
        return rc
    return cmd_fetch_documents(args)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bootstrap", description="Initial-fetch bootstrap for japan-stock-analysis Skill")
    sub = parser.add_subparsers(dest="command", required=True)

    p_fetch = sub.add_parser("fetch-documents", help="Pull documents.json for past N years (weekdays only)")
    p_fetch.add_argument("--years", type=int, default=10, help="years of history to cover (default: 10)")
    p_fetch.add_argument("--chunk", type=str, default=None, metavar="K/M",
                         help="run only the K-th of M slices (e.g. 0/25)")
    p_fetch.add_argument("--sleep", type=float, default=DEFAULT_SLEEP_SECONDS,
                         help="seconds between API calls (default: %(default)s)")
    p_fetch.add_argument("--force", action="store_true", help="re-fetch dates already in cache")
    p_fetch.add_argument("--max-errors", type=int, default=10,
                         help="abort after this many request errors (default: 10)")
    p_fetch.set_defaults(func=cmd_fetch_documents)

    p_refresh = sub.add_parser("refresh-company-map", help="Re-download EDINET company master and rebuild company_map.csv")
    p_refresh.set_defaults(func=cmd_refresh_company_map)

    p_init = sub.add_parser("init", help="End-to-end first-time setup")
    p_init.add_argument("--years", type=int, default=10)
    p_init.add_argument("--chunk", type=str, default=None, metavar="K/M")
    p_init.add_argument("--sleep", type=float, default=DEFAULT_SLEEP_SECONDS)
    p_init.add_argument("--force", action="store_true")
    p_init.add_argument("--max-errors", type=int, default=10)
    p_init.set_defaults(func=cmd_init)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
