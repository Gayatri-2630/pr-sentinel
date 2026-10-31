"""
Test setup. Runs before any app code is imported.

- Fake credentials so modules import without a real .env.
- The database is ALWAYS a throwaway SQLite file, so tests can never touch
  the real (Neon) database even if DATABASE_URL is set in your shell or .env.
"""
import os
import tempfile
from pathlib import Path

os.environ.setdefault("GEMINI_API_KEY", "test-key-not-real")
os.environ["GITHUB_WEBHOOK_SECRET"] = "test-webhook-secret"

_db_file = Path(tempfile.gettempdir()) / "pr_sentinel_pytest.db"
try:
    _db_file.unlink()
except FileNotFoundError:
    pass
os.environ["DATABASE_URL"] = f"sqlite:///{_db_file.as_posix()}"