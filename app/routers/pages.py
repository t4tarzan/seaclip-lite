"""Full-page HTML routes."""
from fastapi import APIRouter, Depends, Request
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import get_db
from ..models import Issue, Agent, ImportedComment, ActivityLog, DevTask

router = APIRouter()


@router.get("/")
async def dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    # Count issues by status
    result = await db.execute(
        select(Issue.status, func.count(Issue.id)).group_by(Issue.status)
    )
    counts = dict(result.all())

    agents = (await db.execute(select(Agent).order_by(Agent.created_at))).scalars().all()

    return request.app.state.templates.TemplateResponse("pages/dashboard.html", {
        "request": request,
        "counts": counts,
        "agents": agents,
        "total": sum(counts.values()),
    })


@router.get("/api/activity")
async def activity_feed(request: Request, db: AsyncSession = Depends(get_db)):
    activities = (await db.execute(
        select(ActivityLog).order_by(ActivityLog.created_at.desc()).limit(20)
    )).scalars().all()
    return request.app.state.templates.TemplateResponse("partials/activity_feed.html", {
        "request": request,
        "activities": activities,
    })


@router.get("/kanban")
async def kanban(request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Issue).order_by(Issue.updated_at.desc()))
    issues = result.scalars().all()

    columns = {
        "backlog": [], "todo": [], "in_progress": [], "in_review": [], "done": [],
    }
    for issue in issues:
        if issue.status in columns:
            columns[issue.status].append(issue)

    from ..services.github import list_org_repos
    repos = await list_org_repos()

    return request.app.state.templates.TemplateResponse("pages/kanban.html", {
        "request": request,
        "columns": columns,
        "repos": repos,
    })


@router.get("/identify")
async def identify(request: Request, db: AsyncSession = Depends(get_db)):
    from ..services.github import list_org_repos
    repos = await list_org_repos()
    return request.app.state.templates.TemplateResponse("pages/identify.html", {
        "request": request,
        "repos": repos,
    })


@router.get("/agents")
async def agents_page(request: Request, db: AsyncSession = Depends(get_db)):
    agents = (await db.execute(select(Agent).order_by(Agent.created_at))).scalars().all()
    return request.app.state.templates.TemplateResponse("pages/agents.html", {
        "request": request,
        "agents": agents,
    })


@router.get("/backup")
async def backup_page(request: Request, db: AsyncSession = Depends(get_db)):
    from ..services.backup import list_backups
    backups = await list_backups(db)
    last_backup = backups[0] if backups else None
    return request.app.state.templates.TemplateResponse("pages/backup.html", {
        "request": request,
        "backups": backups,
        "last_backup": last_backup,
        "backup_dir": settings.backup_dir,
    })


@router.get("/roadmap")
async def roadmap(request: Request, db: AsyncSession = Depends(get_db)):
    tasks = (await db.execute(select(DevTask).order_by(DevTask.priority))).scalars().all()
    stats = {
        "total": len(tasks),
        "planned": sum(1 for t in tasks if t.status == "planned"),
        "in_progress": sum(1 for t in tasks if t.status == "in_progress"),
        "done": sum(1 for t in tasks if t.status == "done"),
    }
    issue_ids = [t.issue_id for t in tasks if t.issue_id]
    issues_map = {}
    if issue_ids:
        result = await db.execute(select(Issue).where(Issue.id.in_(issue_ids)))
        issues_map = {i.id: i for i in result.scalars().all()}

    return request.app.state.templates.TemplateResponse("pages/roadmap.html", {
        "request": request,
        "tasks": tasks,
        "stats": stats,
        "issues_map": issues_map,
    })


@router.get("/api/issues/{issue_id}/comments")
async def issue_comments_partial(request: Request, issue_id: str, db: AsyncSession = Depends(get_db)):
    comments = (await db.execute(
        select(ImportedComment)
        .where(ImportedComment.issue_id == issue_id)
        .order_by(ImportedComment.created_at)
    )).scalars().all()
    return request.app.state.templates.TemplateResponse("partials/comments_list.html", {
        "request": request,
        "comments": comments,
    })


@router.get("/issues/{issue_id}")
async def issue_detail(request: Request, issue_id: str, db: AsyncSession = Depends(get_db)):
    issue = await db.get(Issue, issue_id)
    if not issue:
        return request.app.state.templates.TemplateResponse("pages/dashboard.html", {
            "request": request, "counts": {}, "agents": [], "total": 0,
        })

    comments = (await db.execute(
        select(ImportedComment)
        .where(ImportedComment.issue_id == issue_id)
        .order_by(ImportedComment.created_at)
    )).scalars().all()

    from ..agents.pipeline import STAGE_AGENT_NAME
    return request.app.state.templates.TemplateResponse("pages/issue_detail.html", {
        "request": request,
        "issue": issue,
        "comments": comments,
        "stage_agent_name": STAGE_AGENT_NAME,
    })
