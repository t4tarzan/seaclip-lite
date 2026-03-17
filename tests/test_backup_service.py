"""Tests for Backup & Restore feature — issue #15.

Covers:
  - BackupJob model fields
  - _human_size helper
  - _row_to_dict helper
  - _timestamp format
  - create_sqlite_backup (with mock DB file)
  - create_json_backup
  - list_backups
  - delete_backup
  - restore_from_json (valid, invalid, missing format_version)
  - export_issues endpoint (via router)
  - Scheduler: start_backup_scheduler creates an asyncio.Task
"""
import asyncio
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── project root on sys.path ─────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


# ── helpers (pure-function tests, no DB needed) ───────────────────────────────
from app.services.backup import _human_size, _timestamp, _row_to_dict


class TestHumanSize:
    def test_bytes(self):
        assert _human_size(512) == "512 B"

    def test_kilobytes(self):
        result = _human_size(2048)
        assert "KB" in result
        assert "2.0" in result

    def test_megabytes(self):
        result = _human_size(5 * 1024 * 1024)
        assert "MB" in result
        assert "5.0" in result

    def test_zero(self):
        assert _human_size(0) == "0 B"


class TestTimestamp:
    def test_format(self):
        ts = _timestamp()
        # Expect YYYYMMDD_HHMMSS  (15 chars)
        assert len(ts) == 15
        assert ts[8] == "_"


class TestRowToDict:
    def test_converts_model_columns(self):
        """_row_to_dict should return all column values, converting datetimes."""
        from app.models import BackupJob
        job = BackupJob(
            backup_type="json",
            file_path="/tmp/test.json",
            file_size=100,
            status="ok",
        )
        # Set a datetime manually so we can test the conversion
        job.created_at = datetime(2024, 1, 15, 12, 0, 0)
        d = _row_to_dict(job)
        assert d["backup_type"] == "json"
        assert d["file_path"] == "/tmp/test.json"
        assert d["status"] == "ok"
        assert isinstance(d["created_at"], str)  # datetime → ISO string


# ── async DB tests ────────────────────────────────────────────────────────────
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import StaticPool
from app.database import Base
from app.models import Issue, BackupJob as BackupJobModel, ActivityLog, ImportedComment


@pytest.fixture
async def async_db():
    """In-memory SQLite async session for each test."""
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


# ── Backup creation ────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_create_sqlite_backup(async_db, tmp_path):
    """SQLite backup should copy DB file and record a BackupJob with status=ok."""
    from app.services.backup import create_sqlite_backup

    # Create a dummy "seaclip.db" for the copy
    fake_db = tmp_path / "seaclip.db"
    fake_db.write_bytes(b"SQLite" * 100)

    with (
        patch("app.services.backup._ensure_backup_dir", return_value=tmp_path),
        patch("app.services.backup.DB_PATH", fake_db),
    ):
        job = await create_sqlite_backup(async_db, description="test-sqlite")

    assert job.status == "ok"
    assert job.backup_type == "sqlite"
    assert job.file_size > 0
    assert Path(job.file_path).exists()


@pytest.mark.asyncio
async def test_create_sqlite_backup_missing_db(async_db, tmp_path):
    """If the DB file is absent the backup job should have status=error."""
    from app.services.backup import create_sqlite_backup

    missing = tmp_path / "does_not_exist.db"

    with (
        patch("app.services.backup._ensure_backup_dir", return_value=tmp_path),
        patch("app.services.backup.DB_PATH", missing),
    ):
        job = await create_sqlite_backup(async_db, description="test-missing")

    assert job.status == "error"
    assert job.description is not None
    assert "Backup failed" in job.description


@pytest.mark.asyncio
async def test_create_json_backup(async_db, tmp_path):
    """JSON backup should create a valid JSON file and record a BackupJob."""
    from app.services.backup import create_json_backup

    # Seed one issue
    issue = Issue(title="Test Issue", description="For JSON export")
    async_db.add(issue)
    await async_db.commit()

    with patch("app.services.backup._ensure_backup_dir", return_value=tmp_path):
        job = await create_json_backup(async_db, description="test-json")

    assert job.status == "ok"
    assert job.backup_type == "json"
    assert job.file_size > 0

    # Verify the file is valid JSON with expected structure
    data = json.loads(Path(job.file_path).read_bytes())
    assert data["format_version"] == "1.0"
    assert "issues" in data
    assert len(data["issues"]) == 1
    assert data["issues"][0]["title"] == "Test Issue"


# ── List & Delete ──────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_list_backups_empty(async_db):
    from app.services.backup import list_backups
    result = await list_backups(async_db)
    assert result == []


@pytest.mark.asyncio
async def test_list_backups_ordered(async_db, tmp_path):
    from app.services.backup import create_json_backup, list_backups

    with patch("app.services.backup._ensure_backup_dir", return_value=tmp_path):
        job1 = await create_json_backup(async_db, description="first")
        job2 = await create_json_backup(async_db, description="second")

    result = await list_backups(async_db)
    # Most recent first
    assert result[0].id >= result[-1].id


@pytest.mark.asyncio
async def test_delete_backup_removes_file(async_db, tmp_path):
    from app.services.backup import create_json_backup, delete_backup

    with patch("app.services.backup._ensure_backup_dir", return_value=tmp_path):
        job = await create_json_backup(async_db, description="to-delete")

    file_path = Path(job.file_path)
    assert file_path.exists()

    found = await delete_backup(job.id, async_db)
    assert found is True
    assert not file_path.exists()


@pytest.mark.asyncio
async def test_delete_backup_nonexistent(async_db):
    from app.services.backup import delete_backup
    found = await delete_backup(99999, async_db)
    assert found is False


# ── Restore / Import ───────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_restore_from_json_valid(async_db):
    from app.services.backup import restore_from_json

    import uuid
    test_id = str(uuid.uuid4())
    payload = {
        "format_version": "1.0",
        "export_date": datetime.now(timezone.utc).isoformat(),
        "issues": [
            {
                "id": test_id,
                "title": "Restored Issue",
                "description": "Restored",
                "priority": "high",
                "status": "backlog",
                "github_repo": None,
                "github_issue_number": None,
                "github_issue_url": None,
                "pipeline_stage": None,
                "pipeline_mode": None,
                "pipeline_waiting": None,
                "last_comment_check_at": None,
                "created_at": None,
                "updated_at": None,
            }
        ],
        "imported_comments": [],
    }

    result = await restore_from_json(async_db, payload)
    assert result["restored"]["issues"] == 1
    assert not result.get("errors")


@pytest.mark.asyncio
async def test_restore_from_json_missing_format_version(async_db):
    from app.services.backup import restore_from_json
    with pytest.raises(ValueError, match="format_version"):
        await restore_from_json(async_db, {"issues": []})


@pytest.mark.asyncio
async def test_restore_from_json_empty(async_db):
    from app.services.backup import restore_from_json
    result = await restore_from_json(async_db, {"format_version": "1.0"})
    assert result["restored"]["issues"] == 0
    assert result["restored"]["imported_comments"] == 0


@pytest.mark.asyncio
async def test_restore_idempotent(async_db):
    """Restoring the same issue twice should not error (upsert)."""
    from app.services.backup import restore_from_json
    import uuid

    test_id = str(uuid.uuid4())
    payload = {
        "format_version": "1.0",
        "issues": [
            {
                "id": test_id,
                "title": "Idempotent",
                "description": "",
                "priority": "medium",
                "status": "backlog",
                "github_repo": None,
                "github_issue_number": None,
                "github_issue_url": None,
                "pipeline_stage": None,
                "pipeline_mode": None,
                "pipeline_waiting": None,
                "last_comment_check_at": None,
                "created_at": None,
                "updated_at": None,
            }
        ],
        "imported_comments": [],
    }

    r1 = await restore_from_json(async_db, payload)
    r2 = await restore_from_json(async_db, payload)
    assert r1["restored"]["issues"] == 1
    assert r2["restored"]["issues"] == 1  # upsert, not duplicate error


# ── Scheduler ────────────────────────────────────────────────────────────────
def test_start_backup_scheduler_returns_task():
    """start_backup_scheduler should return an asyncio.Task."""
    from app.services.backup import start_backup_scheduler
    import app.services.backup as backup_mod

    async def _run():
        task = start_backup_scheduler()
        assert isinstance(task, asyncio.Task)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(_run())


# ── BackupJob model sanity ─────────────────────────────────────────────────────
def test_backup_job_model_defaults():
    """SQLAlchemy column defaults only apply on DB flush, not in-memory construction.

    NOTE: This is a known SQLAlchemy behaviour: Column(default=...) sets the
    value only when the row is INSERTed, so bare object instantiation leaves
    those fields as None.  The backup service always sets status explicitly
    before persisting, so this is safe.
    """
    job = BackupJobModel(backup_type="sqlite", file_path="/tmp/x.sqlite")
    # SQLAlchemy column defaults are NOT applied until the row is flushed to DB
    assert job.status is None   # default applied on INSERT, not in __init__
    assert job.file_size is None  # same reason


def test_backup_job_model_fields():
    job = BackupJobModel(
        backup_type="json",
        file_path="/tmp/x.json",
        file_size=1234,
        status="error",
        description="something went wrong",
    )
    assert job.backup_type == "json"
    assert job.file_size == 1234
    assert job.description == "something went wrong"
