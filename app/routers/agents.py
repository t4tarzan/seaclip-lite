"""Agent status routes."""
from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import Agent

router = APIRouter(prefix="/api/agents")


@router.get("")
async def list_agents(request: Request, db: AsyncSession = Depends(get_db)):
    agents = (await db.execute(select(Agent).order_by(Agent.created_at))).scalars().all()
    return request.app.state.templates.TemplateResponse("partials/agent_list.html", {
        "request": request, "agents": agents,
    })
