"""Pipeline control routes."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import Issue
from ..services import github
from ..agents.pipeline import start_pipeline, resume_pipeline, STAGE_AGENT_NAME, stop_pipeline

router = APIRouter(prefix="/api/pipeline")


@router.post("/{issue_id}/sync-github")
async def sync_github(
    request: Request,
    issue_id: str,
    db: AsyncSession = Depends(get_db),
):
    issue = await db.get(Issue, issue_id)
    if not issue or not issue.github_repo:
        return HTMLResponse("Issue has no repo set", status_code=400)

    await github.bootstrap_repo_labels(issue.github_repo)

    body = f"{issue.description or ''}\n\n---\n_SeaClip Lite_"
    gh = await github.create_issue(issue.github_repo, issue.title, body)

    issue.github_issue_number = gh["number"]
    issue.github_issue_url = gh["url"]
    issue.status = "todo"
    issue.updated_at = datetime.now(timezone.utc)
    await db.commit()

    return request.app.state.templates.TemplateResponse("partials/pipeline_panel.html", {
        "request": request, "issue": issue, "stage_agent_name": STAGE_AGENT_NAME,
    })


@router.post("/{issue_id}/start")
async def start(
    request: Request,
    issue_id: str,
    mode: str = Form("auto"),
    db: AsyncSession = Depends(get_db),
):
    issue = await db.get(Issue, issue_id)
    if not issue:
        return HTMLResponse("Not found", status_code=404)

    # Add plan label on GitHub
    if issue.github_repo and issue.github_issue_number:
        await github.add_label(issue.github_repo, issue.github_issue_number, "plan")

    await start_pipeline(issue_id, mode=mode, start_stage="plan")

    await db.refresh(issue)
    return request.app.state.templates.TemplateResponse("partials/pipeline_panel.html", {
        "request": request, "issue": issue, "stage_agent_name": STAGE_AGENT_NAME,
    })


@router.post("/{issue_id}/resume")
async def resume(
    request: Request,
    issue_id: str,
    stage: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    issue = await db.get(Issue, issue_id)
    if not issue:
        return HTMLResponse("Not found", status_code=404)

    await resume_pipeline(issue_id, stage)

    await db.refresh(issue)
    return request.app.state.templates.TemplateResponse("partials/pipeline_panel.html", {
        "request": request, "issue": issue, "stage_agent_name": STAGE_AGENT_NAME,
    })


@router.post("/{issue_id}/stop")
async def stop(
    request: Request,
    issue_id: str,
    db: AsyncSession = Depends(get_db),
):
    stopped = stop_pipeline(issue_id)
    issue = await db.get(Issue, issue_id)
    return request.app.state.templates.TemplateResponse("partials/pipeline_panel.html", {
        "request": request, "issue": issue, "stage_agent_name": STAGE_AGENT_NAME,
        "toast": "Pipeline stopped" if stopped else "No running pipeline to stop",
    })


@router.get("/{issue_id}/panel")
async def panel_partial(
    request: Request,
    issue_id: str,
    db: AsyncSession = Depends(get_db),
):
    issue = await db.get(Issue, issue_id)
    if not issue:
        return HTMLResponse("", status_code=404)
    return request.app.state.templates.TemplateResponse("partials/pipeline_panel.html", {
        "request": request, "issue": issue, "stage_agent_name": STAGE_AGENT_NAME,
    })


@router.get("/{issue_id}/status")
async def status(issue_id: str, db: AsyncSession = Depends(get_db)):
    issue = await db.get(Issue, issue_id)
    if not issue:
        return {"error": "Not found"}
    return {
        "stage": issue.pipeline_stage,
        "mode": issue.pipeline_mode,
        "waiting": issue.pipeline_waiting,
        "status": issue.status,
    }
