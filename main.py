"""
main.py
-------
FastAPI REST API for COT (Commitments of Traders) data.
Reads from Supabase PostgreSQL.
"""

import os
from datetime import datetime
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from supabase import create_client, Client
from dotenv import load_dotenv
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from symbols import SYMBOL_MAP, METALS, CURRENCIES

load_dotenv()

# ── Supabase ──────────────────────────────────────────────────────────────────
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_ANON_KEY")  # anon key for reads
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ── Rate Limiter ──────────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="COT Data API",
    description="Free REST API for CFTC Commitments of Traders data. Metals & Currencies.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


# ── Helpers ───────────────────────────────────────────────────────────────────
def validate_symbol(symbol: str, category: str = None):
    symbol = symbol.upper()
    info = SYMBOL_MAP.get(symbol)
    if not info:
        raise HTTPException(status_code=404, detail=f"Symbol '{symbol}' not found. Check /api/symbols for valid symbols.")
    if category and info["category"] != category:
        raise HTTPException(status_code=400, detail=f"'{symbol}' is not in category '{category}'. It belongs to '{info['category']}'.")
    return symbol


def get_latest(symbol: str) -> dict:
    res = (
        supabase.table("cot_positions")
        .select("*")
        .eq("symbol", symbol)
        .order("as_of", desc=True)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail=f"No data found for symbol '{symbol}'")
    return res.data[0]


def get_history(symbol: str, weeks: int = 12) -> list:
    weeks = min(weeks, 260)  # cap at 5 years
    res = (
        supabase.table("cot_positions")
        .select("*")
        .eq("symbol", symbol)
        .order("as_of", desc=True)
        .limit(weeks)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail=f"No history found for symbol '{symbol}'")
    return res.data


def shape_full(row: dict) -> dict:
    info = SYMBOL_MAP.get(row["symbol"], {})
    return {
        "symbol": row["symbol"],
        "name": row["name"],
        "description": info.get("description", ""),
        "as_of": row["as_of"],
        "open_interest": row["open_interest"],
        "noncommercial": {
            "long": row["noncomm_long"],
            "short": row["noncomm_short"],
            "spreads": row["noncomm_spreads"],
            "net": row["noncomm_net"],
        },
        "commercial": {
            "long": row["comm_long"],
            "short": row["comm_short"],
            "net": row["comm_net"],
        },
        "nonreportable": {
            "long": row["nonrept_long"],
            "short": row["nonrept_short"],
            "net": row["nonrept_net"],
        },
        "total": {
            "long": row["total_long"],
            "short": row["total_short"],
        },
        "changes": {
            "open_interest": row["chg_open_interest"],
            "noncomm_long": row["chg_noncomm_long"],
            "noncomm_short": row["chg_noncomm_short"],
            "noncomm_spreads": row["chg_noncomm_spreads"],
            "comm_long": row["chg_comm_long"],
            "comm_short": row["chg_comm_short"],
            "total_long": row["chg_total_long"],
            "total_short": row["chg_total_short"],
            "nonrept_long": row["chg_nonrept_long"],
            "nonrept_short": row["chg_nonrept_short"],
        },
    }


# ── Root ──────────────────────────────────────────────────────────────────────
@app.get("/")
def root():
    return {
        "name": "COT Data API",
        "version": "1.0.0",
        "docs": "/docs",
        "endpoints": "/api/symbols",
        "rate_limit": "60 requests/minute",
        "source": "CFTC - Commitments of Traders",
    }


# ── Symbols ───────────────────────────────────────────────────────────────────
@app.get("/api/symbols")
@limiter.limit("60/minute")
def list_symbols(request: Request):
    return {
        "metals": {k: v for k, v in SYMBOL_MAP.items() if v["category"] == "metals"},
        "currencies": {k: v for k, v in SYMBOL_MAP.items() if v["category"] == "currencies"},
    }


@app.get("/api/last-updated")
@limiter.limit("60/minute")
def last_updated(request: Request):
    res = (
        supabase.table("cot_positions")
        .select("as_of")
        .order("as_of", desc=True)
        .limit(1)
        .execute()
    )
    if not res.data:
        return {"last_updated": None}
    return {
        "last_updated": res.data[0]["as_of"],
        "next_update": "Every Friday after 3:30 PM EST (CFTC release schedule)",
    }


@app.get("/api/all")
@limiter.limit("30/minute")
def get_all(request: Request):
    results = {}
    for symbol in SYMBOL_MAP:
        try:
            row = get_latest(symbol)
            results[symbol] = shape_full(row)
        except HTTPException:
            results[symbol] = None
    return results


# ── History endpoints (MUST be before generic /{category}/{symbol} routes) ────
@app.get("/api/history/{symbol}")
@limiter.limit("30/minute")
def get_symbol_history(request: Request, symbol: str, weeks: int = 12, from_date: str = None, to_date: str = None):
    symbol = validate_symbol(symbol)
    query = (
        supabase.table("cot_positions")
        .select("*")
        .eq("symbol", symbol)
        .order("as_of", desc=True)
    )
    if from_date:
        query = query.gte("as_of", from_date)
    if to_date:
        query = query.lte("as_of", to_date)
    if not from_date and not to_date:
        query = query.limit(min(weeks, 260))

    res = query.execute()
    if not res.data:
        raise HTTPException(status_code=404, detail=f"No history found for '{symbol}'")
    return {
        "symbol": symbol,
        "weeks": len(res.data),
        "data": [shape_full(r) for r in res.data],
    }


@app.get("/api/history/{symbol}/{group}/{field}")
@limiter.limit("30/minute")
def get_field_history(request: Request, symbol: str, group: str, field: str, weeks: int = 12, from_date: str = None, to_date: str = None):
    symbol = validate_symbol(symbol)

    col_map = {
        "commercial":    {"long": "comm_long", "short": "comm_short", "net": "comm_net"},
        "noncommercial": {"long": "noncomm_long", "short": "noncomm_short", "net": "noncomm_net", "spreads": "noncomm_spreads"},
        "nonreportable": {"long": "nonrept_long", "short": "nonrept_short", "net": "nonrept_net"},
    }

    if group not in col_map or field not in col_map[group]:
        raise HTTPException(status_code=400, detail=f"Invalid group '{group}' or field '{field}'.")

    db_col = col_map[group][field]

    query = (
        supabase.table("cot_positions")
        .select(f"as_of,{db_col}")
        .eq("symbol", symbol)
        .order("as_of", desc=True)
    )
    if from_date:
        query = query.gte("as_of", from_date)
    if to_date:
        query = query.lte("as_of", to_date)
    if not from_date and not to_date:
        query = query.limit(min(weeks, 260))

    res = query.execute()
    if not res.data:
        raise HTTPException(status_code=404, detail=f"No history found for '{symbol}'")

    return {
        "symbol": symbol,
        "group": group,
        "field": field,
        "weeks": len(res.data),
        "data": [{"as_of": r["as_of"], field: r[db_col]} for r in res.data],
    }


# ── Generic symbol endpoint (works for both metals and currencies) ─────────────
@app.get("/api/{category}/{symbol}")
@limiter.limit("60/minute")
def get_symbol_full(request: Request, category: str, symbol: str):
    symbol = validate_symbol(symbol, category)
    row = get_latest(symbol)
    return shape_full(row)


@app.get("/api/{category}/{symbol}/commercial")
@limiter.limit("60/minute")
def get_commercial(request: Request, category: str, symbol: str):
    symbol = validate_symbol(symbol, category)
    row = get_latest(symbol)
    return {
        "symbol": symbol,
        "as_of": row["as_of"],
        "commercial": {
            "long": row["comm_long"],
            "short": row["comm_short"],
            "net": row["comm_net"],
        },
    }


@app.get("/api/{category}/{symbol}/commercial/long")
@limiter.limit("60/minute")
def get_commercial_long(request: Request, category: str, symbol: str):
    symbol = validate_symbol(symbol, category)
    row = get_latest(symbol)
    return {"symbol": symbol, "as_of": row["as_of"], "commercial_long": row["comm_long"]}


@app.get("/api/{category}/{symbol}/commercial/short")
@limiter.limit("60/minute")
def get_commercial_short(request: Request, category: str, symbol: str):
    symbol = validate_symbol(symbol, category)
    row = get_latest(symbol)
    return {"symbol": symbol, "as_of": row["as_of"], "commercial_short": row["comm_short"]}


@app.get("/api/{category}/{symbol}/commercial/net")
@limiter.limit("60/minute")
def get_commercial_net(request: Request, category: str, symbol: str):
    symbol = validate_symbol(symbol, category)
    row = get_latest(symbol)
    return {"symbol": symbol, "as_of": row["as_of"], "commercial_net": row["comm_net"]}


@app.get("/api/{category}/{symbol}/commercial/changes")
@limiter.limit("60/minute")
def get_commercial_changes(request: Request, category: str, symbol: str):
    symbol = validate_symbol(symbol, category)
    row = get_latest(symbol)
    return {
        "symbol": symbol,
        "as_of": row["as_of"],
        "commercial_changes": {
            "long": row["chg_comm_long"],
            "short": row["chg_comm_short"],
        },
    }


@app.get("/api/{category}/{symbol}/noncommercial")
@limiter.limit("60/minute")
def get_noncommercial(request: Request, category: str, symbol: str):
    symbol = validate_symbol(symbol, category)
    row = get_latest(symbol)
    return {
        "symbol": symbol,
        "as_of": row["as_of"],
        "noncommercial": {
            "long": row["noncomm_long"],
            "short": row["noncomm_short"],
            "spreads": row["noncomm_spreads"],
            "net": row["noncomm_net"],
        },
    }


@app.get("/api/{category}/{symbol}/noncommercial/long")
@limiter.limit("60/minute")
def get_noncommercial_long(request: Request, category: str, symbol: str):
    symbol = validate_symbol(symbol, category)
    row = get_latest(symbol)
    return {"symbol": symbol, "as_of": row["as_of"], "noncommercial_long": row["noncomm_long"]}


@app.get("/api/{category}/{symbol}/noncommercial/short")
@limiter.limit("60/minute")
def get_noncommercial_short(request: Request, category: str, symbol: str):
    symbol = validate_symbol(symbol, category)
    row = get_latest(symbol)
    return {"symbol": symbol, "as_of": row["as_of"], "noncommercial_short": row["noncomm_short"]}


@app.get("/api/{category}/{symbol}/noncommercial/net")
@limiter.limit("60/minute")
def get_noncommercial_net(request: Request, category: str, symbol: str):
    symbol = validate_symbol(symbol, category)
    row = get_latest(symbol)
    return {"symbol": symbol, "as_of": row["as_of"], "noncommercial_net": row["noncomm_net"]}


@app.get("/api/{category}/{symbol}/noncommercial/spreads")
@limiter.limit("60/minute")
def get_noncommercial_spreads(request: Request, category: str, symbol: str):
    symbol = validate_symbol(symbol, category)
    row = get_latest(symbol)
    return {"symbol": symbol, "as_of": row["as_of"], "noncommercial_spreads": row["noncomm_spreads"]}


@app.get("/api/{category}/{symbol}/noncommercial/changes")
@limiter.limit("60/minute")
def get_noncommercial_changes(request: Request, category: str, symbol: str):
    symbol = validate_symbol(symbol, category)
    row = get_latest(symbol)
    return {
        "symbol": symbol,
        "as_of": row["as_of"],
        "noncommercial_changes": {
            "long": row["chg_noncomm_long"],
            "short": row["chg_noncomm_short"],
            "spreads": row["chg_noncomm_spreads"],
        },
    }


@app.get("/api/{category}/{symbol}/nonreportable")
@limiter.limit("60/minute")
def get_nonreportable(request: Request, category: str, symbol: str):
    symbol = validate_symbol(symbol, category)
    row = get_latest(symbol)
    return {
        "symbol": symbol,
        "as_of": row["as_of"],
        "nonreportable": {
            "long": row["nonrept_long"],
            "short": row["nonrept_short"],
            "net": row["nonrept_net"],
        },
    }


@app.get("/api/{category}/{symbol}/nonreportable/long")
@limiter.limit("60/minute")
def get_nonreportable_long(request: Request, category: str, symbol: str):
    symbol = validate_symbol(symbol, category)
    row = get_latest(symbol)
    return {"symbol": symbol, "as_of": row["as_of"], "nonreportable_long": row["nonrept_long"]}


@app.get("/api/{category}/{symbol}/nonreportable/short")
@limiter.limit("60/minute")
def get_nonreportable_short(request: Request, category: str, symbol: str):
    symbol = validate_symbol(symbol, category)
    row = get_latest(symbol)
    return {"symbol": symbol, "as_of": row["as_of"], "nonreportable_short": row["nonrept_short"]}


@app.get("/api/{category}/{symbol}/nonreportable/net")
@limiter.limit("60/minute")
def get_nonreportable_net(request: Request, category: str, symbol: str):
    symbol = validate_symbol(symbol, category)
    row = get_latest(symbol)
    return {"symbol": symbol, "as_of": row["as_of"], "nonreportable_net": row["nonrept_net"]}


@app.get("/api/{category}/{symbol}/openinterest")
@limiter.limit("60/minute")
def get_open_interest(request: Request, category: str, symbol: str):
    symbol = validate_symbol(symbol, category)
    row = get_latest(symbol)
    return {
        "symbol": symbol,
        "as_of": row["as_of"],
        "open_interest": row["open_interest"],
        "change": row["chg_open_interest"],
    }


@app.get("/api/{category}/{symbol}/changes")
@limiter.limit("60/minute")
def get_all_changes(request: Request, category: str, symbol: str):
    symbol = validate_symbol(symbol, category)
    row = get_latest(symbol)
    return {
        "symbol": symbol,
        "as_of": row["as_of"],
        "changes": {
            "open_interest": row["chg_open_interest"],
            "noncomm_long": row["chg_noncomm_long"],
            "noncomm_short": row["chg_noncomm_short"],
            "noncomm_spreads": row["chg_noncomm_spreads"],
            "comm_long": row["chg_comm_long"],
            "comm_short": row["chg_comm_short"],
            "total_long": row["chg_total_long"],
            "total_short": row["chg_total_short"],
            "nonrept_long": row["chg_nonrept_long"],
            "nonrept_short": row["chg_nonrept_short"],
        },
    }
