from datetime import date, datetime, timedelta
import os
import time
from typing import Dict, List, Optional

import requests
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Momentum Stock Screener")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

API_KEY = os.getenv("FINNHUB_API_KEY")
FINNHUB_BASE = "https://finnhub.io/api/v1"

# In-memory cache. Good enough for MVP on Render.
UNIVERSE: List[Dict] = []
MATCHES: List[Dict] = []
SCAN_STATUS: Dict = {
    "running": False,
    "total_symbols": 0,
    "symbols_scanned": 0,
    "matches_found": 0,
    "last_scan_started": None,
    "last_scan_finished": None,
    "message": "Ready. Load universe, then run scan.",
}


def finnhub_get(path: str, params: Optional[Dict] = None) -> Dict:
    if not API_KEY:
        return {"error": "FINNHUB_API_KEY is missing in Render environment variables."}
    params = params or {}
    params["token"] = API_KEY
    response = requests.get(f"{FINNHUB_BASE}{path}", params=params, timeout=20)
    try:
        return response.json()
    except Exception:
        return {"error": "Finnhub returned a non-JSON response", "status_code": response.status_code}


def is_common_stock(symbol_row: Dict) -> bool:
    symbol = symbol_row.get("symbol", "")
    description = symbol_row.get("description", "").upper()
    stock_type = symbol_row.get("type", "").upper()

    bad_symbol_parts = [".", "-", "/", "^", "="]
    bad_words = [
        "ETF", "ETN", "FUND", "TRUST", "WARRANT", "RIGHT", "UNIT", "PREFERRED",
        "PREF", "ADR", "NOTE", "BOND", "INDEX", "SPAC", "ACQUISITION CORP WT",
    ]

    if not symbol or any(part in symbol for part in bad_symbol_parts):
        return False
    if len(symbol) > 5:
        return False
    if stock_type and stock_type not in ["COMMON STOCK", "", "EQS"]:
        return False
    if any(word in description for word in bad_words):
        return False
    return True


def get_quote(symbol: str) -> Dict:
    return finnhub_get("/quote", {"symbol": symbol})


def get_today_news(symbol: str) -> List[Dict]:
    today = date.today().isoformat()
    news = finnhub_get("/company-news", {"symbol": symbol, "from": today, "to": today})
    return news if isinstance(news, list) else []


def get_candle_data(symbol: str, resolution: str = "5", lookback_days: int = 10) -> Dict:
    now = int(time.time())
    start = now - lookback_days * 24 * 60 * 60
    return finnhub_get(
        "/stock/candle",
        {"symbol": symbol, "resolution": resolution, "from": start, "to": now},
    )


def calculate_relative_volume(symbol: str) -> Dict:
    candles = get_candle_data(symbol, "5", 10)
    if candles.get("s") != "ok" or not candles.get("v") or not candles.get("t"):
        return {"relative_volume": 0, "today_volume": 0, "average_volume": 0, "error": candles}

    today_str = date.today().isoformat()
    by_day: Dict[str, int] = {}

    for timestamp, volume in zip(candles["t"], candles["v"]):
        day = datetime.fromtimestamp(timestamp).date().isoformat()
        by_day[day] = by_day.get(day, 0) + int(volume)

    today_volume = by_day.get(today_str, 0)
    prior_days = [volume for day, volume in by_day.items() if day != today_str and volume > 0]
    average_volume = sum(prior_days) / len(prior_days) if prior_days else 0
    relative_volume = today_volume / average_volume if average_volume else 0

    return {
        "relative_volume": round(relative_volume, 2),
        "today_volume": today_volume,
        "average_volume": round(average_volume, 0),
    }


@app.get("/")
def root():
    return {
        "status": "running",
        "app": "Momentum Stock Screener",
        "filters": {
            "price": "$3-$20",
            "change": ">= 20% today",
            "relative_volume": ">= 5x",
            "news": "at least one company news article today",
        },
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
        "has_finnhub_key": bool(API_KEY),
        "universe_count": len(UNIVERSE),
        "matches_count": len(MATCHES),
    }


@app.get("/debug/{symbol}")
def debug(symbol: str):
    quote = get_quote(symbol.upper())
    news = get_today_news(symbol.upper())
    relvol = calculate_relative_volume(symbol.upper())
    return {"symbol": symbol.upper(), "quote": quote, "news_count_today": len(news), "relative_volume": relvol}


@app.post("/load-universe")
def load_universe(exchange: str = Query("US")):
    global UNIVERSE
    data = finnhub_get("/stock/symbol", {"exchange": exchange})
    if not isinstance(data, list):
        return {"status": "error", "message": "Could not load symbols", "raw": data}

    UNIVERSE = [row for row in data if is_common_stock(row)]
    SCAN_STATUS.update({
        "total_symbols": len(UNIVERSE),
        "symbols_scanned": 0,
        "matches_found": len(MATCHES),
        "message": f"Loaded {len(UNIVERSE)} common-stock-like U.S. symbols.",
    })
    return {"status": "ok", "total_symbols": len(UNIVERSE), "sample": UNIVERSE[:10]}


@app.post("/scan")
def run_scan(
    start: int = Query(0),
    limit: int = Query(50),
    min_price: float = Query(3),
    max_price: float = Query(20),
    min_change: float = Query(20),
    min_relative_volume: float = Query(5),
    require_news: bool = Query(True),
):
    global MATCHES

    if not API_KEY:
        return {"status": "error", "message": "FINNHUB_API_KEY is missing in Render."}
    if not UNIVERSE:
        return {"status": "error", "message": "Universe is empty. Call /load-universe first."}

    SCAN_STATUS.update({
        "running": True,
        "last_scan_started": datetime.utcnow().isoformat() + "Z",
        "message": "Scanning batch...",
    })

    batch = UNIVERSE[start:start + limit]
    new_matches = []
    inspected = []

    for row in batch:
        symbol = row["symbol"]
        quote = get_quote(symbol)
        current_price = float(quote.get("c") or 0)
        previous_close = float(quote.get("pc") or 0)
        day_change = ((current_price - previous_close) / previous_close) * 100 if previous_close else 0

        reason = []
        if not (min_price <= current_price <= max_price):
            reason.append("price outside range")
        if day_change < min_change:
            reason.append("day change below target")

        relvol = {"relative_volume": 0, "today_volume": 0, "average_volume": 0}
        news = []

        if not reason:
            relvol = calculate_relative_volume(symbol)
            if relvol["relative_volume"] < min_relative_volume:
                reason.append("relative volume below target")

        if not reason and require_news:
            news = get_today_news(symbol)
            if len(news) == 0:
                reason.append("no news today")

        passed = len(reason) == 0
        inspected.append({"symbol": symbol, "price": current_price, "change": round(day_change, 2), "passed": passed, "reason": reason})

        if passed:
            latest_news = news[0] if news else {}
            match = {
                "symbol": symbol,
                "description": row.get("description"),
                "price": round(current_price, 2),
                "change": round(day_change, 2),
                "relative_volume": relvol["relative_volume"],
                "today_volume": relvol["today_volume"],
                "average_volume": relvol["average_volume"],
                "headline": latest_news.get("headline"),
                "news_url": latest_news.get("url"),
                "matched_at": datetime.utcnow().isoformat() + "Z",
            }
            new_matches.append(match)

    existing = {match["symbol"]: match for match in MATCHES}
    for match in new_matches:
        existing[match["symbol"]] = match
    MATCHES = list(existing.values())

    scanned_total = min(start + limit, len(UNIVERSE))
    SCAN_STATUS.update({
        "running": False,
        "total_symbols": len(UNIVERSE),
        "symbols_scanned": scanned_total,
        "matches_found": len(MATCHES),
        "last_scan_finished": datetime.utcnow().isoformat() + "Z",
        "message": f"Scanned symbols {start + 1}-{scanned_total} of {len(UNIVERSE)}.",
    })

    return {
        "status": "ok",
        "batch_start": start,
        "batch_limit": limit,
        "scanned_this_batch": len(batch),
        "next_start": scanned_total if scanned_total < len(UNIVERSE) else None,
        "new_matches": new_matches,
        "matches_found_total": len(MATCHES),
        "debug_sample": inspected[:10],
    }


@app.get("/scan/status")
def scan_status():
    return SCAN_STATUS


@app.get("/matches")
def get_matches():
    return sorted(MATCHES, key=lambda item: item.get("change", 0), reverse=True)


@app.get("/candles/{symbol}")
def candles(symbol: str, resolution: str = Query("5"), days: int = Query(5)):
    data = get_candle_data(symbol.upper(), resolution, days)
    if data.get("s") != "ok":
        return []
    return [
        {
            "time": data["t"][i],
            "open": data["o"][i],
            "high": data["h"][i],
            "low": data["l"][i],
            "close": data["c"][i],
            "volume": data["v"][i],
        }
        for i in range(len(data.get("t", [])))
    ]


@app.get("/news/{symbol}")
def news(symbol: str):
    return get_today_news(symbol.upper())
