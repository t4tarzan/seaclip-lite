"""Resolve provider/model/api_key for a given agent call."""
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import AgentSoul, HubSettings


@dataclass
class ProviderConfig:
    provider: str
    model: str
    api_key: str
    base_url: str = field(default="")


async def _get_hub_setting(db: AsyncSession, key: str, default: str = "") -> str:
    result = await db.execute(select(HubSettings).where(HubSettings.key == key))
    row = result.scalar_one_or_none()
    return row.value if row else default


async def resolve_model_config(
    db: AsyncSession,
    agent_role: str | None = None,
) -> ProviderConfig:
    """
    Resolve provider/model/api_key with this priority:
      1. AgentSoul.provider / AgentSoul.model  (if agent_role given and non-empty)
      2. HubSettings default_provider / default_model
      3. Hard-coded fallback: claude_cli
    """
    provider = ""
    model = ""

    # 1. Per-agent soul override
    if agent_role:
        r = await db.execute(select(AgentSoul).where(AgentSoul.agent_role == agent_role))
        soul = r.scalar_one_or_none()
        if soul:
            provider = getattr(soul, "provider", "") or ""
            model = getattr(soul, "model", "") or ""

    # 2. Global HubSettings
    if not provider:
        provider = await _get_hub_setting(db, "default_provider", "")
    if not model:
        model = await _get_hub_setting(db, "default_model", "")

    # 3. Env fallback
    if not provider:
        provider = "claude_cli"

    # Resolve API key and base_url for provider
    api_key = ""
    base_url = ""
    key_setting_map = {
        "anthropic": "anthropic_api_key",
        "openai": "openai_api_key",
        "openrouter": "openrouter_api_key",
        "litellm": "litellm_api_key",
    }
    if provider in key_setting_map:
        api_key = await _get_hub_setting(db, key_setting_map[provider], "")
    if provider == "litellm":
        base_url = await _get_hub_setting(db, "litellm_base_url", "http://localhost:4000/v1")

    return ProviderConfig(provider=provider, model=model, api_key=api_key, base_url=base_url)
