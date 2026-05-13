"""
EDINET API v2 - basic verification script.
Checks: (1) document list endpoint, (2) document download (XBRL zip).
Usage: python step0_verify.py [date] [edinet_code]
  date        : YYYY-MM-DD (default: today)
  edinet_code : e.g. E02144 (Toyota). default: first code found on that date.
"""

import json
import sys
import zipfile
import io
from datetime import date
from pathlib import Path
import requests

CONFIG_PATH = Path(__file__).parent.parent.parent / "secret.json"


def load_api_key() -> str:
    with CONFIG_PATH.open() as f:
        return json.load(f)["edinet"]["api_key"]


def fetch_document_list(api_key: str, target_date: str) -> dict:
    """GET /api/v2/documents.json - document list for a given date."""
    # disclosure.edinet-fsa.go.jp  = API endpoint (requires Subscription-Key)
    # disclosure2dl.edinet-fsa.go.jp = static file downloads (no key needed)
    url = "https://disclosure.edinet-fsa.go.jp/api/v2/documents.json"
    params = {
        "date": target_date,
        "type": 2,  # 2 = metadata + document list
        "Subscription-Key": api_key,
    }
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def fetch_xbrl_zip(api_key: str, doc_id: str) -> bytes:
    """GET /api/v2/documents/{docID} - download XBRL zip for a document."""
    url = f"https://disclosure.edinet-fsa.go.jp/api/v2/documents/{doc_id}"
    params = {
        "type": 1,  # 1 = XBRL zip
        "Subscription-Key": api_key,
    }
    resp = requests.get(url, params=params, timeout=60)
    resp.raise_for_status()
    return resp.content


def main() -> None:
    api_key = load_api_key()

    target_date = sys.argv[1] if len(sys.argv) > 1 else str(date.today())
    filter_code = sys.argv[2] if len(sys.argv) > 2 else None

    print(f"=== EDINET API v2 verification ===")
    print(f"Date: {target_date}")

    # --- Step 1: document list ---
    print("\n[1] Fetching document list...")
    data = fetch_document_list(api_key, target_date)

    status = data.get("metadata", {}).get("status")
    total = data.get("metadata", {}).get("resultset", {}).get("count", 0)
    print(f"    Status : {status}")
    print(f"    Total  : {total} documents")

    results = data.get("results", [])
    if not results:
        print("    No documents found. Try a different date (weekday with market open).")
        return

    # Show first 5 entries
    print("\n    Sample (up to 5 docs):")
    for doc in results[:5]:
        print(f"      [{doc.get('edinetCode')}] {doc.get('filerName')} "
              f"| {doc.get('docDescription')} | docID={doc.get('docID')}")

    # --- Step 2: pick a doc to download ---
    if filter_code:
        candidates = [d for d in results if d.get("edinetCode") == filter_code]
        if not candidates:
            print(f"\n    No document found for edinetCode={filter_code} on {target_date}.")
            return
        target_doc = candidates[0]
    else:
        # xbrlFlag is not guaranteed on the first record; picking results[0] is fine
        # for a connectivity check — Step 3 will filter by docTypeCode properly.
        target_doc = results[0]

    doc_id = target_doc["docID"]
    filer = target_doc.get("filerName", "")
    desc = target_doc.get("docDescription", "")
    print(f"\n[2] Downloading XBRL zip for: [{target_doc.get('edinetCode')}] {filer} ({desc})")
    print(f"    docID: {doc_id}")

    raw = fetch_xbrl_zip(api_key, doc_id)
    print(f"    Downloaded: {len(raw):,} bytes")

    # List files inside the zip
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        names = zf.namelist()
        print(f"    Files in zip ({len(names)} total):")
        for name in names[:20]:
            print(f"      {name}")
        if len(names) > 20:
            print(f"      ... and {len(names) - 20} more")

    print("\n=== OK: EDINET API v2 is working ===")


if __name__ == "__main__":
    main()
