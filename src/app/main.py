from fastapi import FastAPI, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import asyncio
from contextlib import asynccontextmanager

from .models.database import init_db
from .models.auth import verify_credentials
from .routers import router
from .services.scheduler import background_task

templates = Jinja2Templates(directory="app/templates")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_db()
    # Start the background polling task
    task = asyncio.create_task(background_task())
    yield
    # Shutdown
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

app = FastAPI(title="Hybrid Parental Control", lifespan=lifespan)

app.include_router(router)

@app.get("/", response_class=HTMLResponse, dependencies=[Depends(verify_credentials)])
async def serve_ui(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})
