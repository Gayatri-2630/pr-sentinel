"""
Handles getting a local, up-to-date copy of a repo's code so we can read
more than just the diff -- this is the foundation for our RAG pipeline.
"""
 
import os
import pickle
import shutil
 
import faiss
import numpy as np
from git import Repo
from sentence_transformers import SentenceTransformer
from tree_sitter import Language, Parser
import tree_sitter_python as tspython
 
# Where we'll keep local clones. Each repo gets its own subfolder, named
# after its full_name with the slash replaced (GitHub repo names can't
# contain colons or other path-unsafe characters, so this is safe).
CLONE_BASE_DIR = "./repo_clones"
INDEX_BASE_DIR = "./vector_indexes"
 
# Set up the tree-sitter parser once, at import time, so we don't rebuild
# it on every single file we parse.
PY_LANGUAGE = Language(tspython.language())
_parser = Parser(PY_LANGUAGE)
 
# The kinds of tree-sitter nodes we consider "a chunk worth indexing."
# Functions and classes are the meaningful units of code most reviewers
# actually reason about -- not arbitrary line counts.
CHUNKABLE_NODE_TYPES = {"function_definition", "class_definition"}
 
# A small, fast, free, locally-run embedding model -- no API key or cost.
# 384-dimensional vectors, good enough for code similarity at this scale.
_embedding_model = SentenceTransformer("all-MiniLM-L6-v2")
 
 
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
 
 
def _index_paths_for_repo(repo_full_name: str) -> tuple[str, str]:
    """Returns (faiss_index_path, metadata_path) for a given repo."""
    safe_name = repo_full_name.replace("/", "__")
    os.makedirs(INDEX_BASE_DIR, exist_ok=True)
    index_path = os.path.join(INDEX_BASE_DIR, f"{safe_name}.faiss")
    metadata_path = os.path.join(INDEX_BASE_DIR, f"{safe_name}_metadata.pkl")
    return index_path, metadata_path
 
 
def embed_and_store_chunks(repo_full_name: str, all_chunks: list[dict]) -> None:
    """
    Turn a list of code chunks into embeddings and save them in a FAISS
    index on disk, along with their metadata (name, file, line range) so
    we can map a search result back to actual readable information.
    """
    if not all_chunks:
        return
 
    code_texts = [chunk["code"] for chunk in all_chunks]
    embeddings = _embedding_model.encode(code_texts, show_progress_bar=False)
    embeddings = np.array(embeddings, dtype="float32")
 
    dimension = embeddings.shape[1]  # 384 for this model
    index = faiss.IndexFlatL2(dimension)  # simple, exact nearest-neighbor search
    index.add(embeddings)
 
    index_path, metadata_path = _index_paths_for_repo(repo_full_name)
    faiss.write_index(index, index_path)
 
    with open(metadata_path, "wb") as f:
        pickle.dump(all_chunks, f)
 
 
def search_similar_chunks(repo_full_name: str, query_code: str, top_k: int = 5) -> list[dict]:
    """
    Given a piece of code (e.g. from a PR diff), find the most semantically
    similar chunks already indexed for this repo -- this is the actual
    'retrieval' in Retrieval-Augmented Generation.
    """
    index_path, metadata_path = _index_paths_for_repo(repo_full_name)
 
    if not os.path.exists(index_path):
        return []  # repo hasn't been indexed yet
 
    index = faiss.read_index(index_path)
    with open(metadata_path, "rb") as f:
        all_chunks = pickle.load(f)
 
    query_embedding = _embedding_model.encode([query_code], show_progress_bar=False)
    query_embedding = np.array(query_embedding, dtype="float32")
 
    distances, indices = index.search(query_embedding, min(top_k, len(all_chunks)))
 
    results = []
    for idx, distance in zip(indices[0], distances[0]):
        chunk = all_chunks[idx].copy()
        chunk["similarity_distance"] = float(distance)  # lower = more similar
        results.append(chunk)
 
    return results