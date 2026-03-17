from ..models import Issue
from .base import BaseAgent


class PeterPlan(BaseAgent):
    name = "Peter Plan"
    role = "architect"
    trigger_label = "researched"
    completion_label = "planned"

    def _instructions(self, issue: Issue) -> str:
        repo = issue.github_repo
        num = issue.github_issue_number
        return (
            f"Peter Plan: Read Charlie's research comment on issue #{num} in repo {repo}.\n"
            f"Create a detailed implementation plan and comment it on the issue.\n"
            f"All file paths and references MUST be relative to the {repo} codebase.\n\n"
            + self._label_cmd(issue, "planned")
        )
