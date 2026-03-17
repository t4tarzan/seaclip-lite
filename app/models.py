import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text

from .database import Base


def utcnow():
    return datetime.now(timezone.utc)


def new_id():
    return str(uuid.uuid4())


class Issue(Base):
    __tablename__ = "issues"

    id = Column(String(36), primary_key=True, default=new_id)
    title = Column(String(255), nullable=False)
    description = Column(Text, default="")
    priority = Column(String(20), default="medium")
    status = Column(String(20), default="backlog")
    github_repo = Column(String(255), nullable=True)
    github_issue_number = Column(Integer, nullable=True)
    github_issue_url = Column(String(500), nullable=True)
    pipeline_stage = Column(String(20), nullable=True)
    pipeline_mode = Column(String(10), nullable=True)
    pipeline_waiting = Column(String(20), nullable=True)
    ai_mode = Column(String(10), default="claude")  # claude, local, hybrid
    last_comment_check_at = Column(String(30), nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class Agent(Base):
    __tablename__ = "agents"

    id = Column(String(36), primary_key=True, default=new_id)
    name = Column(String(100), nullable=False)
    role = Column(String(20), nullable=False)
    status = Column(String(20), default="idle")
    current_issue_id = Column(String(36), ForeignKey("issues.id"), nullable=True)
    last_completed_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class ActivityLog(Base):
    __tablename__ = "activity_log"

    id = Column(String(36), primary_key=True, default=new_id)
    event_type = Column(String(50), nullable=False)
    issue_id = Column(String(36), ForeignKey("issues.id"), nullable=True)
    agent_id = Column(String(36), ForeignKey("agents.id"), nullable=True)
    summary = Column(Text, default="")
    payload = Column(Text, default="{}")
    created_at = Column(DateTime, default=utcnow)


class ImportedComment(Base):
    __tablename__ = "imported_comments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    issue_id = Column(String(36), ForeignKey("issues.id"), nullable=False)
    github_comment_id = Column(Integer, nullable=False)
    body = Column(Text, default="")
    author = Column(String(100), default="")
    created_at = Column(DateTime, default=utcnow)


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id = Column(String(36), primary_key=True, default=new_id)
    repo = Column(String(255), nullable=True)
    messages = Column(Text, default="[]")
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class BackupJob(Base):
    """Metadata record for each database backup."""
    __tablename__ = "backup_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    backup_type = Column(String(10), nullable=False)  # "sqlite" or "json"
    file_path = Column(String(500), nullable=False)
    file_size = Column(Integer, default=0)  # bytes
    status = Column(String(10), default="ok")  # "ok" or "error"
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow)


class DevTask(Base):
    """SeaClip Lite development roadmap tracker."""
    __tablename__ = "dev_tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    feature = Column(String(255), nullable=False)
    category = Column(String(50), nullable=False)
    description = Column(Text, default="")
    impact = Column(String(10), default="medium")
    effort = Column(String(10), default="medium")
    status = Column(String(20), default="planned")
    priority = Column(Integer, default=50)
    issue_id = Column(String(36), ForeignKey("issues.id"), nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class ScheduleConfig(Base):
    """Scheduler config for auto-syncing repos into kanban."""
    __tablename__ = "schedule_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    repo = Column(String(255), nullable=False, unique=True)
    enabled = Column(Integer, default=0)
    interval_minutes = Column(Integer, default=15)
    target_column = Column(String(20), default="backlog")
    auto_pipeline = Column(Integer, default=0)
    pipeline_mode = Column(String(10), default="manual")
    ai_mode = Column(String(10), default="claude")
    last_synced_at = Column(DateTime, nullable=True)
    issues_synced = Column(Integer, default=0)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


SEED_AGENTS = [
    {"name": "Curious Charlie", "role": "research"},
    {"name": "Peter Plan", "role": "architect"},
    {"name": "David Dev", "role": "developer"},
    {"name": "Test Tina", "role": "tester"},
    {"name": "Sceptic Suzy", "role": "reviewer"},
    {"name": "Merge Matthews", "role": "release"},
]
