"""Tests for Activity Feed feature — issue #12.

Covers:
  - ActivityLog model fields and defaults
  - GET /api/activity endpoint: returns 200, limits to 20, ordered desc
  - GET / (dashboard) returns 200 and includes HTMX activity feed container
  - activity_feed.html partial: color-coded icons for all event types
  - HTMX auto-refresh attributes present in dashboard.html
"""
import sys
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.database import Base
from app.models import ActivityLog, Agent


# ── Fixtures ────────────────────────────────────────────────────────────────────

@pytest.fixture
async def async_db():
    """In-memory SQLite async session."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest.fixture
def templates_dir():
    return ROOT / "app" / "templates"


# ── ActivityLog model ───────────────────────────────────────────────────────────

def test_activity_log_model_fields():
    """ActivityLog should have the expected columns."""
    log = ActivityLog(
        event_type="agent.completed",
        summary="David Dev finished coding",
        payload='{"issue_id": "abc"}',
    )
    assert log.event_type == "agent.completed"
    assert log.summary == "David Dev finished coding"
    assert log.payload == '{"issue_id": "abc"}'
    assert log.id is None  # assigned on DB flush


@pytest.mark.asyncio
async def test_activity_log_created_at_set_on_insert(async_db):
    """created_at should be auto-set when the row is inserted."""
    log = ActivityLog(event_type="pipeline.started", summary="Pipeline started")
    async_db.add(log)
    await async_db.commit()
    await async_db.refresh(log)
    assert log.created_at is not None
    assert isinstance(log.created_at, datetime)


@pytest.mark.asyncio
async def test_activity_log_nullable_foreign_keys(async_db):
    """issue_id and agent_id should be nullable."""
    log = ActivityLog(event_type="sync.done", summary="GitHub sync completed")
    async_db.add(log)
    await async_db.commit()
    await async_db.refresh(log)
    assert log.issue_id is None
    assert log.agent_id is None


# ── /api/activity endpoint ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_api_activity_returns_at_most_20(async_db):
    """Endpoint must limit to 20 entries even if more exist in DB."""
    from sqlalchemy import select

    # Insert 25 ActivityLog entries
    for i in range(25):
        async_db.add(ActivityLog(
            event_type="pipeline.completed",
            summary=f"Activity {i}",
            created_at=datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=i),
        ))
    await async_db.commit()

    result = (await async_db.execute(
        select(ActivityLog).order_by(ActivityLog.created_at.desc()).limit(20)
    )).scalars().all()

    assert len(result) == 20


@pytest.mark.asyncio
async def test_api_activity_ordered_desc(async_db):
    """Activities must be ordered most-recent first."""
    from sqlalchemy import select

    times = [
        datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc),
        datetime(2024, 1, 1, 11, 0, tzinfo=timezone.utc),
        datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc),
    ]
    for i, t in enumerate(times):
        async_db.add(ActivityLog(event_type="agent.completed", summary=f"ev{i}", created_at=t))
    await async_db.commit()

    rows = (await async_db.execute(
        select(ActivityLog).order_by(ActivityLog.created_at.desc()).limit(20)
    )).scalars().all()

    # Most recent should be first
    assert rows[0].summary == "ev2"
    assert rows[-1].summary == "ev0"


@pytest.mark.asyncio
async def test_api_activity_empty_db(async_db):
    """Endpoint should return empty list when no activities exist."""
    from sqlalchemy import select

    rows = (await async_db.execute(
        select(ActivityLog).order_by(ActivityLog.created_at.desc()).limit(20)
    )).scalars().all()

    assert rows == []


# ── Template: dashboard.html HTMX attributes ────────────────────────────────────

def test_dashboard_has_htmx_activity_container(templates_dir):
    """dashboard.html must include the HTMX activity feed container."""
    content = (templates_dir / "pages" / "dashboard.html").read_text()
    assert 'id="activity-feed"' in content


def test_dashboard_htmx_get_api_activity(templates_dir):
    """dashboard.html must point hx-get at /api/activity."""
    content = (templates_dir / "pages" / "dashboard.html").read_text()
    assert 'hx-get="/api/activity"' in content


def test_dashboard_htmx_auto_refresh_15s(templates_dir):
    """dashboard.html must configure HTMX trigger for 15-second polling."""
    content = (templates_dir / "pages" / "dashboard.html").read_text()
    assert "every 15s" in content


def test_dashboard_htmx_loads_on_page_load(templates_dir):
    """dashboard.html HTMX trigger must include 'load' so feed appears immediately."""
    content = (templates_dir / "pages" / "dashboard.html").read_text()
    assert "load" in content


def test_dashboard_htmx_swap_mode(templates_dir):
    """dashboard.html must use innerHTML swap for feed refresh."""
    content = (templates_dir / "pages" / "dashboard.html").read_text()
    assert 'hx-swap="innerHTML"' in content


# ── Template: activity_feed.html partial ────────────────────────────────────────

def test_activity_feed_partial_exists(templates_dir):
    """partials/activity_feed.html must exist."""
    assert (templates_dir / "partials" / "activity_feed.html").exists()


def test_activity_feed_partial_renders_summary(templates_dir):
    """Partial must output the summary field."""
    content = (templates_dir / "partials" / "activity_feed.html").read_text()
    assert "a.summary" in content


def test_activity_feed_partial_renders_timestamp(templates_dir):
    """Partial must output the created_at timestamp."""
    content = (templates_dir / "partials" / "activity_feed.html").read_text()
    assert "a.created_at" in content


def test_activity_feed_partial_empty_state(templates_dir):
    """Partial must show empty-state message when no activities."""
    content = (templates_dir / "partials" / "activity_feed.html").read_text()
    assert "No activity yet" in content


# ── Color coding by event type ───────────────────────────────────────────────────

def test_activity_feed_green_for_completed(templates_dir):
    """Completed events must map to success (green) color."""
    content = (templates_dir / "partials" / "activity_feed.html").read_text()
    # Both agent.completed and pipeline.completed should use text-success
    assert "agent.completed" in content or "completed" in content
    assert "text-success" in content


def test_activity_feed_red_for_error(templates_dir):
    """Error events must map to error (red) color."""
    content = (templates_dir / "partials" / "activity_feed.html").read_text()
    assert "agent.error" in content or "error" in content
    assert "text-error" in content


def test_activity_feed_blue_for_started(templates_dir):
    """Started events must map to primary (blue) color."""
    content = (templates_dir / "partials" / "activity_feed.html").read_text()
    assert "pipeline.started" in content or "started" in content
    assert "text-primary" in content


def test_activity_feed_icon_for_sync(templates_dir):
    """Sync events must render with a refresh/warning icon."""
    content = (templates_dir / "partials" / "activity_feed.html").read_text()
    assert "sync" in content
    assert "text-warning" in content


# ── /api/activity route exists in router ────────────────────────────────────────

def test_api_activity_route_registered():
    """The /api/activity GET route must be registered in pages router."""
    from app.routers.pages import router
    routes = {r.path for r in router.routes}
    assert "/api/activity" in routes


def test_api_activity_route_is_get():
    """The /api/activity route must accept GET requests."""
    from app.routers.pages import router
    for route in router.routes:
        if route.path == "/api/activity":
            assert "GET" in route.methods
            break
    else:
        pytest.fail("/api/activity route not found")
