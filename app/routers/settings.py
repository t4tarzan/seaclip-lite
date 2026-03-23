"""Hub settings page and API."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import HubSettings

router = APIRouter()


@router.get("/settings")
async def settings_page(request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(HubSettings).order_by(HubSettings.key))
    rows = result.scalars().all()
    settings_map = {r.key: r.value for r in rows}
    return request.app.state.templates.TemplateResponse("pages/settings.html", {
        "request": request,
        "settings": settings_map,
    })


@router.post("/api/settings")
async def save_settings(
    request: Request,
    github_org: str = Form(""),
    claude_model: str = Form(""),
    ollama_model: str = Form(""),
    ollama_url: str = Form(""),
    default_ai_mode: str = Form("claude"),
    default_pipeline_mode: str = Form("manual"),
    # Multi-provider LLM fields
    default_provider: str = Form("claude_cli"),
    default_model: str = Form(""),
    anthropic_api_key: str = Form(""),
    openai_api_key: str = Form(""),
    openrouter_api_key: str = Form(""),
    litellm_base_url: str = Form(""),
    litellm_api_key: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    # Always-update settings (non-sensitive)
    always_update = {
        "github_org": github_org,
        "claude_model": claude_model,
        "ollama_model": ollama_model,
        "ollama_url": ollama_url,
        "default_ai_mode": default_ai_mode,
        "default_pipeline_mode": default_pipeline_mode,
        "default_provider": default_provider,
        "default_model": default_model,
        "litellm_base_url": litellm_base_url,
    }
    # API keys: only update when submitted value is non-empty (prevents accidental blanking)
    api_keys = {
        "anthropic_api_key": anthropic_api_key,
        "openai_api_key": openai_api_key,
        "openrouter_api_key": openrouter_api_key,
        "litellm_api_key": litellm_api_key,
    }

    async def _upsert(key: str, value: str):
        r = await db.execute(select(HubSettings).where(HubSettings.key == key))
        row = r.scalar_one_or_none()
        if row:
            row.value = value
            row.updated_at = datetime.now(timezone.utc)
        else:
            db.add(HubSettings(key=key, value=value))

    for key, value in always_update.items():
        await _upsert(key, value)
    for key, value in api_keys.items():
        if value:  # only save when non-empty
            await _upsert(key, value)

    await db.commit()

    result = await db.execute(select(HubSettings).order_by(HubSettings.key))
    rows = result.scalars().all()
    settings_map = {r.key: r.value for r in rows}
    return request.app.state.templates.TemplateResponse("pages/settings.html", {
        "request": request,
        "settings": settings_map,
        "flash": "Settings saved successfully.",
    })


@router.get("/api/settings/providers")
async def list_providers():
    """Return available LLM providers (no keys)."""
    return {"providers": ["claude_cli", "anthropic", "openai", "openrouter", "litellm", "ollama"]}
