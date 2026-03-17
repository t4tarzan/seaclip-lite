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


SEED_AGENTS = [
    {"name": "Curious Charlie", "role": "research"},
    {"name": "Peter Plan", "role": "architect"},
    {"name": "David Dev", "role": "developer"},
    {"name": "Test Tina", "role": "tester"},
    {"name": "Sceptic Suzy", "role": "reviewer"},
    {"name": "Merge Matthews", "role": "release"},
]
