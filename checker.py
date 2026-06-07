"""
checker.py
----------
Polls the CFTC website to detect if new COT data has been published.
Compares the zip file's Last-Modified header against the latest as_of date
stored in Supabase. Writes new_data=true|false to GITHUB_OUTPUT.

Usage:
    python checker.py
Exit code is always 0 (failures default to running the ingest as a fallback).
"""

import os
import sys
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; OpenCOT-Checker/1.0)"}
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")


def set_gha_output(name: str, value: str):
    """Write step output to GITHUB_OUTPUT (GHA) or print for local runs."""
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a") as f:
            f.write(f"{name}={value}\n")
    print(f"[output] {name}={value}")


def get_cftc_last_modified(year: int) -> datetime | None:
    """HEAD request to CFTC zip — returns Last-Modified as datetime (UTC)."""
    url = f"https://www.cftc.gov/files/dea/history/dea_fut_xls_{year}.zip"
    try:
        r = requests.head(url, headers=HEADERS, timeout=30, allow_redirects=True)
        lm = r.headers.get("Last-Modified")
        if lm:
            return datetime.strptime(lm, "%a, %d %b %Y %H:%M:%S %Z")
        print("  WARNING: No Last-Modified header in CFTC response")
    except Exception as e:
        print(f"  CFTC HEAD request failed: {e}")
    return None


def get_supabase_latest_date() -> str | None:
    """Returns the most recent as_of date string (YYYY-MM-DD) from Supabase."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("  WARNING: Supabase credentials not set")
        return None
    try:
        from supabase import create_client
        sb = create_client(SUPABASE_URL, SUPABASE_KEY)
        res = (
            sb.table("cot_positions")
            .select("as_of")
            .order("as_of", desc=True)
            .limit(1)
            .execute()
        )
        if res.data:
            return res.data[0]["as_of"]
    except Exception as e:
        print(f"  Supabase query failed: {e}")
    return None


if __name__ == "__main__":
    year = datetime.now().year
    print(f"\nCOT availability check — {year}")
    print("-" * 40)

    cftc_modified = get_cftc_last_modified(year)
    supabase_latest = get_supabase_latest_date()

    print(f"  CFTC Last-Modified : {cftc_modified}")
    print(f"  Supabase latest    : {supabase_latest}")

    # Can't read CFTC → run ingest as a safe fallback
    if cftc_modified is None:
        print("  → Cannot determine CFTC file age; running ingest as fallback")
        set_gha_output("new_data", "true")
        sys.exit(0)

    # No data in DB at all → definitely need to ingest
    if supabase_latest is None:
        print("  → No data in Supabase; running ingest")
        set_gha_output("new_data", "true")
        sys.exit(0)

    sb_date = datetime.strptime(supabase_latest, "%Y-%m-%d")

    # CFTC releases on Fridays for the week ending the prior Tuesday.
    # If the CFTC file's Last-Modified date is newer than our stored date → new week arrived.
    if cftc_modified.date() > sb_date.date():
        print(f"  → NEW DATA detected — CFTC: {cftc_modified.date()}, DB: {sb_date.date()}")
        set_gha_output("new_data", "true")
    else:
        print(f"  → No new data — CFTC: {cftc_modified.date()}, DB: {sb_date.date()}")
        set_gha_output("new_data", "false")
