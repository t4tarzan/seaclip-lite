"""Issue CRUD + HTMX partials."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import Issue

router = APIRouter(prefix="/api/issues")


@router.get("")
async def list_issues(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Issue).order_by(Issue.updated_at.desc()))
    issues = result.scalars().all()
    return [{"id": i.id, "title": i.title, "status": i.status, "priority": i.priority} for i in issues]


@router.post("")
async def create_issue(
    request: Request,
    title: str = Form(...),
    description: str = Form(""),
    priority: str = Form("medium"),
    github_repo: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    issue = Issue(
        title=title,
        description=description,
        priority=priority,
        status="backlog",
        github_repo=github_repo or None,
    )
    db.add(issue)
    await db.commit()
    await db.refresh(issue)

    return request.app.state.templates.TemplateResponse("partials/kanban_card.html", {
        "request": request, "issue": issue,
    })


@router.post("/{issue_id}/move")
async def move_issue(
    request: Request,
    issue_id: str,
    status: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    issue = await db.get(Issue, issue_id)
    if not issue:
        return HTMLResponse("Not found", status_code=404)

    issue.status = status
    issue.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return HTMLResponse(status_code=200)


@router.post("/{issue_id}/status")
async def update_issue_status(
    request: Request,
    issue_id: str,
    status: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    issue = await db.get(Issue, issue_id)
    if not issue:
        return HTMLResponse("Not found", status_code=404)

    issue.status = status
    issue.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(issue)
    return request.app.state.templates.TemplateResponse("partials/kanban_card.html", {
        "request": request, "issue": issue,
    })


@router.delete("/{issue_id}")
async def delete_issue(issue_id: str, db: AsyncSession = Depends(get_db)):
    issue = await db.get(Issue, issue_id)
    if issue:
        await db.delete(issue)
        await db.commit()
    return HTMLResponse(status_code=200)
