"""
Handles getting a local, up-to-date copy of a repo's code so we can read
more than just the diff -- this is the foundation for our RAG pipeline.
"""
 
import os
import shutil
 
from git import Repo
from tree_sitter import Language, Parser
import tree_sitter_python as tspython
 
# Where we'll keep local clones. Each repo gets its own subfolder, named
# after its full_name with the slash replaced (GitHub repo names can't
# contain colons or other path-unsafe characters, so this is safe).
CLONE_BASE_DIR = "./repo_clones"
 
# Set up the tree-sitter parser once, at import time, so we don't rebuild
# it on every single file we parse.
PY_LANGUAGE = Language(tspython.language())
_parser = Parser(PY_LANGUAGE)
 
# The kinds of tree-sitter nodes we consider "a chunk worth indexing."
# Functions and classes are the meaningful units of code most reviewers
# actually reason about -- not arbitrary line counts.
CHUNKABLE_NODE_TYPES = {"function_definition", "class_definition"}
 
 
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
 
 
def _extract_name(node, source_bytes: bytes) -> str:
    """Pull the function/class name out of a tree-sitter node, e.g. 'calculate_total'."""
    for child in node.children:
        if child.type == "identifier":
            return source_bytes[child.start_byte:child.end_byte].decode("utf-8")
    return "<unnamed>"
 
 
def chunk_python_file(file_path: str) -> list[dict]:
    """
    Parse a single Python file and break it into a list of chunks, one per
    top-level function or class, instead of treating the whole file as one
    blob of text.
 
    Returns a list of dicts like:
        {"name": "calculate_total", "type": "function_definition",
         "start_line": 12, "end_line": 25, "code": "def calculate_total(...): ..."}
    """
    with open(file_path, "rb") as f:
        source_bytes = f.read()
 
    tree = _parser.parse(source_bytes)
    root_node = tree.root_node
 
    chunks = []
 
    def walk(node):
        if node.type in CHUNKABLE_NODE_TYPES:
            chunks.append({
                "name": _extract_name(node, source_bytes),
                "type": node.type,
                "start_line": node.start_point[0] + 1,  # tree-sitter is 0-indexed, humans expect 1-indexed
                "end_line": node.end_point[0] + 1,
                "code": source_bytes[node.start_byte:node.end_byte].decode("utf-8"),
            })
            # Deliberately not recursing into a function/class's children --
            # we don't want to also chunk a method inside a class separately
            # from the class itself, at least for this first version.
            return
        for child in node.children:
            walk(child)
 
    walk(root_node)
    return chunks