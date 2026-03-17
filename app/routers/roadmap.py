"""Roadmap dev task management."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import DevTask, Issue

router = APIRouter(prefix="/api/roadmap")

DEFAULT_REPO = "t4tarzan/seaclip-lite"


@router.post("/{task_id}/status")
async def update_status(
    request: Request,
    task_id: int,
    status: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    task = await db.get(DevTask, task_id)
    if not task:
        return HTMLResponse("Not found", status_code=404)

    if status not in ("planned", "in_progress", "done", "deferred"):
        return HTMLResponse("Invalid status", status_code=400)

    task.status = status
    task.updated_at = datetime.now(timezone.utc)

    # Start → create kanban issue in backlog
    if status == "in_progress" and not task.issue_id:
        issue = Issue(
            title=f"feat: {task.feature}",
            description=task.description or task.feature,
            priority="high" if task.impact == "high" else "medium" if task.impact == "medium" else "low",
            status="backlog",
            github_repo=DEFAULT_REPO,
        )
        db.add(issue)
        await db.flush()  # get the issue.id
        task.issue_id = issue.id

    # Done → stamp completed_at
    if status == "done":
        task.completed_at = datetime.now(timezone.utc)
    elif status in ("planned", "in_progress"):
        task.completed_at = None

    await db.commit()

    # Fetch linked issue for template
    issue = await db.get(Issue, task.issue_id) if task.issue_id else None

    return request.app.state.templates.TemplateResponse("partials/roadmap_row.html", {
        "request": request, "task": task, "issue": issue,
    })
