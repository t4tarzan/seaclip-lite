"""Scheduler — auto-syncs GitHub repo issues into kanban on a configurable interval."""
import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import async_session
from ..models import Issue, ScheduleConfig, ActivityLog
from ..services import github
from ..services.events import event_bus

logger = logging.getLogger("seaclip.scheduler")

_task: asyncio.Task | None = None


async def sync_repo(config: ScheduleConfig, db: AsyncSession) -> int:
    """Pull open issues from a GitHub repo and create missing kanban cards. Returns count of new issues."""
    gh_issues = await github.list_repo_issues(config.repo, state="open")
    if not gh_issues:
        return 0

    # Get existing issue numbers for this repo
    result = await db.execute(
        select(Issue.github_issue_number).where(Issue.github_repo == config.repo)
    )
    existing_numbers = {row[0] for row in result.all() if row[0]}

    created = 0
    for gi in gh_issues:
        if gi["number"] in existing_numbers:
            continue

        issue = Issue(
            title=gi["title"],
            description=gi["body"][:2000] if gi["body"] else "",
            priority="medium",
            status=config.target_column or "backlog",
            github_repo=config.repo,
            github_issue_number=gi["number"],
            github_issue_url=gi["url"],
        )
        db.add(issue)
        created += 1

    if created:
        await db.flush()

        # Auto-start pipeline on new issues if enabled
        if config.auto_pipeline:
            from ..agents.pipeline import start_pipeline
            result = await db.execute(
                select(Issue).where(
                    Issue.github_repo == config.repo,
                    Issue.pipeline_stage.is_(None),
                    Issue.status == (config.target_column or "backlog"),
                ).order_by(Issue.created_at.desc()).limit(created)
            )
            new_issues = result.scalars().all()
            for ni in new_issues:
                try:
                    await start_pipeline(
                        ni.id,
                        mode=config.pipeline_mode or "manual",
                    )
                    logger.info("Auto-started pipeline for %s (#%s)", ni.title, ni.github_issue_number)
                except Exception as e:
                    logger.warning("Auto-pipeline failed for %s: %s", ni.title, e)

        activity = ActivityLog(
            event_type="scheduler.sync",
            summary=f"Synced {created} new issues from {config.repo}",
        )
        db.add(activity)

    config.last_synced_at = datetime.now(timezone.utc)
    config.issues_synced = (config.issues_synced or 0) + created
    config.updated_at = datetime.now(timezone.utc)
    await db.commit()

    if created:
        logger.info("Scheduler: synced %d new issues from %s", created, config.repo)
        await event_bus.publish("pipeline", "scheduler.synced", {
            "repo": config.repo, "count": created,
        })

    return created


async def _scheduler_loop():
    """Main scheduler loop — checks all enabled configs and syncs on interval."""
    logger.info("Scheduler started")
    while True:
        try:
            async with async_session() as db:
                result = await db.execute(
                    select(ScheduleConfig).where(ScheduleConfig.enabled == 1)
                )
                configs = result.scalars().all()

                for config in configs:
                    # Check if it's time to sync
                    interval = (config.interval_minutes or 15) * 60  # seconds
                    if config.last_synced_at:
                        last = config.last_synced_at
                        if last.tzinfo is None:
                            last = last.replace(tzinfo=timezone.utc)
                        elapsed = (datetime.now(timezone.utc) - last).total_seconds()
                        if elapsed < interval:
                            continue

                    try:
                        await sync_repo(config, db)
                    except Exception as e:
                        logger.error("Scheduler sync failed for %s: %s", config.repo, e)

        except Exception as e:
            logger.error("Scheduler loop error: %s", e)

        await asyncio.sleep(30)  # check every 30s


def start_scheduler() -> asyncio.Task:
    """Start the scheduler background task."""
    global _task
    _task = asyncio.create_task(_scheduler_loop())
    return _task


async def run_sync_now(repo: str) -> int:
    """Manually trigger a sync for a repo."""
    async with async_session() as db:
        result = await db.execute(
            select(ScheduleConfig).where(ScheduleConfig.repo == repo)
        )
        config = result.scalar_one_or_none()
        if not config:
            return 0
        return await sync_repo(config, db)
