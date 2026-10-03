"""Stock valuation web app. Run: python server.py  → http://localhost:8000"""

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import data_sources

STATIC = Path(__file__).parent / "static"
app = FastAPI(title="Оценка на акции")


@app.get("/api/data/{ticker}")
def data(ticker: str, peers: str = Query("", description="comma-separated peer tickers")):
    if not ticker.replace(".", "").replace("-", "").isalnum() or len(ticker) > 12:
        raise HTTPException(400, "Невалиден тикер")
    peer_list = [p for p in peers.replace(" ", "").split(",") if p] or None
    return data_sources.gather(ticker, peer_list)


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", 8000)))
