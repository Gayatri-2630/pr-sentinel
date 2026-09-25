# Use a specific, pinned Python version -- avoids the "works on my
# machine but not in Docker" surprises we hit locally with mismatched
# Python versions (3.14 vs 3.12) earlier in this project.
FROM python:3.12-slim

# System dependencies needed by our stack:
# - git: required by GitPython (code_indexer.py clones repos)
# - build-essential: some Python packages need a C compiler to install
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy just requirements first, install them, THEN copy the rest of the
# code. This ordering matters: Docker caches each step, so as long as
# requirements.txt doesn't change, re-building after a code change reuses
# the cached (slow) dependency-install step instead of redoing it.
# Install PyTorch's CPU-only build FIRST -- avoids pip pulling in the
# full GPU/CUDA build (2GB+ of unnecessary NVIDIA libraries) that
# sentence-transformers would otherwise trigger. We only need CPU-based
# embeddings, never a GPU, inside this container.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# In production, uvicorn runs WITHOUT --reload (that's a dev-only feature)
# and binds to 0.0.0.0 so it's reachable from outside the container.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
