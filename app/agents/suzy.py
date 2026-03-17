from ..models import Issue
from .base import BaseAgent


class SuzyReview(BaseAgent):
    name = "Sceptic Suzy"
    role = "reviewer"
    trigger_label = "tested"
    completion_label = "reviewed"

    def _instructions(self, issue: Issue) -> str:
        repo = issue.github_repo
        num = issue.github_issue_number
        return (
            f"Sceptic Suzy: Review the code changes for issue #{num} in repo {repo}.\n"
            f"1. Clone ONLY \"{repo}\" — run: git clone https://github.com/{repo}.git\n"
            f"2. Check out the fix branch\n"
            f"3. Review for security, quality, and correctness\n"
            f"4. Comment your verdict on issue #{num}\n"
            f"DO NOT reference or review code from any other repository.\n\n"
            f"If PASS:\n"
            + self._label_cmd(issue, "reviewed")
        )
