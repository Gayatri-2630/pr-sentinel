"""
Thin wrapper around the Gemini API.

Every agent calls Gemini through this file so model configuration
and API handling stay in one place.
"""

import os

from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MODEL_NAME = "gemini-3.6-flash"

if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY is not set in .env")

_client = genai.Client(api_key=GEMINI_API_KEY)


def call_llm(prompt: str) -> str:
    response = _client.models.generate_content(
        model=MODEL_NAME,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
        ),
    )

    return response.text