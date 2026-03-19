"""GitHub REST API wrapper using httpx."""
import httpx

from ..config import settings

_client: httpx.AsyncClient | None = None

PIPELINE_LABELS = [
    {"name": "plan", "color": "1d76db", "description": "Pipeline: research stage"},
    {"name": "researched", "color": "0075ca", "description": "Pipeline: research complete"},
    {"name": "planned", "color": "5319e7", "description": "Pipeline: plan complete"},
    {"name": "coded", "color": "e4e669", "description": "Pipeline: code complete"},
    {"name": "tested", "color": "0e8a16", "description": "Pipeline: tests passed"},
    {"name": "reviewed", "color": "22c55e", "description": "Pipeline: review passed"},
]

PIPELINE_STAGES = ["plan", "researched", "planned", "coded", "tested", "reviewed"]


def _headers() -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {settings.github_token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }


async def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            base_url="https://api.github.com",
            headers=_headers(),
            timeout=30.0,
        )
    return _client


async def list_org_repos(org: str | None = None) -> list[dict]:
    target = org or settings.github_org
    client = await get_client()
    r = await client.get(f"/users/{target}/repos", params={"per_page": 100, "sort": "updated"})
    if r.status_code != 200:
        return []
    return [
        {"name": repo["name"], "full_name": repo["full_name"], "description": repo.get("description"), "private": repo["private"]}
        for repo in r.json()
    ]


async def list_repo_issues(repo: str, state: str = "open") -> list[dict]:
    """List issues for a repo. Returns list of dicts with number, title, body, url."""
    client = await get_client()
    r = await client.get(f"/repos/{repo}/issues", params={"state": state, "per_page": 100})
    if r.status_code != 200:
        return []
    return [
        {"number": i["number"], "title": i["title"], "body": i.get("body"), "url": i["html_url"]}
        for i in r.json()
        if "pull_request" not in i  # exclude PRs
    ]


async def create_issue(repo: str, title: str, body: str) -> dict:
    client = await get_client()
    r = await client.post(f"/repos/{repo}/issues", json={"title": title, "body": body})
    if r.status_code not in (200, 201):
        raise Exception(f"GitHub create issue failed ({r.status_code}): {r.text}")
    data = r.json()
    return {"number": data["number"], "url": data["html_url"]}


async def post_comment(repo: str, issue_number: int, body: str) -> dict:
    """Post a comment on a GitHub issue."""
    client = await get_client()
    r = await client.post(
        f"/repos/{repo}/issues/{issue_number}/comments",
        json={"body": body},
    )
    if r.status_code not in (200, 201):
        raise Exception(f"GitHub post comment failed ({r.status_code}): {r.text}")
    data = r.json()
    return {"id": data.get("id", 0)}


async def add_label(repo: str, issue_number: int, label: str) -> None:
    client = await get_client()
    await client.post(f"/repos/{repo}/issues/{issue_number}/labels", json={"labels": [label]})


async def get_labels(repo: str, issue_number: int) -> list[str]:
    client = await get_client()
    r = await client.get(f"/repos/{repo}/issues/{issue_number}/labels")
    if r.status_code != 200:
        return []
    return [label["name"] for label in r.json()]


async def get_comments_since(repo: str, issue_number: int, since: str | None = None) -> list[dict]:
    client = await get_client()
    params: dict = {"per_page": 100}
    if since:
        params["since"] = since
    r = await client.get(f"/repos/{repo}/issues/{issue_number}/comments", params=params)
    if r.status_code != 200:
        return []
    return [
        {"id": c["id"], "body": c["body"], "user": c.get("user", {}).get("login", "unknown"), "created_at": c["created_at"]}
        for c in r.json()
    ]


async def is_issue_closed(repo: str, issue_number: int) -> bool:
    client = await get_client()
    r = await client.get(f"/repos/{repo}/issues/{issue_number}")
    if r.status_code != 200:
        return False
    return r.json().get("state") == "closed"


async def bootstrap_repo_labels(repo: str) -> None:
    client = await get_client()
    r = await client.get(f"/repos/{repo}/labels", params={"per_page": 100})
    existing = [label["name"] for label in r.json()] if r.status_code == 200 else []
    for label in PIPELINE_LABELS:
        if label["name"] not in existing:
            await client.post(f"/repos/{repo}/labels", json=label)


def latest_stage_from_labels(labels: list[str]) -> str | None:
    latest = None
    latest_idx = -1
    for label in labels:
        if label in PIPELINE_STAGES:
            idx = PIPELINE_STAGES.index(label)
            if idx > latest_idx:
                latest_idx = idx
                latest = label
    return latest
