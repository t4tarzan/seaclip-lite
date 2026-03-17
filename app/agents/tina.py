from ..models import Issue
from .base import BaseAgent


class TinaTest(BaseAgent):
    name = "Test Tina"
    role = "tester"
    trigger_label = "coded"
    completion_label = "tested"

    def _instructions(self, issue: Issue) -> str:
        repo = issue.github_repo
        num = issue.github_issue_number
        return (
            f"Test Tina: Read David's changes on the fix branch for issue #{num} in repo {repo}.\n"
            f"1. Clone ONLY \"{repo}\" — run: git clone https://github.com/{repo}.git\n"
            f"2. Check out David's fix branch\n"
            f"3. Write and run tests\n"
            f"4. Comment a test report on issue #{num}\n"
            f"DO NOT reference or test against any other repository.\n\n"
            + self._label_cmd(issue, "tested")
        )
