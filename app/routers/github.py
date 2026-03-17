"""GitHub API proxy routes."""
from fastapi import APIRouter

from ..services import github

router = APIRouter(prefix="/api/github")


@router.get("/repos")
async def list_repos():
    repos = await github.list_org_repos()
    return {"data": repos}
