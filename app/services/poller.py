"""GitHub poller — syncs labels, comments, and issue state."""
import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select, and_, not_

from ..database import async_session
from ..models import Issue, ImportedComment, ActivityLog
from ..services import github
from ..services.events import event_bus
from ..config import settings

logger = logging.getLogger("seaclip.poller")


async def start_poller():
    """Run the poller loop as a background task."""
    if not settings.github_token:
        logger.warning("GITHUB_TOKEN not set — poller disabled")
        return
    logger.info("GitHub poller started (interval=%ds)", settings.github_poll_interval_seconds)
    while True:
        try:
            await poll_once()
        except Exception as e:
            logger.error("Poller tick failed: %s", e)
        await asyncio.sleep(settings.github_poll_interval_seconds)


async def poll_once():
    async with async_session() as db:
        result = await db.execute(
            select(Issue).where(
                and_(
                    Issue.github_repo.isnot(None),
                    Issue.github_issue_number.isnot(None),
                    not_(Issue.status.in_(["done", "cancelled"])),
                )
            )
        )
        issues = result.scalars().all()

        for issue in issues:
            try:
                await poll_issue(issue, db)
            except Exception as e:
                logger.error("Error polling issue %s: %s", issue.id[:8], e)


async def poll_issue(issue: Issue, db):
    repo = issue.github_repo
    gh_number = issue.github_issue_number
    if not repo or not gh_number:
        return

    # 1. Check labels for stage advancement
    labels = await github.get_labels(repo, gh_number)
    current_stage = github.latest_stage_from_labels(labels)
    previous_stage = issue.pipeline_stage

    if (
        current_stage
        and current_stage != previous_stage
        and github.PIPELINE_STAGES.index(current_stage) > github.PIPELINE_STAGES.index(previous_stage or "plan") - 1
    ):
        new_status = "in_review" if current_stage in ("tested", "reviewed") else "in_progress"
        issue.pipeline_stage = current_stage
        issue.status = new_status
        issue.updated_at = datetime.now(timezone.utc)

        activity = ActivityLog(
            event_type="pipeline.stage_changed",
            issue_id=issue.id,
            summary=f"Pipeline advanced to \"{current_stage}\"",
        )
        db.add(activity)
        await db.commit()
        await event_bus.publish("pipeline", "pipeline.stage_changed", {"issue_id": issue.id, "stage": current_stage})
        logger.info("Issue %s advanced to %s", issue.id[:8], current_stage)

    # 2. Import new GitHub comments
    result = await db.execute(
        select(ImportedComment.github_comment_id).where(ImportedComment.issue_id == issue.id)
    )
    imported_ids = set(row[0] for row in result.all())

    comments = await github.get_comments_since(repo, gh_number, issue.last_comment_check_at)
    new_comments = [c for c in comments if c["id"] not in imported_ids]

    for comment in new_comments:
        imp = ImportedComment(
            issue_id=issue.id,
            github_comment_id=comment["id"],
            body=comment["body"],
            author=comment["user"],
        )
        db.add(imp)

    if new_comments:
        issue.last_comment_check_at = new_comments[-1]["created_at"]
        issue.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await event_bus.publish("pipeline", "comments.updated", {"issue_id": issue.id, "count": len(new_comments)})

    # 3. Check if GitHub issue is closed
    closed = await github.is_issue_closed(repo, gh_number)
    if closed and issue.status != "done":
        issue.status = "done"
        issue.pipeline_stage = "completed"
        issue.pipeline_waiting = None
        issue.updated_at = datetime.now(timezone.utc)

        activity = ActivityLog(
            event_type="pipeline.completed",
            issue_id=issue.id,
            summary="Pipeline completed — GitHub issue closed",
        )
        db.add(activity)
        await db.commit()
        await event_bus.publish("pipeline", "pipeline.completed", {"issue_id": issue.id})
        logger.info("Issue %s completed — GH issue closed", issue.id[:8])
