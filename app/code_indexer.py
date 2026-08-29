"""
Handles getting a local, up-to-date copy of a repo's code so we can read
more than just the diff -- this is the foundation for our RAG pipeline.
"""

import os
import shutil

from git import Repo

# Where we'll keep local clones. Each repo gets its own subfolder, named
# after its full_name with the slash replaced (GitHub repo names can't
# contain colons or other path-unsafe characters, so this is safe).
CLONE_BASE_DIR = "./repo_clones"


def _local_path_for_repo(repo_full_name: str) -> str:
    safe_name = repo_full_name.replace("/", "__")
    return os.path.join(CLONE_BASE_DIR, safe_name)


def ensure_repo_cloned(repo_full_name: str, clone_url: str, installation_token: str) -> str:
    """
    Make sure we have a local, up-to-date clone of this repo.
    Returns the local path where the repo now lives.

    If we've never cloned it: clone fresh.
    If we already have it: pull the latest changes instead of re-cloning
    everything from scratch (this is the "incremental" part -- much faster
    on repeat runs).
    """
    local_path = _local_path_for_repo(repo_full_name)

    # Inject the installation token into the clone URL so git can
    # authenticate -- GitHub accepts this "x-access-token" format.
    authenticated_url = clone_url.replace(
        "https://", f"https://x-access-token:{installation_token}@"
    )

    if os.path.exists(local_path):
        try:
            repo = Repo(local_path)
            repo.remotes.origin.pull()
            return local_path
        except Exception:
            # If the existing clone is somehow corrupted, wipe it and
            # start fresh rather than getting stuck in a broken state.
            shutil.rmtree(local_path)

    os.makedirs(CLONE_BASE_DIR, exist_ok=True)
    Repo.clone_from(authenticated_url, local_path)
    return local_path
