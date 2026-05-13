"""
Step 1: Build a mapping table from securities code (4-digit) to EDINET code.

Source: EDINET公式 EDINETコード一覧 ZIP (no API key required)
  https://disclosure2dl.edinet-fsa.go.jp/searchdocument/codelist/Edinetcode.zip

The ZIP contains EdinetcodeDlInfo.csv (cp932, ~11,000 rows) with columns:
  EDINETコード, 提出者種別, 上場区分, 連結の有無, 資本金, 決算日,
  提出者名, 提出者名（英字）, 提出者名（ヨミ）, 所在地, 提出者業種,
  証券コード, 提出者法人番号

Usage:
  python step1_company_map.py               # download & save CSV
  python step1_company_map.py --sec-code 7203  # lookup single stock
"""

import argparse
import csv
import io
import zipfile
from pathlib import Path

import requests

EDINET_CODE_ZIP = "https://disclosure2dl.edinet-fsa.go.jp/searchdocument/codelist/Edinetcode.zip"
OUTPUT_CSV = Path(__file__).parent / "data" / "company_map.csv"

FIELDNAMES = ["sec_code", "edinet_code", "filer_name", "listing", "fiscal_month", "industry"]


def download_edinet_code_list() -> list[dict]:
    """Download Edinetcode.zip and parse EdinetcodeDlInfo.csv."""
    print(f"Downloading {EDINET_CODE_ZIP} ...")
    resp = requests.get(EDINET_CODE_ZIP, timeout=60)
    resp.raise_for_status()
    print(f"  {len(resp.content):,} bytes")

    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        csv_name = next(n for n in zf.namelist() if n.endswith(".csv"))
        raw = zf.read(csv_name).decode("cp932")

    lines = raw.splitlines()
    # The CSV has a non-standard 2-row preamble:
    #   Row 0: "ダウンロード実行日, 2026年XX月XX日現在, 件数, XXXXX件"  <- discard
    #   Row 1: actual column headers (ＥＤＩＮＥＴコード, 証券コード, ...)
    #   Row 2+: data
    reader = csv.DictReader(lines[1:])  # use row 1 as header
    return list(reader)


def build_map(rows: list[dict]) -> dict[str, dict]:
    mapping: dict[str, dict] = {}
    for row in rows:
        # The CSV wraps values in double-quotes; csv.DictReader strips the outer
        # quotes automatically, but extra whitespace may remain — strip() handles it.
        # 証券コード is empty for non-listed entities (investment trusts, foreign corps).
        sec = row.get("証券コード", "").strip().strip('"')
        edinet = row.get("ＥＤＩＮＥＴコード", "").strip().strip('"')
        if not sec or not edinet:
            continue
        mapping[sec] = {
            "sec_code": sec,
            "edinet_code": edinet,
            "filer_name": row.get("提出者名", "").strip().strip('"'),
            "listing": row.get("上場区分", "").strip().strip('"'),
            "fiscal_month": row.get("決算日", "").strip().strip('"'),
            "industry": row.get("提出者業種", "").strip().strip('"'),
        }
    return mapping


def save_csv(mapping: dict[str, dict]) -> None:
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(mapping.values(), key=lambda r: r["sec_code"])
    with OUTPUT_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Saved {len(rows)} entries -> {OUTPUT_CSV}")


def load_csv() -> dict[str, dict]:
    if not OUTPUT_CSV.exists():
        return {}
    with OUTPUT_CSV.open(encoding="utf-8") as f:
        return {row["sec_code"]: row for row in csv.DictReader(f)}


def normalize_sec_code(sec_code: str) -> str:
    """Convert user-facing 4-digit code to the 5-digit form used in EDINET CSV.

    EDINET stores securities codes as 5 characters with a trailing zero
    (e.g. "7203" -> "72030"). This is an EDINET-specific convention and differs
    from the standard 4-digit TSE code that users and most data sources use.
    """
    if len(sec_code) == 4 and sec_code.isdigit():
        return sec_code + "0"
    return sec_code


def lookup(sec_code: str) -> None:
    mapping = load_csv()
    if not mapping:
        print("company_map.csv not found. Run without --sec-code first.")
        return
    result = mapping.get(normalize_sec_code(sec_code))
    if result:
        for k, v in result.items():
            print(f"{k:15}: {v}")
    else:
        print(f"Not found: {sec_code}  (total entries: {len(mapping)})")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sec-code", type=str, default=None, help="lookup a single securities code")
    args = parser.parse_args()

    if args.sec_code:
        lookup(args.sec_code)
        return

    rows = download_edinet_code_list()
    print(f"  {len(rows)} rows parsed")

    mapping = build_map(rows)
    print(f"  {len(mapping)} entries with securities code")

    save_csv(mapping)

    print("\nSample (listed stocks, first 5):")
    listed = [r for r in mapping.values() if r["listing"] == "上場"]
    for r in sorted(listed, key=lambda x: x["sec_code"])[:5]:
        print(f"  {r['sec_code']} -> {r['edinet_code']}  {r['filer_name']}")


if __name__ == "__main__":
    main()
