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
 
# A simple in-memory log of every LLM call made during the current request.
# main.py reads and clears this after each webhook run, then saves it to
# Postgres. Good enough for our single-request-at-a-time scale; a busier
# production system would use a request-scoped context instead of a
# module-level list.
_usage_log = []
 
 
def get_and_clear_usage_log() -> list[dict]:
    """Return everything logged so far, and reset the log for the next run."""
    global _usage_log
    log_copy = _usage_log
    _usage_log = []
    return log_copy
 
 
def call_llm(prompt: str, agent_type: str = "unknown") -> str:
    """
    Send a prompt to Gemini and return its text response.
    Retries on transient server-side errors (like 503 "high demand"),
    since these are common and usually resolve within a few seconds --
    not something we want to just give up on immediately.
 
    Every call (successful or not) gets recorded in _usage_log, tagged
    with which agent made it -- this is what feeds the llm_usage table.
    """
    last_error = None
 
    for attempt in range(1, MAX_RETRIES + 1):
        start_time = time.time()
        try:
            response = _client.models.generate_content(
                model=MODEL_NAME,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                ),
            )
            latency_ms = int((time.time() - start_time) * 1000)
 
            usage = getattr(response, "usage_metadata", None)
            input_tokens = getattr(usage, "prompt_token_count", 0) if usage else 0
            output_tokens = getattr(usage, "candidates_token_count", 0) if usage else 0
 
            _usage_log.append({
                "agent_type": agent_type,
                "model": MODEL_NAME,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "latency_ms": latency_ms,
                "cost_estimate": 0.0,  # Gemini free tier -- no real cost to track yet
            })
 
            return response.text
        except Exception as e:
            last_error = e
            is_transient = "503" in str(e) or "UNAVAILABLE" in str(e)
            if is_transient and attempt < MAX_RETRIES:
                print(f"Transient API error (attempt {attempt}/{MAX_RETRIES}), retrying in {RETRY_DELAY_SECONDS}s...")
                time.sleep(RETRY_DELAY_SECONDS)
                continue
            raise last_error