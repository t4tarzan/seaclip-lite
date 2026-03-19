"""Issue CRUD + HTMX partials."""
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import Issue

router = APIRouter(prefix="/api/issues")

VALID_PRIORITIES = {"low", "medium", "high", "urgent"}
VALID_STATUSES = {"backlog", "todo", "in_progress", "in_review", "done"}
_REPO_RE = re.compile(r"^[\w.\-]+/[\w.\-]+$")


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


@router.get("/{issue_id}/header")
async def issue_header(request: Request, issue_id: str, db: AsyncSession = Depends(get_db)):
    issue = await db.get(Issue, issue_id)
    if not issue:
        return HTMLResponse("Not found", status_code=404)
    return request.app.state.templates.TemplateResponse("partials/issue_header.html", {
        "request": request, "issue": issue,
    })


@router.get("/{issue_id}/edit")
async def issue_edit_form(request: Request, issue_id: str, db: AsyncSession = Depends(get_db)):
    issue = await db.get(Issue, issue_id)
    if not issue:
        return HTMLResponse("Not found", status_code=404)
    return request.app.state.templates.TemplateResponse("partials/issue_edit_form.html", {
        "request": request, "issue": issue,
    })


@router.put("/{issue_id}")
async def update_issue(
    request: Request,
    issue_id: str,
    title: str = Form(...),
    description: str = Form(""),
    priority: str = Form("medium"),
    status: str = Form("backlog"),
    github_repo: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    issue = await db.get(Issue, issue_id)
    if not issue:
        return HTMLResponse("Not found", status_code=404)

    title = title.strip()
    if not title:
        return HTMLResponse("Title is required", status_code=422)
    if priority not in VALID_PRIORITIES:
        return HTMLResponse(f"Invalid priority: {priority}", status_code=422)
    if status not in VALID_STATUSES:
        return HTMLResponse(f"Invalid status: {status}", status_code=422)
    github_repo = github_repo.strip()
    if github_repo and not _REPO_RE.match(github_repo):
        return HTMLResponse("Invalid repo format — use owner/repo", status_code=422)

    issue.title = title
    issue.description = description.strip()
    issue.priority = priority
    issue.status = status
    issue.github_repo = github_repo or None
    issue.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(issue)

    return request.app.state.templates.TemplateResponse("partials/issue_header.html", {
        "request": request, "issue": issue,
    })


@router.delete("/{issue_id}")
async def delete_issue(issue_id: str, db: AsyncSession = Depends(get_db)):
    issue = await db.get(Issue, issue_id)
    if issue:
        await db.delete(issue)
        await db.commit()
    return HTMLResponse(status_code=200)
