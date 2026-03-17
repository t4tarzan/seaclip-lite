from ..models import Issue
from .base import BaseAgent


class CharlieResearch(BaseAgent):
    name = "Curious Charlie"
    role = "research"
    trigger_label = "plan"
    completion_label = "researched"

    def _instructions(self, issue: Issue) -> str:
        repo = issue.github_repo
        num = issue.github_issue_number
        return (
            f"Your job:\n"
            f"1. Clone ONLY the repo \"{repo}\" — run: git clone https://github.com/{repo}.git\n"
            f"2. Research the codebase and understand the issue\n"
            f"3. Write a detailed research comment on GitHub issue #{num} in repo {repo}\n"
            f"4. Write findings to shared/handoff/task.md\n\n"
            + self._label_cmd(issue, "researched")
        )
