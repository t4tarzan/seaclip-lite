"""Base agent class — all pipeline agents inherit from this."""
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Agent, Issue, ActivityLog, ImportedComment
from ..services import ai, github
from ..services.events import event_bus
from ..services.model_config import resolve_model_config

logger = logging.getLogger("seaclip.agents")

# Maps each agent to the next agent name for handoff messages
# CLI-Anything tools available to each agent role
# Activate with: source /Users/whitenoise-oc/projects/CLI-Anything/.venv/bin/activate
CLI_TOOLS_BY_ROLE = {
    "research": {
        "cli-anything-ollama": "Local LLM queries. `cli-anything-ollama --json generate text --model qwen3.5:35b --prompt \"...\" --no-stream`",
        "cli-anything-chromadb": "Search hub knowledge base. `cli-anything-chromadb --json query search --collection hub_knowledge --text \"...\" --n-results 5`",
    },
    "architect": {
        "cli-anything-mermaid": "Diagram generation. `cli-anything-mermaid --json project new -o /tmp/arch.mermaid.json`, then `diagram set --text \"graph TD; ...\"`, then `export share --mode view`.",
        "cli-anything-ollama": "Local LLM for brainstorming. `cli-anything-ollama --json generate text --model qwen3.5:35b --prompt \"...\" --no-stream`",
        "cli-anything-chromadb": "Search existing docs/architecture. `cli-anything-chromadb --json query search --collection docs --text \"...\" --n-results 3`",
    },
    "developer": {
        "cli-anything-ollama": "Local LLM for code questions. `cli-anything-ollama --json generate text --model qwen3.5:35b --prompt \"...\" --no-stream`",
        "cli-anything-mermaid": "Generate diagrams. `cli-anything-mermaid --json project new -o /tmp/diagram.mermaid.json` then set/render.",
        "cli-anything-seaclip": "Query kanban issues and pipeline status. `cli-anything-seaclip --json issue list --status backlog`",
        "cli-anything-pm2": "Check running services. `cli-anything-pm2 --json process list`",
    },
    "tester": {
        "cli-anything-pm2": "Check service status after tests. `cli-anything-pm2 --json process list`",
    },
    "reviewer": {
        "cli-anything-chromadb": "Search for related context. `cli-anything-chromadb --json query search --collection codebase --text \"...\" --n-results 5`",
    },
    "release": {
        "cli-anything-pm2": "Restart services after deploy. `cli-anything-pm2 --json lifecycle restart <service>`",
        "cli-anything-seaclip": "Update issue status. `cli-anything-seaclip --json issue list`",
    },
}

NEXT_AGENT = {
    "research": "Peter Plan (Architect)",
    "architect": "David Dev (Developer)",
    "developer": "Test Tina (Tester)",
    "tester": "Sceptic Suzy (Reviewer)",
    "reviewer": "Merge Matthews (Release)",
    "release": None,
}


class BaseAgent:
    name: str = ""
    role: str = ""
    trigger_label: str = ""
    completion_label: str | None = None

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

        output_format = (
            f"\n\n--- CRITICAL OUTPUT RULES ---\n"
            f"1. Return your findings/work as structured markdown to STDOUT.\n"
            f"2. Do NOT post comments on GitHub yourself — do NOT run 'gh issue comment' or any variant.\n"
            f"3. Do NOT add labels — do NOT run 'gh issue edit --add-label' or curl to the labels API.\n"
            f"4. Do NOT close issues — do NOT run 'gh issue close'.\n"
            f"5. Your stdout text will be automatically posted as a GitHub comment by the pipeline system.\n"
            f"6. Labels are automatically applied by the pipeline system after your work.\n"
            f"7. Just output your analysis/findings/work summary as plain markdown text.\n"
            f"8. Be thorough but concise. Use headings, bullet points, tables, and code blocks.\n"
        )

        # Inject available CLI tools for this agent role
        cli_tools = CLI_TOOLS_BY_ROLE.get(self.role, {})
        if cli_tools:
            tools_section = "\n\n--- AVAILABLE CLI TOOLS ---\n"
            tools_section += "You have access to these CLI tools (activate venv first: source /Users/whitenoise-oc/projects/CLI-Anything/.venv/bin/activate). Always use --json flag for parseable output.\n\n"
            for tool_name, usage in cli_tools.items():
                tools_section += f"**{tool_name}**: {usage}\n\n"
        else:
            tools_section = ""

        return header + self._instructions(issue) + tools_section + output_format

    def _instructions(self, issue: Issue) -> str:
        """Override in subclasses to provide agent-specific instructions."""
        return ""

    def _label_cmd(self, issue: Issue, label: str) -> str:
        """Legacy label instruction — labels are now applied by the pipeline system."""
        return ""

    def _format_github_comment(self, issue: Issue, output: str) -> str:
        """Format the agent output as a structured GitHub comment."""
        repo = issue.github_repo
        num = issue.github_issue_number
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        next_agent = NEXT_AGENT.get(self.role)

        comment = f"## {self.name}\n\n"
        comment += f"**Repo:** [`{repo}`](https://github.com/{repo}) · "
        comment += f"**Issue:** [#{num}](https://github.com/{repo}/issues/{num}) · "
        comment += f"**Date:** {now}\n\n"
        comment += "---\n\n"
        comment += output.strip()
        comment += "\n\n---\n\n"

        if next_agent:
            comment += f"**Handoff →** {next_agent}\n"
        else:
            comment += "**Pipeline complete** — issue closed.\n"

        return comment

    async def run(self, issue: Issue, db: AsyncSession) -> str:
        """Execute the agent: mark active, run AI, post comment, apply label, mark idle."""
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
            # Run AI — resolve provider via model_config (soul → hub → env fallback)
            prompt = self.build_prompt(issue)
            cfg = await resolve_model_config(db, agent_role=self.role)
            logger.info("Running %s for issue %s (provider=%s model=%s)", self.name, issue.id[:8], cfg.provider, cfg.model or "default")
            await event_bus.publish("agents", "agent.log", {"agent": agent.name, "message": f"Building prompt ({len(prompt)} chars) — provider={cfg.provider}"})

            # Live log callback — publishes events to SSE stream
            async def _on_log(line: str):
                await event_bus.publish("agents", "agent.log", {
                    "agent": agent.name, "message": line,
                })

            output = await ai.call_model(
                provider=cfg.provider,
                model=cfg.model,
                api_key=cfg.api_key,
                prompt=prompt,
                base_url=cfg.base_url,
                timeout=600,
                on_log=_on_log,
            )

            await event_bus.publish("agents", "agent.log", {"agent": agent.name, "message": f"AI returned {len(output)} chars"})

            # Post formatted comment on GitHub + save to DB immediately
            if issue.github_repo and issue.github_issue_number:
                comment_body = self._format_github_comment(issue, output)
                try:
                    resp = await github.post_comment(issue.github_repo, issue.github_issue_number, comment_body)
                    gh_comment_id = resp.get("id", 0)
                    logger.info("%s posted comment on GitHub #%s", self.name, issue.github_issue_number)
                    await event_bus.publish("agents", "agent.log", {"agent": agent.name, "message": f"Posted comment on GitHub #{issue.github_issue_number}"})

                    # Save directly to DB so it shows on issue detail immediately
                    imp = ImportedComment(
                        issue_id=issue.id,
                        github_comment_id=gh_comment_id,
                        body=comment_body,
                        author=self.name,
                    )
                    db.add(imp)
                    await db.commit()
                except Exception as e:
                    logger.warning("%s failed to post comment: %s", self.name, e)

            # Apply completion label on GitHub
            if self.completion_label and issue.github_repo and issue.github_issue_number:
                await github.add_label(issue.github_repo, issue.github_issue_number, self.completion_label)
                logger.info("%s applied label '%s'", self.name, self.completion_label)
                await event_bus.publish("agents", "agent.log", {"agent": agent.name, "message": f"Applied label: {self.completion_label}"})

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
