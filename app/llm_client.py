"""
Thin wrapper around the Gemini API.
 
Every agent calls Gemini through this file so model configuration
and API handling stay in one place.
"""
 
import os
import time
 
from dotenv import load_dotenv
from google import genai
from google.genai import types
 
load_dotenv()
 
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MODEL_NAME = "gemini-3.6-flash"
 
if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY is not set in .env")
 
_client = genai.Client(api_key=GEMINI_API_KEY)
 
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 5  # simple fixed backoff -- fine at our current call volume
 
 
def call_llm(prompt: str) -> str:
    """
    Send a prompt to Gemini and return its text response.
    Retries on transient server-side errors (like 503 "high demand"),
    since these are common and usually resolve within a few seconds --
    not something we want to just give up on immediately.
    """
    last_error = None
 
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = _client.models.generate_content(
                model=MODEL_NAME,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                ),
            )
            return response.text
        except Exception as e:
            last_error = e
            is_transient = "503" in str(e) or "UNAVAILABLE" in str(e)
            if is_transient and attempt < MAX_RETRIES:
                print(f"Transient API error (attempt {attempt}/{MAX_RETRIES}), retrying in {RETRY_DELAY_SECONDS}s...")
                time.sleep(RETRY_DELAY_SECONDS)
                continue
            raise last_error
 