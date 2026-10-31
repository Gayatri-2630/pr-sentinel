"""Test setup: fake credentials so modules import without a real .env."""
import os

os.environ.setdefault("GEMINI_API_KEY", "test-key-not-real")
os.environ.setdefault("GITHUB_WEBHOOK_SECRET", "test-webhook-secret")
