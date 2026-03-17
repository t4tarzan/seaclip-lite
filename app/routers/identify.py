"""Identify chat — AI-powered issue extraction."""
import json

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import Issue
from ..services import ai

router = APIRouter(prefix="/api/identify")


@router.post("/chat")
async def chat(
    request: Request,
    messages: str = Form(...),
    repo: str = Form(""),
):
    msgs = json.loads(messages)
    system = (
        f"You are a helpful AI assistant discussing the codebase at {repo}. "
        "Help the user explore, debug, and identify improvements. Be concise and technical."
    ) if repo else (
        "You are a helpful AI assistant for software development. "
        "Help the user explore ideas, debug problems, and identify improvements. Be concise."
    )

    reply = await ai.chat(system, msgs)

    return request.app.state.templates.TemplateResponse("partials/chat_message.html", {
        "request": request, "role": "assistant", "content": reply,
    })


@router.post("/extract-issue")
async def extract_issue(
    request: Request,
    messages: str = Form(...),
    repo: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    msgs = json.loads(messages)
    conversation = "\n\n".join(f"{m['role']}: {m['content']}" for m in msgs)

    repo_ctx = f"\nRepository: {repo}\nInclude this repo context in the description." if repo else ""
    extract_prompt = (
        f"Based on the following conversation, extract a single GitHub-style issue. "
        f"Return ONLY valid JSON with these fields:\n"
        f"- \"title\": a concise issue title (max 100 chars), use conventional commit style\n"
        f"- \"description\": a detailed description in markdown\n"
        f"- \"priority\": one of \"urgent\", \"high\", \"medium\", \"low\"{repo_ctx}\n\n"
        f"Do not wrap in markdown code fences. Output raw JSON only.\n\n"
        f"Conversation:\n{conversation}"
    )

    try:
        raw = await ai.claude_chat(extract_prompt)
        cleaned = raw.replace("```json", "").replace("```", "").strip()
        parsed = json.loads(cleaned)
        title = parsed.get("title", "Untitled Issue")
        description = parsed.get("description", "")
        priority = parsed.get("priority", "medium")
        if priority not in ("urgent", "high", "medium", "low"):
            priority = "medium"
    except Exception:
        title = msgs[0]["content"][:80] if msgs else "Untitled Issue"
        description = conversation
        priority = "medium"

    normalized_repo = repo.replace("https://github.com/", "").rstrip("/").removesuffix(".git") if repo else None

    issue = Issue(
        title=title,
        description=description,
        priority=priority,
        status="backlog",
        github_repo=normalized_repo,
    )
    db.add(issue)
    await db.commit()
    await db.refresh(issue)

    return request.app.state.templates.TemplateResponse("partials/chat_message.html", {
        "request": request,
        "role": "assistant",
        "content": f"Issue created: **{title}**\n\nPriority: {priority} | Repo: {normalized_repo or 'none'}\n\nFind it in the Kanban board.",
    })
