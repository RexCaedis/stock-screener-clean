from fastapi import FastAPI
import os
import requests

app = FastAPI()

API_KEY = os.getenv("FINNHUB_API_KEY")

@app.get("/")
def root():
    return {"status": "running"}

@app.get("/debug/{symbol}")
def debug(symbol: str):
    if not API_KEY:
        return {"error": "API KEY NOT FOUND"}

    r = requests.get(
        "https://finnhub.io/api/v1/quote",
        params={"symbol": symbol, "token": API_KEY}
    )
    return r.json()

@app.get("/stocks")
def stocks():
    symbols = ["AAPL","TSLA","NVDA","AMD","PLTR"]

    results = []

    for s in symbols:
        r = requests.get(
            "https://finnhub.io/api/v1/quote",
            params={"symbol": s, "token": API_KEY}
        ).json()

        if r.get("c"):
            results.append({
                "symbol": s,
                "price": r["c"],
                "change": ((r["c"] - r["pc"]) / r["pc"]) * 100 if r["pc"] else 0
            })

    return results
