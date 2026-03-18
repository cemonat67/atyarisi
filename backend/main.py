from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from routers import races, horses, predictions, scraper, agent as agent_router
from models.database import init_db
from orchestrator import create_scheduler, ws_clients, state
from datetime import date
import logging
import os

log = logging.getLogger(__name__)
app = FastAPI(title="GALOPUM API", version="1.0.0")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(races.router,         prefix="/api/races",       tags=["Races"])
app.include_router(horses.router,        prefix="/api/horses",      tags=["Horses"])
app.include_router(predictions.router,   prefix="/api/predictions", tags=["Predictions"])
app.include_router(scraper.router,       prefix="/api/scraper",     tags=["Scraper"])
app.include_router(agent_router.router,  prefix="/api/agent",       tags=["Agent"])

static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/")
    def serve_frontend():
        return FileResponse(os.path.join(static_dir, "index.html"))

@app.get("/api/health")
def health():
    return {"status": "ok", "version": "1.0.0", "date": date.today().isoformat()}

@app.get("/api/state")
def get_state():
    return state

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    ws_clients.add(ws)
    try:
        while True:
            await ws.receive_text()
    except:
        ws_clients.discard(ws)

@app.on_event("startup")
async def startup():
    init_db()
    orc = create_scheduler()
    orc.start()
    log.info("GALOPUM başlatıldı")

@app.on_event("shutdown")
async def shutdown():
    pass

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
