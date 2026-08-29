"""
Quick standalone test -- run this directly to confirm chunk_python_file()
actually works, before we wire it into the full webhook flow.
"""

from app.code_indexer import chunk_python_file

# Point this at any real Python file with a few functions/classes in it.
# Your own crud.py is a good test case -- it has 4 distinct functions.
chunks = chunk_python_file("app/crud.py")

print(f"Found {len(chunks)} chunks:\n")

for chunk in chunks:
    print(f"- {chunk['type']}: {chunk['name']} (lines {chunk['start_line']}-{chunk['end_line']})")
