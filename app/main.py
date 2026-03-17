"""SeaClip Lite — FastAPI + HTMX pipeline dashboard."""
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from .config import settings
from .database import init_db, async_session
from .models import Agent, SEED_AGENTS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("seaclip")


async def seed_agents():
    """Insert the 6 pipeline agents if they don't exist."""
    async with async_session() as db:
        result = await db.execute(select(Agent))
        if result.scalars().first() is not None:
            return
        for agent_data in SEED_AGENTS:
            db.add(Agent(**agent_data))
        await db.commit()
        logger.info("Seeded %d agents", len(SEED_AGENTS))


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_db()
    await seed_agents()

    # Start GitHub poller
    from .services.poller import start_poller
    poller_task = asyncio.create_task(start_poller())
    logger.info("SeaClip Lite started on port %d", settings.port)

    yield

    # Shutdown
    poller_task.cancel()
    try:
        await poller_task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="SeaClip Lite", lifespan=lifespan)

# Templates
templates_dir = Path(__file__).parent / "templates"
app.state.templates = Jinja2Templates(directory=str(templates_dir))

# Static files
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# Routers
from .routers import pages, issues, identify, pipeline, agents, github  # noqa: E402

app.include_router(pages.router)
app.include_router(issues.router)
app.include_router(identify.router)
app.include_router(pipeline.router)
app.include_router(agents.router)
app.include_router(github.router)


@app.get("/health")
async def health():
    return {"status": "ok", "app": "seaclip-lite"}
