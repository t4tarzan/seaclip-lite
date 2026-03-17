"""Backup service — SQLite file copy, JSON export/import, scheduled daily backups."""
import asyncio
import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import async_session
from ..models import (
    ActivityLog,
    BackupJob,
    ImportedComment,
    Issue,
)

logger = logging.getLogger("seaclip.backup")

_backup_task: asyncio.Task | None = None

# Path to the SQLite database file (relative to project root)
DB_PATH = Path("seaclip.db")


def _ensure_backup_dir() -> Path:
    """Ensure the backup directory exists and return its Path."""
    backup_dir = Path(settings.backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _row_to_dict(row) -> dict:
    """Convert a SQLAlchemy model instance to a JSON-serialisable dict."""
    d = {}
    for col in row.__table__.columns:
        val = getattr(row, col.name)
        if isinstance(val, datetime):
            val = val.isoformat()
        d[col.name] = val
    return d


def _human_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"


async def create_sqlite_backup(db: AsyncSession, description: str = "") -> BackupJob:
    """Create a SQLite file copy backup via WAL checkpoint + shutil.copy2."""
    backup_dir = _ensure_backup_dir()
    dest_path = backup_dir / f"{_timestamp()}_backup.sqlite"
    job = BackupJob(backup_type="sqlite", file_path=str(dest_path), status="error", description=description or None)

    try:
        # Checkpoint WAL to flush pending writes into the main db file
        await db.execute(text("PRAGMA wal_checkpoint(RESTART)"))

        # Copy in executor to avoid blocking the event loop
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, shutil.copy2, str(DB_PATH), str(dest_path))

        file_size = dest_path.stat().st_size
        job.file_size = file_size
        job.status = "ok"
        logger.info("SQLite backup created: %s (%s)", dest_path.name, _human_size(file_size))
    except OSError as exc:
        job.status = "error"
        job.description = f"Backup failed: {exc}"
        logger.error("SQLite backup failed: %s", exc)

    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job


async def create_json_backup(db: AsyncSession, description: str = "") -> BackupJob:
    """Export key tables to a JSON file backup."""
    backup_dir = _ensure_backup_dir()
    dest_path = backup_dir / f"{_timestamp()}_backup.json"
    job = BackupJob(backup_type="json", file_path=str(dest_path), status="error", description=description or None)

    try:
        issues = (await db.execute(select(Issue))).scalars().all()
        comments = (await db.execute(select(ImportedComment))).scalars().all()
        activity = (await db.execute(select(ActivityLog))).scalars().all()

        # Try to import optional models that may not exist on older branches
        try:
            from ..models import DevTask, ScheduleConfig
            dev_tasks = (await db.execute(select(DevTask))).scalars().all()
            schedule_configs = (await db.execute(select(ScheduleConfig))).scalars().all()
        except (ImportError, Exception):
            dev_tasks = []
            schedule_configs = []

        payload = {
            "format_version": "1.0",
            "export_date": datetime.now(timezone.utc).isoformat(),
            "issues": [_row_to_dict(r) for r in issues],
            "imported_comments": [_row_to_dict(r) for r in comments],
            "activity_log": [_row_to_dict(r) for r in activity],
            "dev_tasks": [_row_to_dict(r) for r in dev_tasks],
            "schedule_configs": [_row_to_dict(r) for r in schedule_configs],
        }

        json_bytes = json.dumps(payload, indent=2, default=str).encode("utf-8")

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, dest_path.write_bytes, json_bytes)

        file_size = len(json_bytes)
        job.file_size = file_size
        job.status = "ok"
        logger.info("JSON backup created: %s (%s)", dest_path.name, _human_size(file_size))
    except OSError as exc:
        job.status = "error"
        job.description = f"Backup failed: {exc}"
        logger.error("JSON backup failed: %s", exc)

    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job


async def restore_from_json(db: AsyncSession, json_data: dict) -> dict:
    """Upsert records from a JSON backup dict. Returns counts per table."""
    if "format_version" not in json_data:
        raise ValueError("Invalid backup file: missing format_version")

    counts: dict[str, int] = {}
    errors: dict[str, int] = {}

    # Issues
    issue_count = 0
    issue_errors = 0
    for row in json_data.get("issues", []):
        try:
            # Normalise datetime strings back to datetime objects
            for dt_field in ("created_at", "updated_at"):
                if row.get(dt_field):
                    try:
                        row[dt_field] = datetime.fromisoformat(row[dt_field])
                    except (ValueError, TypeError):
                        row[dt_field] = None
            await db.merge(Issue(**{k: v for k, v in row.items() if hasattr(Issue, k)}))
            issue_count += 1
        except Exception as exc:
            logger.warning("Issue merge failed: %s", exc)
            issue_errors += 1
    counts["issues"] = issue_count
    if issue_errors:
        errors["issues"] = issue_errors

    # Imported comments
    comment_count = 0
    comment_errors = 0
    for row in json_data.get("imported_comments", []):
        try:
            for dt_field in ("created_at",):
                if row.get(dt_field):
                    try:
                        row[dt_field] = datetime.fromisoformat(row[dt_field])
                    except (ValueError, TypeError):
                        row[dt_field] = None
            await db.merge(ImportedComment(**{k: v for k, v in row.items() if hasattr(ImportedComment, k)}))
            comment_count += 1
        except Exception as exc:
            logger.warning("Comment merge failed: %s", exc)
            comment_errors += 1
    counts["imported_comments"] = comment_count
    if comment_errors:
        errors["imported_comments"] = comment_errors

    await db.commit()
    return {"restored": counts, "errors": errors}


async def list_backups(db: AsyncSession) -> list[BackupJob]:
    """Return all backup jobs ordered by most recent first."""
    result = await db.execute(select(BackupJob).order_by(BackupJob.created_at.desc()))
    return result.scalars().all()


async def delete_backup(backup_id: int, db: AsyncSession) -> bool:
    """Delete a backup job record and its file from disk."""
    job = await db.get(BackupJob, backup_id)
    if not job:
        return False
    Path(job.file_path).unlink(missing_ok=True)
    await db.delete(job)
    await db.commit()
    return True


async def _backup_scheduler_loop():
    """Daily backup scheduler — checks every hour, runs auto backup every 24h."""
    logger.info("Backup scheduler started")
    while True:
        try:
            async with async_session() as db:
                # Find the most recent auto backup
                result = await db.execute(
                    select(BackupJob)
                    .where(BackupJob.description == "auto")
                    .order_by(BackupJob.created_at.desc())
                    .limit(1)
                )
                last_auto = result.scalar_one_or_none()
                now = datetime.now(timezone.utc)
                should_run = True
                if last_auto and last_auto.created_at:
                    last_ts = last_auto.created_at
                    # Make timezone-aware if needed
                    if last_ts.tzinfo is None:
                        last_ts = last_ts.replace(tzinfo=timezone.utc)
                    elapsed = (now - last_ts).total_seconds()
                    if elapsed < 86400:  # 24 hours
                        should_run = False

                if should_run:
                    logger.info("Running scheduled daily backups")
                    try:
                        await create_sqlite_backup(db, description="auto")
                    except Exception as exc:
                        logger.error("Auto SQLite backup failed: %s", exc)
                    try:
                        await create_json_backup(db, description="auto")
                    except Exception as exc:
                        logger.error("Auto JSON backup failed: %s", exc)
        except Exception as exc:
            logger.error("Backup scheduler loop error: %s", exc)

        await asyncio.sleep(3600)  # check every hour


def start_backup_scheduler() -> asyncio.Task:
    """Start the backup background scheduler task."""
    global _backup_task
    _backup_task = asyncio.create_task(_backup_scheduler_loop())
    return _backup_task
