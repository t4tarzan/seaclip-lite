"""Scheduler API — manage repo sync schedules."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import ScheduleConfig
from ..services.scheduler import run_sync_now

router = APIRouter(prefix="/api/scheduler")


@router.get("")
async def list_schedules(request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ScheduleConfig).order_by(ScheduleConfig.created_at))
    configs = result.scalars().all()
    return request.app.state.templates.TemplateResponse("partials/scheduler_list.html", {
        "request": request, "configs": configs,
    })


@router.post("/add")
async def add_schedule(
    request: Request,
    repo: str = Form(...),
    interval: int = Form(15),
    target_column: str = Form("backlog"),
    auto_pipeline: int = Form(0),
    pipeline_mode: str = Form("manual"),
    ai_mode: str = Form("claude"),
    db: AsyncSession = Depends(get_db),
):
    # Check if already exists
    result = await db.execute(select(ScheduleConfig).where(ScheduleConfig.repo == repo))
    existing = result.scalar_one_or_none()
    if existing:
        existing.interval_minutes = interval
        existing.target_column = target_column
        existing.auto_pipeline = auto_pipeline
        existing.pipeline_mode = pipeline_mode
        existing.ai_mode = ai_mode
        existing.enabled = 1
        existing.updated_at = datetime.now(timezone.utc)
    else:
        config = ScheduleConfig(
            repo=repo,
            enabled=1,
            interval_minutes=interval,
            target_column=target_column,
            auto_pipeline=auto_pipeline,
            pipeline_mode=pipeline_mode,
            ai_mode=ai_mode,
        )
        db.add(config)
    await db.commit()

    result = await db.execute(select(ScheduleConfig).order_by(ScheduleConfig.created_at))
    configs = result.scalars().all()
    return request.app.state.templates.TemplateResponse("partials/scheduler_list.html", {
        "request": request, "configs": configs,
    })


@router.post("/{config_id}/toggle")
async def toggle_schedule(
    request: Request,
    config_id: int,
    db: AsyncSession = Depends(get_db),
):
    config = await db.get(ScheduleConfig, config_id)
    if not config:
        return HTMLResponse("Not found", status_code=404)
    config.enabled = 0 if config.enabled else 1
    config.updated_at = datetime.now(timezone.utc)
    await db.commit()

    result = await db.execute(select(ScheduleConfig).order_by(ScheduleConfig.created_at))
    configs = result.scalars().all()
    return request.app.state.templates.TemplateResponse("partials/scheduler_list.html", {
        "request": request, "configs": configs,
    })


@router.post("/{config_id}/sync")
async def sync_now(
    request: Request,
    config_id: int,
    db: AsyncSession = Depends(get_db),
):
    config = await db.get(ScheduleConfig, config_id)
    if not config:
        return HTMLResponse("Not found", status_code=404)
    count = await run_sync_now(config.repo)

    result = await db.execute(select(ScheduleConfig).order_by(ScheduleConfig.created_at))
    configs = result.scalars().all()
    return request.app.state.templates.TemplateResponse("partials/scheduler_list.html", {
        "request": request, "configs": configs, "flash": f"Synced {count} new issues",
    })


@router.post("/{config_id}/delete")
async def delete_schedule(
    request: Request,
    config_id: int,
    db: AsyncSession = Depends(get_db),
):
    config = await db.get(ScheduleConfig, config_id)
    if config:
        await db.delete(config)
        await db.commit()

    result = await db.execute(select(ScheduleConfig).order_by(ScheduleConfig.created_at))
    configs = result.scalars().all()
    return request.app.state.templates.TemplateResponse("partials/scheduler_list.html", {
        "request": request, "configs": configs,
    })
