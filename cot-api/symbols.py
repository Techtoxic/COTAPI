# Symbol → CFTC contract code mapping
# Keys are individual assets as reported by CFTC (not pairs)
# e.g. gold, eur, jpy — pairing logic belongs in the frontend strategy layer

SYMBOL_MAP = {
    # Metals
    "GOLD": {
        "code": "088691",
        "name": "GOLD - COMMODITY EXCHANGE INC.",
        "category": "metals",
        "description": "CONTRACTS OF 100 TROY OUNCES",
    },
    "SILVER": {
        "code": "084691",
        "name": "SILVER - COMMODITY EXCHANGE INC.",
        "category": "metals",
        "description": "CONTRACTS OF 5,000 TROY OUNCES",
    },

    # Currencies — individual, as reported by CFTC
    "AUD": {
        "code": "232741",
        "name": "AUSTRALIAN DOLLAR - CHICAGO MERCANTILE EXCHANGE",
        "category": "currencies",
        "description": "CONTRACTS OF AUD 100,000",
    },
    "GBP": {
        "code": "096742",
        "name": "BRITISH POUND STERLING - CHICAGO MERCANTILE EXCHANGE",
        "category": "currencies",
        "description": "CONTRACTS OF GBP 62,500",
    },
    "CAD": {
        "code": "090741",
        "name": "CANADIAN DOLLAR - CHICAGO MERCANTILE EXCHANGE",
        "category": "currencies",
        "description": "CONTRACTS OF CAD 100,000",
    },
    "EUR": {
        "code": "099741",
        "name": "EURO FX - CHICAGO MERCANTILE EXCHANGE",
        "category": "currencies",
        "description": "CONTRACTS OF EUR 125,000",
    },
    "JPY": {
        "code": "097741",
        "name": "JAPANESE YEN - CHICAGO MERCANTILE EXCHANGE",
        "category": "currencies",
        "description": "CONTRACTS OF JPY 12,500,000",
    },
    "CHF": {
        "code": "092741",
        "name": "SWISS FRANC - CHICAGO MERCANTILE EXCHANGE",
        "category": "currencies",
        "description": "CONTRACTS OF CHF 125,000",
    },
    "DXY": {
        "code": "098662",
        "name": "U.S. DOLLAR INDEX - ICE FUTURES U.S.",
        "category": "currencies",
        "description": "CONTRACTS OF USD 1,000 X INDEX",
    },
    "MXN": {
        "code": "095741",
        "name": "MEXICAN PESO - CHICAGO MERCANTILE EXCHANGE",
        "category": "currencies",
        "description": "CONTRACTS OF MXN 500,000",
    },
    "NZD": {
        "code": "112741",
        "name": "NEW ZEALAND DOLLAR - CHICAGO MERCANTILE EXCHANGE",
        "category": "currencies",
        "description": "CONTRACTS OF NZD 100,000",
    },
    "BRL": {
        "code": "102741",
        "name": "BRAZILIAN REAL - CHICAGO MERCANTILE EXCHANGE",
        "category": "currencies",
        "description": "CONTRACTS OF BRL 100,000",
    },
    "ZAR": {
        "code": "122741",
        "name": "SOUTH AFRICAN RAND - CHICAGO MERCANTILE EXCHANGE",
        "category": "currencies",
        "description": "CONTRACTS OF ZAR 500,000",
    },
}

# Reverse lookup: CFTC code → symbol
CODE_TO_SYMBOL = {v["code"]: k for k, v in SYMBOL_MAP.items()}

# All metals symbols
METALS = [k for k, v in SYMBOL_MAP.items() if v["category"] == "metals"]

# All currency symbols
CURRENCIES = [k for k, v in SYMBOL_MAP.items() if v["category"] == "currencies"]


def get_symbol_info(symbol: str) -> dict | None:
    return SYMBOL_MAP.get(symbol.upper())


def get_code(symbol: str) -> str | None:
    info = get_symbol_info(symbol)
    return info["code"] if info else None


def get_all_codes() -> list[str]:
    return [v["code"] for v in SYMBOL_MAP.values()]