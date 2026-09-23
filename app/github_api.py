"""
Calls GitHub's REST API to fetch the actual code changes on a pull request,
using the short-lived Installation Access Token from github_auth.py.
"""
 
import requests
 
from app.github_auth import get_installation_token
 
REQUEST_TIMEOUT_SECONDS = 10
 
 
def get_pr_diff(installation_id: str, repo_full_name: str, pr_number: int) -> str:
    """
    Fetch the raw diff (the actual code changes) for a specific pull request.
 
    repo_full_name looks like "Gayatri-2630/pr-sentinel"
    pr_number is just the PR's number, e.g. 1
    """
    token = get_installation_token(installation_id)
 
    url = f"https://api.github.com/repos/{repo_full_name}/pulls/{pr_number}"
 
    response = requests.get(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            # This specific Accept header tells GitHub: "give me the raw diff
            # text, not the usual JSON description of the PR."
            "Accept": "application/vnd.github.v3.diff",
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
 
    return response.text