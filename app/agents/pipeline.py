"""Pipeline runner — orchestrates the 6-agent sequence."""
import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import async_session
from ..models import Issue, ActivityLog
from ..services.events import event_bus
from .charlie import CharlieResearch
from .peter import PeterPlan
from .david import DavidDev
from .tina import TinaTest
from .suzy import SuzyReview
from .matthews import MatthewsMerge

logger = logging.getLogger("seaclip.pipeline")

STAGE_ORDER = ["plan", "researched", "planned", "coded", "tested", "reviewed"]

STAGE_TO_AGENT = {
    "plan": CharlieResearch(),
    "researched": PeterPlan(),
    "planned": DavidDev(),
    "coded": TinaTest(),
    "tested": SuzyReview(),
    "reviewed": MatthewsMerge(),
}

STAGE_AGENT_NAME = {
    "plan": "Charlie (Research)",
    "researched": "Peter Plan (Architecture)",
    "planned": "David Dev (Coding)",
    "coded": "Tina (Testing)",
    "tested": "Suzy (Review)",
    "reviewed": "Matthews (Merge)",
}

# Active background tasks keyed by issue_id
_running_tasks: dict[str, asyncio.Task] = {}


async def start_pipeline(issue_id: str, mode: str = "auto", start_stage: str = "plan"):
    """Start the pipeline for an issue."""
    async with async_session() as db:
        issue = await db.get(Issue, issue_id)
        if not issue:
            raise ValueError(f"Issue {issue_id} not found")
        if not issue.github_repo or not issue.github_issue_number:
            raise ValueError("Issue not linked to GitHub")

        issue.pipeline_stage = start_stage
        issue.pipeline_mode = mode
        issue.pipeline_waiting = None
        issue.status = "in_progress"
        issue.updated_at = datetime.now(timezone.utc)
        await db.commit()

        activity = ActivityLog(
            event_type="pipeline.started",
            issue_id=issue_id,
            summary=f"Pipeline started at \"{start_stage}\" ({mode} mode)",
        )
        db.add(activity)
        await db.commit()

    await event_bus.publish("pipeline", "pipeline.started", {"issue_id": issue_id, "stage": start_stage})

    # Launch the agent as a background task
    task = asyncio.create_task(_run_stage(issue_id, start_stage, mode))
    _running_tasks[issue_id] = task


async def resume_pipeline(issue_id: str, stage: str):
    """Resume a manual pipeline — trigger the next agent."""
    async with async_session() as db:
        issue = await db.get(Issue, issue_id)
        if not issue:
            raise ValueError(f"Issue {issue_id} not found")

        mode = issue.pipeline_mode or "manual"
        issue.pipeline_waiting = None
        issue.updated_at = datetime.now(timezone.utc)
        await db.commit()

        activity = ActivityLog(
            event_type="pipeline.resumed",
            issue_id=issue_id,
            summary=f"Pipeline resumed — triggering agent for \"{stage}\"",
        )
        db.add(activity)
        await db.commit()

    await event_bus.publish("pipeline", "pipeline.resumed", {"issue_id": issue_id, "stage": stage})

    task = asyncio.create_task(_run_stage(issue_id, stage, mode))
    _running_tasks[issue_id] = task


async def _run_stage(issue_id: str, stage: str, mode: str):
    """Run a single pipeline stage."""
    agent = STAGE_TO_AGENT.get(stage)
    if not agent:
        logger.error("No agent for stage %s", stage)
        return

    try:
        async with async_session() as db:
            issue = await db.get(Issue, issue_id)
            if not issue:
                return

            logger.info("Running %s for issue %s (%s mode)", agent.name, issue_id[:8], mode)
            await agent.run(issue, db)

            # Refresh issue after agent completes
            await db.refresh(issue)

            if mode == "auto":
                # Auto mode: advance to next stage and run it
                stage_idx = STAGE_ORDER.index(stage) if stage in STAGE_ORDER else -1
                if stage_idx < len(STAGE_ORDER) - 1:
                    next_stage = STAGE_ORDER[stage_idx + 1]
                    issue.pipeline_stage = next_stage
                    issue.updated_at = datetime.now(timezone.utc)
                    await db.commit()
                    # Chain to next agent
                    await _run_stage(issue_id, next_stage, mode)
                else:
                    # Last stage done — pipeline complete
                    issue.pipeline_stage = "completed"
                    issue.status = "done"
                    issue.updated_at = datetime.now(timezone.utc)
                    await db.commit()
                    await event_bus.publish("pipeline", "pipeline.completed", {"issue_id": issue_id})
            else:
                # Manual mode: pause and wait for user to click resume
                # The agent just finished. The completion label is on GitHub.
                # Set pipeline_waiting to the current stage label so the UI
                # knows which agent to trigger next when user clicks Resume.
                stage_idx = STAGE_ORDER.index(stage) if stage in STAGE_ORDER else -1
                if stage_idx < len(STAGE_ORDER) - 1:
                    next_trigger = STAGE_ORDER[stage_idx + 1]
                    issue.pipeline_stage = next_trigger
                    issue.pipeline_waiting = next_trigger
                    issue.updated_at = datetime.now(timezone.utc)
                    await db.commit()
                    await event_bus.publish("pipeline", "pipeline.waiting", {
                        "issue_id": issue_id,
                        "waiting": next_trigger,
                        "agent_name": STAGE_AGENT_NAME.get(next_trigger, "Next Agent"),
                    })
                    logger.info("Manual mode — waiting for user to trigger %s", STAGE_AGENT_NAME.get(next_trigger))
                else:
                    issue.pipeline_stage = "completed"
                    issue.status = "done"
                    issue.updated_at = datetime.now(timezone.utc)
                    await db.commit()
                    await event_bus.publish("pipeline", "pipeline.completed", {"issue_id": issue_id})

    except Exception as e:
        logger.error("Pipeline stage %s failed for %s: %s", stage, issue_id[:8], e)
        async with async_session() as db:
            issue = await db.get(Issue, issue_id)
            if issue:
                issue.pipeline_waiting = stage  # Allow retry
                issue.updated_at = datetime.now(timezone.utc)
                await db.commit()
    finally:
        _running_tasks.pop(issue_id, None)


def stop_pipeline(issue_id: str) -> bool:
    """Cancel a running pipeline task."""
    task = _running_tasks.pop(issue_id, None)
    if task and not task.done():
        task.cancel()
        return True
    return False
