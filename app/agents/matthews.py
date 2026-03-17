from ..models import Issue
from .base import BaseAgent


class MatthewsMerge(BaseAgent):
    name = "Merge Matthews"
    role = "release"
    trigger_label = "reviewed"
    completion_label = None  # Matthews closes the issue instead of adding a label

    def _instructions(self, issue: Issue) -> str:
        repo = issue.github_repo
        num = issue.github_issue_number
        return (
            f"Merge Matthews: Create a PR and merge for issue #{num} in repo {repo}.\n"
            f"1. The fix branch is in \"{repo}\" — create a PR ONLY in that repo\n"
            f"2. PR title must reference issue: \"closes #{num}\"\n"
            f"3. Run: gh pr create --repo {repo} --title \"fix: <description> (closes #{num})\" --body \"Closes #{num}\"\n"
            f"4. Merge: gh pr merge --repo {repo} --squash --delete-branch\n"
            f"5. Close the issue: gh issue close {num} --repo {repo}\n\n"
            f"CRITICAL: The PR MUST be created in \"{repo}\" and ONLY in \"{repo}\".\n"
            f"Do NOT create PRs in any other repository."
        )
