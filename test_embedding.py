"""
Standalone test for the embedding + FAISS search pipeline.
Run this directly -- no webhook or GitHub event needed.
"""

from app.code_indexer import chunk_python_file, embed_and_store_chunks, search_similar_chunks

# Step 1: chunk a real file (reuse crud.py, has 4 distinct functions)
chunks = chunk_python_file("app/crud.py")
print(f"Chunked {len(chunks)} functions from app/crud.py")

# Step 2: embed and store them in FAISS, tagged under a test repo name
embed_and_store_chunks("test/fake-repo", chunks)
print("Embedded and stored in FAISS.\n")

# Step 3: search using a NEW piece of code we didn't index, but which is
# conceptually similar to one specific function -- creating something new.
query = """
def make_new_widget(db, name, color):
    widget = Widget(name=name, color=color)
    db.add(widget)
    db.commit()
    db.refresh(widget)
    return widget
"""

results = search_similar_chunks("test/fake-repo", query, top_k=2)

print("Top matches for a new 'create a thing in the database' function:\n")
for r in results:
    print(f"- {r['name']} (distance: {r['similarity_distance']:.4f})")
