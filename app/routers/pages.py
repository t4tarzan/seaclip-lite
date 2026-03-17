"""Full-page HTML routes."""
from fastapi import APIRouter, Depends, Request
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import Issue, Agent, ImportedComment

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

    return request.app.state.templates.TemplateResponse("pages/kanban.html", {
        "request": request,
        "columns": columns,
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
