"""Base agent class — all pipeline agents inherit from this."""
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Agent, Issue, ActivityLog
from ..services import ai, github
from ..services.events import event_bus

logger = logging.getLogger("seaclip.agents")


class BaseAgent:
    name: str = ""
    role: str = ""
    trigger_label: str = ""
    completion_label: str | None = None  # None for Matthews (closes issue instead)

    def build_prompt(self, issue: Issue) -> str:
        """Build the strict-context prompt for this agent."""
        repo = issue.github_repo or "unknown/repo"
        num = issue.github_issue_number or 0
        url = issue.github_issue_url or f"https://github.com/{repo}/issues/{num}"

        header = (
            f"STRICT CONTEXT — DO NOT DEVIATE:\n"
            f"  Repository: {repo}\n"
            f"  GitHub Issue: #{num}\n"
            f"  Issue URL: {url}\n"
            f"  Clone URL: https://github.com/{repo}.git\n\n"
            f"IMPORTANT: You MUST only operate on the repository \"{repo}\".\n"
            f"Do NOT clone, push to, create PRs on, or reference any other repository.\n"
            f"All git commands, gh CLI commands, and API calls MUST target \"{repo}\" and issue #{num}.\n\n"
            f"Issue: {issue.title}\n\n"
            f"Description:\n{issue.description or 'No description'}\n\n"
        )
        return header + self._instructions(issue)

    def _instructions(self, issue: Issue) -> str:
        """Override in subclasses to provide agent-specific instructions."""
        return ""

    def _label_cmd(self, issue: Issue, label: str) -> str:
        repo = issue.github_repo
        num = issue.github_issue_number
        return (
            f"CRITICAL — YOUR LAST STEP (do NOT skip):\n"
            f"Run this exact command:\n"
            f"  gh issue edit {num} --repo {repo} --add-label \"{label}\"\n"
            f"If that fails, use curl:\n"
            f"  curl -s -X POST -H \"Authorization: token $GITHUB_TOKEN\" "
            f"-H \"Content-Type: application/json\" "
            f"https://api.github.com/repos/{repo}/issues/{num}/labels "
            f"-d '{{\"labels\":[\"{label}\"]}}'"
        )

    async def run(self, issue: Issue, db: AsyncSession) -> str:
        """Execute the agent: mark active, run AI, apply label, mark idle."""
        # Find this agent in DB
        result = await db.execute(select(Agent).where(Agent.role == self.role))
        agent = result.scalar_one_or_none()
        if not agent:
            raise RuntimeError(f"Agent with role {self.role} not found in DB")

        # Mark active
        agent.status = "active"
        agent.current_issue_id = issue.id
        agent.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await event_bus.publish("agents", "agent.active", {"agent": agent.name, "issue": issue.title})

        try:
            # Run AI
            prompt = self.build_prompt(issue)
            logger.info("Running %s for issue %s", self.name, issue.id[:8])
            output = await ai.claude_chat(prompt)

            # Apply completion label on GitHub
            if self.completion_label and issue.github_repo and issue.github_issue_number:
                await github.add_label(issue.github_repo, issue.github_issue_number, self.completion_label)
                logger.info("%s applied label '%s'", self.name, self.completion_label)

            # Mark idle
            agent.status = "idle"
            agent.current_issue_id = None
            agent.last_completed_at = datetime.now(timezone.utc)
            agent.last_error = None
            agent.updated_at = datetime.now(timezone.utc)
            await db.commit()

            # Log activity
            activity = ActivityLog(
                event_type="agent.completed",
                issue_id=issue.id,
                agent_id=agent.id,
                summary=f"{self.name} completed work on \"{issue.title}\"",
            )
            db.add(activity)
            await db.commit()

            await event_bus.publish("agents", "agent.completed", {"agent": agent.name, "issue": issue.title})
            await event_bus.publish("pipeline", "pipeline.stage_changed", {"issue_id": issue.id})

            return output

        except Exception as e:
            logger.error("%s failed: %s", self.name, e)
            agent.status = "error"
            agent.last_error = str(e)
            agent.current_issue_id = None
            agent.updated_at = datetime.now(timezone.utc)
            await db.commit()
            await event_bus.publish("agents", "agent.error", {"agent": agent.name, "error": str(e)})
            raise
