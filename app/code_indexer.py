"""
Handles getting a local, up-to-date copy of a repo's code so we can read
more than just the diff -- this is the foundation for our RAG pipeline.
"""
 
import os
import pickle
import shutil
import stat
 
import faiss
import numpy as np
from git import Repo
from tree_sitter import Language, Parser
import tree_sitter_python as tspython
 
from app.llm_client import embed_texts
 
CLONE_BASE_DIR = "./repo_clones"
INDEX_BASE_DIR = "./vector_indexes"
 
PY_LANGUAGE = Language(tspython.language())
_parser = Parser(PY_LANGUAGE)
 
CHUNKABLE_NODE_TYPES = {"function_definition", "class_definition"}
 
SENSITIVE_FILE_PATTERNS = [
    ".env",
    ".pem",
    "credentials.json",
    "id_rsa",
    "id_ed25519",
    ".pfx",
    ".p12",
    "secrets.yml",
    "secrets.yaml",
    ".npmrc",
    ".pypirc",
]
 
 
def is_sensitive_file(file_path: str) -> bool:
    """Check if a file path matches any known sensitive-file pattern."""
    file_path_lower = file_path.lower()
    return any(pattern in file_path_lower for pattern in SENSITIVE_FILE_PATTERNS)
 
 
def _local_path_for_repo(repo_full_name: str) -> str:
    safe_name = repo_full_name.replace("/", "__")
    return os.path.join(CLONE_BASE_DIR, safe_name)
 
 
def _remove_readonly(func, path, _exc_info):
    """
    Windows marks git's internal pack files as read-only, which blocks normal
    deletion. This clears that flag and retries -- a well-known workaround
    for GitPython + shutil.rmtree on Windows specifically.
    """
    os.chmod(path, stat.S_IWRITE)
    func(path)
 
 
def ensure_repo_cloned(repo_full_name: str, clone_url: str, installation_token: str) -> str:
    """
    Make sure we have a local, up-to-date clone of this repo.
    Returns the local path where the repo now lives.
    """
    local_path = _local_path_for_repo(repo_full_name)
 
    authenticated_url = clone_url.replace(
        "https://", f"https://x-access-token:{installation_token}@"
    )
 
    if os.path.exists(local_path):
        try:
            repo = Repo(local_path)
            repo.remotes.origin.set_url(authenticated_url)
            repo.remotes.origin.pull()
            return local_path
        except Exception as e:
            print(f"Existing clone failed to update ({e}), re-cloning from scratch.")
            shutil.rmtree(local_path, onerror=_remove_readonly)
 
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
    top-level function or class.
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
                "start_line": node.start_point[0] + 1,
                "end_line": node.end_point[0] + 1,
                "code": source_bytes[node.start_byte:node.end_byte].decode("utf-8"),
            })
            return
        for child in node.children:
            walk(child)
 
    walk(root_node)
    return chunks
 
 
def _index_paths_for_repo(repo_full_name: str) -> tuple[str, str]:
    """Returns (faiss_index_path, metadata_path) for a given repo."""
    safe_name = repo_full_name.replace("/", "__")
    os.makedirs(INDEX_BASE_DIR, exist_ok=True)
    index_path = os.path.join(INDEX_BASE_DIR, f"{safe_name}.faiss")
    metadata_path = os.path.join(INDEX_BASE_DIR, f"{safe_name}_metadata.pkl")
    return index_path, metadata_path
 
 
def index_repository(repo_full_name: str, local_repo_path: str) -> int:
    """
    Walk every Python file in a cloned repo, chunk each one, and store all
    the chunks together as one searchable FAISS index for this repo.
    """
    SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", "node_modules", ".pytest_cache"}
 
    all_chunks = []
 
    for root, dirs, files in os.walk(local_repo_path):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
 
        for filename in files:
            if not filename.endswith(".py"):
                continue
 
            full_path = os.path.join(root, filename)
            relative_path = os.path.relpath(full_path, local_repo_path)
 
            if is_sensitive_file(relative_path):
                print(f"Skipping sensitive file, not indexing: {relative_path}")
                continue
 
            try:
                chunks = chunk_python_file(full_path)
            except Exception as e:
                print(f"Skipping {relative_path}, failed to parse: {e}")
                continue
 
            for chunk in chunks:
                chunk["file_path"] = relative_path
            all_chunks.extend(chunks)
 
    embed_and_store_chunks(repo_full_name, all_chunks)
    return len(all_chunks)
 
 
def embed_and_store_chunks(repo_full_name: str, all_chunks: list[dict]) -> None:
    """
    Turn a list of code chunks into embeddings (via Gemini's remote
    embedding API -- no local model loaded) and save them in a FAISS
    index on disk, along with their metadata.
    """
    if not all_chunks:
        return
 
    code_texts = [chunk["code"] for chunk in all_chunks]
    embeddings = embed_texts(code_texts)
    embeddings = np.array(embeddings, dtype="float32")
 
    dimension = embeddings.shape[1]
    index = faiss.IndexFlatL2(dimension)
    index.add(embeddings)
 
    index_path, metadata_path = _index_paths_for_repo(repo_full_name)
    faiss.write_index(index, index_path)
 
    # Bandit flags pickle as unsafe for untrusted data (B301) -- this is
    # safe here because this file is generated entirely by our own
    # embed_and_store_chunks() function, never from user-uploaded or
    # externally-sourced data.
    with open(metadata_path, "wb") as f:
        pickle.dump(all_chunks, f)
 
 
def search_similar_chunks(repo_full_name: str, query_code: str, top_k: int = 5) -> list[dict]:
    """
    Given a piece of code, find the most semantically similar chunks
    already indexed for this repo.
    """
    index_path, metadata_path = _index_paths_for_repo(repo_full_name)
 
    if not os.path.exists(index_path):
        return []
 
    index = faiss.read_index(index_path)
    with open(metadata_path, "rb") as f:
        all_chunks = pickle.load(f)
 
    query_embedding = embed_texts([query_code])
    query_embedding = np.array(query_embedding, dtype="float32")
 
    distances, indices = index.search(query_embedding, min(top_k, len(all_chunks)))
 
    results = []
    for idx, distance in zip(indices[0], distances[0]):
        chunk = all_chunks[idx].copy()
        chunk["similarity_distance"] = float(distance)
        results.append(chunk)
 
    return results