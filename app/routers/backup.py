"""Backup & Restore API router."""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import get_db
from ..models import BackupJob, Issue
from ..services.backup import (
    create_json_backup,
    create_sqlite_backup,
    delete_backup,
    list_backups,
    restore_from_json,
    _row_to_dict,
    _human_size,
)

logger = logging.getLogger("seaclip.backup.router")

router = APIRouter(prefix="/api/backup")


@router.get("")
async def backup_list_partial(request: Request, db: AsyncSession = Depends(get_db)):
    """HTMX partial: list of all backup jobs."""
    backups = await list_backups(db)
    return request.app.state.templates.TemplateResponse("partials/backup_list.html", {
        "request": request,
        "backups": backups,
        "human_size": _human_size,
    })


@router.post("/create")
async def create_backup(
    request: Request,
    fmt: str = Form(..., alias="format"),
    description: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    """Create a new backup (SQLite or JSON)."""
    flash = ""
    if fmt == "sqlite":
        job = await create_sqlite_backup(db, description=description)
        flash = f"SQLite backup created ({_human_size(job.file_size)})" if job.status == "ok" else f"Backup failed: {job.description}"
    elif fmt == "json":
        job = await create_json_backup(db, description=description)
        flash = f"JSON backup created ({_human_size(job.file_size)})" if job.status == "ok" else f"Backup failed: {job.description}"
    else:
        raise HTTPException(status_code=400, detail="Invalid format. Use 'sqlite' or 'json'.")

    backups = await list_backups(db)
    return request.app.state.templates.TemplateResponse("partials/backup_list.html", {
        "request": request,
        "backups": backups,
        "flash": flash,
        "human_size": _human_size,
    })


@router.get("/{backup_id}/download")
async def download_backup(backup_id: int, db: AsyncSession = Depends(get_db)):
    """Download a backup file."""
    job = await db.get(BackupJob, backup_id)
    if not job:
        raise HTTPException(status_code=404, detail="Backup not found")
    file_path = Path(job.file_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Backup file missing from disk")
    return FileResponse(str(file_path), filename=file_path.name)


@router.post("/{backup_id}/delete")
async def delete_backup_endpoint(
    request: Request,
    backup_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Delete a backup job and its file."""
    found = await delete_backup(backup_id, db)
    flash = "Backup deleted." if found else "Backup not found."
    backups = await list_backups(db)
    return request.app.state.templates.TemplateResponse("partials/backup_list.html", {
        "request": request,
        "backups": backups,
        "flash": flash,
        "human_size": _human_size,
    })


@router.post("/import")
async def import_backup(
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Import (merge/upsert) records from a JSON backup file."""
    content = await file.read()
    if len(content) > 50 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 50 MB)")

    try:
        json_data = json.loads(content)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}")

    try:
        result = await restore_from_json(db, json_data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    restored = result.get("restored", {})
    flash = "Imported: " + ", ".join(f"{k}={v}" for k, v in restored.items())
    if result.get("errors"):
        flash += " | Errors: " + ", ".join(f"{k}={v}" for k, v in result["errors"].items())

    backups = await list_backups(db)
    return request.app.state.templates.TemplateResponse("partials/backup_list.html", {
        "request": request,
        "backups": backups,
        "flash": flash,
        "human_size": _human_size,
    })


@router.get("/export/issues")
async def export_issues(db: AsyncSession = Depends(get_db)):
    """Export all issues as a streaming JSON download."""
    issues = (await db.execute(select(Issue))).scalars().all()
    payload = {
        "format_version": "1.0",
        "export_date": datetime.now(timezone.utc).isoformat(),
        "issues": [_row_to_dict(r) for r in issues],
    }
    json_bytes = json.dumps(payload, indent=2, default=str).encode("utf-8")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"issues_export_{timestamp}.json"

    return StreamingResponse(
        iter([json_bytes]),
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
