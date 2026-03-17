from ..models import Issue
from .base import BaseAgent


class DavidDev(BaseAgent):
    name = "David Dev"
    role = "developer"
    trigger_label = "planned"
    completion_label = "coded"

    def _instructions(self, issue: Issue) -> str:
        repo = issue.github_repo
        num = issue.github_issue_number
        return (
            f"David Dev: Read Peter's plan on issue #{num} in repo {repo}.\n"
            f"1. Clone ONLY \"{repo}\" — run: git clone https://github.com/{repo}.git\n"
            f"2. Implement ALL changes in a fix branch\n"
            f"3. Push ONLY to \"{repo}\" — run: git push origin <branch-name>\n"
            f"4. Comment your changes summary on issue #{num}\n"
            f"DO NOT push to or create branches on any other repository.\n\n"
            + self._label_cmd(issue, "coded")
        )
