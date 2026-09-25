"""
Handles proving our GitHub App's identity to GitHub's API.
 
Two-step process:
1. Build a short-lived JWT signed with our private key -- proves "I am this App."
2. Exchange that JWT for an Installation Access Token -- scoped to one specific
   installation (e.g. one user's account + the repos they installed us on).
   This is the token actually used to call the GitHub API (fetch diffs, post
   comments, etc.).
"""
 
import os
import time
 
import jwt  # from the pyjwt package
import requests
from dotenv import load_dotenv
 
load_dotenv()
 
GITHUB_APP_ID = os.getenv("GITHUB_APP_ID")
GITHUB_PRIVATE_KEY_PATH = os.getenv("GITHUB_PRIVATE_KEY_PATH")
 
REQUEST_TIMEOUT_SECONDS = 10
 
 
def _load_private_key() -> str:
    """
    Prefer reading the key directly from an environment variable -- this
    is how we'll run in production (Render's free tier doesn't support
    mounting secret files). Falls back to reading from a file path for
    local development, where the .pem file already exists on disk.
    """
    key_from_env = os.getenv("GITHUB_PRIVATE_KEY_PEM")
    if key_from_env:
        return key_from_env.replace("\\n", "\n")
    with open(GITHUB_PRIVATE_KEY_PATH, "r", encoding="utf-8") as key_file:
        return key_file.read()
 
 
def generate_jwt() -> str:
    """
    Build a JWT proving 'I am App #GITHUB_APP_ID', signed with our private key.
    Valid for 10 minutes max (GitHub's own limit) -- we use 9 to stay safely inside it.
    """
    private_key = _load_private_key()
    now = int(time.time())
 
    payload = {
        "iat": now - 60,  # issued-at, backdated 60s to allow for small clock drift
        "exp": now + (9 * 60),  # expires in 9 minutes
        "iss": GITHUB_APP_ID,  # the "issuer" -- identifies which App this token is for
    }
 
    return jwt.encode(payload, private_key, algorithm="RS256")
 
 
def get_installation_token(installation_id: str) -> str:
    """
    Exchange our App-level JWT for a short-lived token scoped to one specific
    installation. THIS is the token we'll actually use to call the GitHub API.
    """
    app_jwt = generate_jwt()
 
    response = requests.post(
        f"https://api.github.com/app/installations/{installation_id}/access_tokens",
        headers={
            "Authorization": f"Bearer {app_jwt}",
            "Accept": "application/vnd.github+json",
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()  # raises an error loudly if this fails, instead of failing silently
 
    return response.json()["token"]