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
# code -- so Docker can reuse the cached dependency-install step as long
# as requirements.txt doesn't change.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
 
COPY . .
 
EXPOSE 8000
 
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]