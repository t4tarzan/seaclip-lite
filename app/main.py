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
from .models import Agent, BackupJob, DevTask, ScheduleConfig, SEED_AGENTS  # noqa: F401

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


SEED_DEV_TASKS = [
    {"priority": 1, "feature": "Voice Command Interface", "category": "ai", "description": "Voice input/output for hands-free issue creation and pipeline control.", "impact": "high", "effort": "medium"},
    {"priority": 2, "feature": "Shared Folder Sync & File Browser", "category": "infra", "description": "Mount shared folders, expose file browser in UI.", "impact": "high", "effort": "easy"},
    {"priority": 3, "feature": "ChromaDB Knowledge Base Integration", "category": "ai", "description": "Connect to ChromaDB, agents query docs before working.", "impact": "high", "effort": "easy"},
    {"priority": 4, "feature": "Cost & Token Tracking Dashboard", "category": "governance", "description": "Track Claude/Ollama usage, per-agent cost breakdown.", "impact": "high", "effort": "easy"},
    {"priority": 5, "feature": "Activity Feed & Notifications", "category": "ui", "description": "Real-time activity feed on dashboard.", "impact": "high", "effort": "easy"},
    {"priority": 6, "feature": "Multi-Model Adapter System", "category": "ai", "description": "Support multiple LLM backends.", "impact": "high", "effort": "medium"},
    {"priority": 7, "feature": "PR Tracking & Review Dashboard", "category": "integration", "description": "Track PRs created by Matthews.", "impact": "high", "effort": "easy"},
    {"priority": 8, "feature": "Settings Page", "category": "ui", "description": "Central settings page for all configs.", "impact": "medium", "effort": "easy"},
    {"priority": 9, "feature": "Agent Soul Customization", "category": "ai", "description": "UI editor for agent personalities.", "impact": "medium", "effort": "easy"},
    {"priority": 10, "feature": "Issue Templates & Quick Create", "category": "ui", "description": "Pre-defined issue templates.", "impact": "medium", "effort": "easy"},
    {"priority": 11, "feature": "Approval Gates", "category": "governance", "description": "Configurable approval checkpoints between stages.", "impact": "high", "effort": "medium"},
    {"priority": 12, "feature": "Projects & Goals Grouping", "category": "core", "description": "Group issues into projects.", "impact": "medium", "effort": "medium"},
    {"priority": 13, "feature": "Team Member Profiles", "category": "core", "description": "Register dev team members, assign issues.", "impact": "medium", "effort": "medium"},
    {"priority": 14, "feature": "Webhook Receiver", "category": "integration", "description": "Replace polling with webhook ingestion.", "impact": "medium", "effort": "medium"},
    {"priority": 15, "feature": "Agent Run History & Replay", "category": "core", "description": "Store full prompt+response for every run.", "impact": "medium", "effort": "medium"},
    {"priority": 16, "feature": "Local Drive Vector Indexing", "category": "ai", "description": "Index local folders into ChromaDB.", "impact": "high", "effort": "medium"},
    {"priority": 17, "feature": "Dark/Light Theme Toggle", "category": "ui", "description": "Theme switcher.", "impact": "low", "effort": "easy"},
    {"priority": 18, "feature": "Markdown Rendering in Comments", "category": "ui", "description": "Render comments as markdown.", "impact": "medium", "effort": "easy"},
    {"priority": 19, "feature": "Pipeline Visualization", "category": "ui", "description": "Visual pipeline flow diagram.", "impact": "medium", "effort": "medium"},
    {"priority": 20, "feature": "Bulk Issue Import", "category": "core", "description": "Upload CSV/JSON to bulk-create issues.", "impact": "medium", "effort": "easy"},
    {"priority": 21, "feature": "Edge Device Support", "category": "infra", "description": "Register RPi/Jetson as spoke agents.", "impact": "medium", "effort": "hard"},
    {"priority": 22, "feature": "Slack/Teams Integration", "category": "integration", "description": "Post pipeline updates to Slack.", "impact": "medium", "effort": "medium"},
    {"priority": 23, "feature": "Multi-Repo Pipeline", "category": "core", "description": "Pipeline across multiple repos.", "impact": "medium", "effort": "hard"},
    {"priority": 24, "feature": "Custom Agent Creation", "category": "ai", "description": "Create custom agents beyond the 6 defaults.", "impact": "medium", "effort": "hard"},
    {"priority": 25, "feature": "Backup & Restore", "category": "infra", "description": "One-click DB backup.", "impact": "low", "effort": "easy"},
    {"priority": 26, "feature": "Auth & User Roles", "category": "governance", "description": "Basic auth for multi-user access.", "impact": "low", "effort": "medium"},
    {"priority": 27, "feature": "Mobile Responsive Layout", "category": "ui", "description": "Make all pages responsive.", "impact": "low", "effort": "medium"},
    {"priority": 28, "feature": "Hub Federation", "category": "infra", "description": "Connect multiple SeaClip instances.", "impact": "low", "effort": "hard"},
    {"priority": 29, "feature": "CI/CD Pipeline Trigger", "category": "integration", "description": "Trigger CI/CD after Matthews merges.", "impact": "medium", "effort": "medium"},
    {"priority": 30, "feature": "Analytics & Reporting", "category": "governance", "description": "Weekly/monthly reports.", "impact": "low", "effort": "hard"},
]


async def seed_dev_tasks():
    """Seed the development roadmap if empty."""
    async with async_session() as db:
        result = await db.execute(select(DevTask))
        if result.scalars().first() is not None:
            return
        for task_data in SEED_DEV_TASKS:
            db.add(DevTask(**task_data))
        await db.commit()
        logger.info("Seeded %d dev tasks", len(SEED_DEV_TASKS))


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_db()
    await seed_agents()
    await seed_dev_tasks()

    # Ensure backup directory exists
    from .services.backup import _ensure_backup_dir
    _ensure_backup_dir()

    # Start GitHub poller
    from .services.poller import start_poller
    poller_task = asyncio.create_task(start_poller())

    # Start backup scheduler
    from .services.backup import start_backup_scheduler
    backup_task = start_backup_scheduler()

    # Start scheduler
    from .services.scheduler import start_scheduler
    scheduler_task = start_scheduler()

    logger.info("SeaClip Lite started on port %d", settings.port)

    yield

    # Shutdown
    poller_task.cancel()
    backup_task.cancel()
    try:
        await poller_task
    except asyncio.CancelledError:
        pass
    try:
        await backup_task
    except asyncio.CancelledError:
        pass
    scheduler_task.cancel()
    try:
        await scheduler_task
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
from .routers import pages, issues, identify, pipeline, agents, github, backup, roadmap, scheduler  # noqa: E402

app.include_router(pages.router)
app.include_router(issues.router)
app.include_router(identify.router)
app.include_router(pipeline.router)
app.include_router(agents.router)
app.include_router(github.router)
app.include_router(backup.router)
app.include_router(roadmap.router)
app.include_router(scheduler.router)


@app.get("/health")
async def health():
    return {"status": "ok", "app": "seaclip-lite"}
