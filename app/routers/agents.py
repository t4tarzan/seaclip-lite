"""Agent status routes."""
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import Agent, AgentSoul
from ..services.events import event_bus

router = APIRouter(prefix="/api/agents")


@router.get("/stream")
async def agents_stream(db: AsyncSession = Depends(get_db)):
    """Single SSE connection for all agent events."""
    active_agents = (await db.execute(
        select(Agent).where(Agent.status == "active")
    )).scalars().all()

    async def event_generator():
        q = event_bus.subscribe("agents")
        try:
            # Send initial status for any active agents
            for ag in active_agents:
                payload = json.dumps({"agent": ag.name, "status": "active", "message": "Currently working..."})
                yield f"event: status\ndata: {payload}\n\n"

            while True:
                event = await q.get()
                etype = event.get("type", "")
                data = event.get("data", {})

                if etype == "agent.active":
                    payload = json.dumps({"agent": data.get("agent", ""), "status": "active", "message": f"Working on: {data.get('issue', '')}"})
                    yield f"event: status\ndata: {payload}\n\n"
                elif etype == "agent.completed":
                    payload = json.dumps({"agent": data.get("agent", ""), "status": "completed", "message": f"Completed: {data.get('issue', '')}"})
                    yield f"event: status\ndata: {payload}\n\n"
                elif etype == "agent.error":
                    payload = json.dumps({"agent": data.get("agent", ""), "status": "error", "message": data.get("error", "Unknown error")})
                    yield f"event: status\ndata: {payload}\n\n"
                elif etype == "agent.log":
                    payload = json.dumps({"agent": data.get("agent", ""), "message": data.get("message", "")})
                    yield f"event: log\ndata: {payload}\n\n"

        except Exception:
            pass
        finally:
            event_bus.unsubscribe("agents", q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("")
async def list_agents(request: Request, db: AsyncSession = Depends(get_db)):
    agents = (await db.execute(select(Agent).order_by(Agent.created_at))).scalars().all()
    return request.app.state.templates.TemplateResponse("partials/agent_list.html", {
        "request": request, "agents": agents,
    })


@router.get("/customize")
async def customize_page(request: Request, db: AsyncSession = Depends(get_db)):
    """Agent soul customization page."""
    souls = (await db.execute(
        select(AgentSoul).order_by(AgentSoul.agent_role)
    )).scalars().all()
    return request.app.state.templates.TemplateResponse("pages/agent_customize.html", {
        "request": request,
        "souls": souls,
    })


@router.post("/souls/{soul_id}")
async def update_soul(
    request: Request,
    soul_id: int,
    system_prompt: str = Form(""),
    extra_instructions: str = Form(""),
    temperature: str = Form("0.7"),
    provider: str = Form(""),
    model: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    soul = await db.get(AgentSoul, soul_id)
    if not soul:
        return HTMLResponse("Not found", status_code=404)

    soul.system_prompt = system_prompt
    soul.extra_instructions = extra_instructions
    soul.temperature = temperature
    soul.provider = provider
    soul.model = model
    soul.updated_at = datetime.now(timezone.utc)
    await db.commit()

    souls = (await db.execute(
        select(AgentSoul).order_by(AgentSoul.agent_role)
    )).scalars().all()
    return request.app.state.templates.TemplateResponse("pages/agent_customize.html", {
        "request": request,
        "souls": souls,
        "flash": f"Soul for '{soul.agent_role}' updated.",
    })
