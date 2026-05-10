"""
ingest.py
---------
Downloads CFTC COT zip files, parses them, and upserts into Supabase.

Usage:
    # Full historical backload (run once on your laptop)
    python ingest.py --backload --from-year 2010

    # Latest week only (runs every Friday via GitHub Actions)
    python ingest.py

    # Specific year
    python ingest.py --year 2025
"""

import os
import sys
import glob
import zipfile
import argparse
import requests
import pandas as pd
from datetime import datetime
from supabase import create_client, Client
from dotenv import load_dotenv
from symbols import SYMBOL_MAP, CODE_TO_SYMBOL

load_dotenv()

# ── Supabase client ───────────────────────────────────────────────────────────
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")  # use service key for inserts

if not SUPABASE_URL or not SUPABASE_KEY:
    print("ERROR: SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in .env")
    sys.exit(1)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ── CFTC URLs ─────────────────────────────────────────────────────────────────
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
CACHE_DIR = "cache"
os.makedirs(CACHE_DIR, exist_ok=True)


def cot_url(year: int) -> str:
    return f"https://www.cftc.gov/files/dea/history/dea_fut_xls_{year}.zip"


# ── Download ──────────────────────────────────────────────────────────────────
def download_year(year: int, force: bool = False) -> str | None:
    zip_path = os.path.join(CACHE_DIR, f"cot_{year}.zip")

    if os.path.exists(zip_path) and not force:
        print(f"  [{year}] Using cached zip")
        return zip_path

    url = cot_url(year)
    print(f"  [{year}] Downloading {url} ...")
    try:
        r = requests.get(url, headers=HEADERS, timeout=60)
        r.raise_for_status()
        with open(zip_path, "wb") as f:
            f.write(r.content)
        print(f"  [{year}] Downloaded ({len(r.content) / 1024:.0f} KB)")
        return zip_path
    except Exception as e:
        print(f"  [{year}] Download failed: {e}")
        return None


# ── Parse ─────────────────────────────────────────────────────────────────────
COT_COLUMNS = {
    "CFTC_Contract_Market_Code":       "cftc_code",
    "Market_and_Exchange_Names":       "name",
    "As_of_Date_In_Form_YYMMDD":       "as_of_raw",
    "Open_Interest_All":               "open_interest",
    # Non-Commercial
    "NonComm_Positions_Long_All":      "noncomm_long",
    "NonComm_Positions_Short_All":     "noncomm_short",
    "NonComm_Positions_Spread_All":    "noncomm_spreads",
    # Commercial
    "Comm_Positions_Long_All":         "comm_long",
    "Comm_Positions_Short_All":        "comm_short",
    # Total Reportable
    "Tot_Rept_Positions_Long_All":     "total_long",
    "Tot_Rept_Positions_Short_All":    "total_short",
    # Non-Reportable
    "NonRept_Positions_Long_All":      "nonrept_long",
    "NonRept_Positions_Short_All":     "nonrept_short",
    # Changes
    "Change_in_Open_Interest_All":     "chg_open_interest",
    "Change_in_NonComm_Long_All":      "chg_noncomm_long",
    "Change_in_NonComm_Short_All":     "chg_noncomm_short",
    "Change_in_NonComm_Spead_All":     "chg_noncomm_spreads",
    "Change_in_Comm_Long_All":         "chg_comm_long",
    "Change_in_Comm_Short_All":        "chg_comm_short",
    "Change_in_Tot_Rept_Long_All":     "chg_total_long",
    "Change_in_Tot_Rept_Short_All":    "chg_total_short",
    "Change_in_NonRept_Long_All":      "chg_nonrept_long",
    "Change_in_NonRept_Short_All":     "chg_nonrept_short",
}

TARGET_CODES = set(SYMBOL_MAP[s]["code"] for s in SYMBOL_MAP)


def parse_zip(zip_path: str) -> pd.DataFrame | None:
    extract_dir = zip_path.replace(".zip", "_extracted")
    os.makedirs(extract_dir, exist_ok=True)

    try:
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(extract_dir)
            xls_files = [f for f in z.namelist() if f.lower().endswith((".xls", ".xlsx"))]

        if not xls_files:
            print(f"  No Excel file found in {zip_path}")
            return None

        xls_path = os.path.join(extract_dir, xls_files[0])
        engine = "xlrd" if xls_path.endswith(".xls") else "openpyxl"
        df = pd.read_excel(xls_path, engine=engine)

        # Keep only columns we need
        available = {k: v for k, v in COT_COLUMNS.items() if k in df.columns}
        df = df[list(available.keys())].rename(columns=available)

        # Filter to our target symbols only
        df["cftc_code"] = df["cftc_code"].astype(str).str.strip()
        df = df[df["cftc_code"].isin(TARGET_CODES)].copy()

        if df.empty:
            print(f"  No matching symbols found in {zip_path}")
            return None

        # Map CFTC code → symbol
        df["symbol"] = df["cftc_code"].map(CODE_TO_SYMBOL)

        # Parse date YYMMDD → YYYY-MM-DD
        def parse_date(val):
            try:
                return datetime.strptime(str(int(val)), "%y%m%d").strftime("%Y-%m-%d")
            except Exception:
                return None

        df["as_of"] = df["as_of_raw"].apply(parse_date)
        df = df.dropna(subset=["as_of", "symbol"])

        # Compute net positions
        df["noncomm_net"] = df["noncomm_long"] - df["noncomm_short"]
        df["comm_net"]    = df["comm_long"]    - df["comm_short"]
        df["nonrept_net"] = df["nonrept_long"] - df["nonrept_short"]

        # Drop raw columns we don't need in DB
        df = df.drop(columns=["as_of_raw", "cftc_code"], errors="ignore")

        # Convert all numeric columns to int (CFTC sends floats like -2681.0)
        numeric_cols = [
            "open_interest", "noncomm_long", "noncomm_short", "noncomm_spreads",
            "comm_long", "comm_short", "total_long", "total_short",
            "nonrept_long", "nonrept_short", "noncomm_net", "comm_net", "nonrept_net",
            "chg_open_interest", "chg_noncomm_long", "chg_noncomm_short",
            "chg_noncomm_spreads", "chg_comm_long", "chg_comm_short",
            "chg_total_long", "chg_total_short", "chg_nonrept_long", "chg_nonrept_short",
        ]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)

        # Clean up NaN → None for JSON compatibility
        df = df.where(pd.notna(df), None)

        print(f"  Parsed {len(df)} rows for {df['symbol'].nunique()} symbols")
        return df

    except Exception as e:
        print(f"  Parse error: {e}")
        return None


# ── Upsert to Supabase ────────────────────────────────────────────────────────
def upsert_to_supabase(df: pd.DataFrame):
    records = df.to_dict(orient="records")
    batch_size = 500
    total = 0

    for i in range(0, len(records), batch_size):
        batch = records[i: i + batch_size]
        try:
            # upsert on (symbol, as_of) unique constraint — no duplicates
            supabase.table("cot_positions").upsert(
                batch,
                on_conflict="symbol,as_of"
            ).execute()
            total += len(batch)
            print(f"  Upserted {total}/{len(records)} rows...")
        except Exception as e:
            print(f"  Upsert error on batch {i}: {e}")

    print(f"  Done — {total} rows upserted")


# ── Main ──────────────────────────────────────────────────────────────────────
def process_year(year: int, force_download: bool = False):
    print(f"\n{'='*50}")
    print(f"  Processing year: {year}")
    print(f"{'='*50}")

    zip_path = download_year(year, force=force_download)
    if not zip_path:
        return

    df = parse_zip(zip_path)
    if df is None or df.empty:
        return

    upsert_to_supabase(df)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="COT CFTC Data Ingest")
    parser.add_argument("--backload", action="store_true", help="Run full historical backload")
    parser.add_argument("--from-year", type=int, default=2010, help="Start year for backload (default: 2010)")
    parser.add_argument("--year", type=int, help="Process a specific year")
    parser.add_argument("--force", action="store_true", help="Force re-download even if cached")
    args = parser.parse_args()

    current_year = datetime.now().year

    if args.backload:
        print(f"\nStarting historical backload from {args.from_year} to {current_year}...")
        for year in range(args.from_year, current_year + 1):
            process_year(year, force_download=args.force)
        print("\nBackload complete!")

    elif args.year:
        process_year(args.year, force_download=args.force)

    else:
        # Default: current year only (used by GitHub Actions every Friday)
        print(f"\nWeekly ingest — current year ({current_year})...")
        process_year(current_year, force_download=True)
        print("\nWeekly ingest complete!")
