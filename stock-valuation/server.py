"""Stock valuation web app. Run: python server.py  → http://localhost:8000"""

import base64
import os
import secrets
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

import data_sources
import db

STATIC = Path(__file__).parent / "static"
# Optional: set APP_PASSWORD to require a login (any user name) for the whole site.
APP_PASSWORD = os.environ.get("APP_PASSWORD", "")

app = FastAPI(title="Оценка на акции")
db.init()


@app.middleware("http")
async def password_gate(request: Request, call_next):
    if APP_PASSWORD:
        auth = request.headers.get("authorization", "")
        given = ""
        if auth.lower().startswith("basic "):
            try:
                given = base64.b64decode(auth[6:]).decode().partition(":")[2]
            except ValueError:
                pass
        if not secrets.compare_digest(given.encode(), APP_PASSWORD.encode()):
            return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="Stock valuation"'})
    return await call_next(request)


@app.get("/api/data/{ticker}")
def data(ticker: str, peers: str = Query("", description="comma-separated peer tickers")):
    if not ticker.replace(".", "").replace("-", "").isalnum() or len(ticker) > 12:
        raise HTTPException(400, "Невалиден тикер")
    peer_list = [p for p in peers.replace(" ", "").split(",") if p] or None
    return data_sources.gather(ticker, peer_list)


@app.get("/api/valuations")
def list_valuations():
    return {"items": db.list_all(), "storage": db.storage_info()}


@app.post("/api/valuations")
def save_valuation(v: dict = Body(...)):
    if not v.get("ticker"):
        raise HTTPException(400, "Липсва тикер")
    return {"id": db.save(v)}


@app.get("/api/valuations/{vid}")
def get_valuation(vid: int):
    v = db.get(vid)
    if not v:
        raise HTTPException(404, "Няма такъв запис")
    return v


@app.delete("/api/valuations/{vid}")
def delete_valuation(vid: int):
    if not db.delete(vid):
        raise HTTPException(404, "Няма такъв запис")
    return {"ok": True}


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", 8000)))
