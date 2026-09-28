"""
Thin wrapper around the Gemini API.
 
Every agent calls Gemini through this file so model configuration,
retry logic, and usage tracking all stay in one place.
"""
 
import os
import time
 
from dotenv import load_dotenv
from google import genai
from google.genai import types
 
load_dotenv()
 
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MODEL_NAME = "gemini-3.6-flash"
 
# Embedding model name -- this may need adjusting once we see the real
# error/response, same as MODEL_NAME above did earlier in this project.
EMBEDDING_MODEL_NAME = "gemini-embedding-001"
 
if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY is not set in .env")
 
_client = genai.Client(api_key=GEMINI_API_KEY)
 
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 5
 
_usage_log = []
 
 
class LLMQuotaExhaustedError(Exception):
    """
    Raised when Gemini returns 429 (quota exceeded). Deliberately a
    DIFFERENT exception type than a normal API failure, so callers can
    tell "temporarily overloaded, worth retrying" apart from "out of
    quota, retrying is pointless until it resets."
    """
    pass
 
 
def get_and_clear_usage_log() -> list[dict]:
    """Return everything logged so far, and reset the log for the next run."""
    global _usage_log
    log_copy = _usage_log
    _usage_log = []
    return log_copy
 
 
def _is_daily_quota_error(error_message: str) -> bool:
    return "PerDay" in error_message
 
 
def call_llm(prompt: str, agent_type: str = "unknown") -> str:
    """
    Send a prompt to Gemini and return its text response.
 
    Retries on transient server-side errors (like 503 "high demand").
    Does NOT retry on 429 daily-quota-exhausted errors -- raises
    LLMQuotaExhaustedError immediately instead, so callers can fail fast.
 
    Every successful call gets recorded in _usage_log, tagged with which
    agent made it -- this is what feeds the llm_usage table.
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
                "cost_estimate": 0.0,
            })
 
            return response.text
 
        except Exception as e:
            error_message = str(e)
            last_error = e
 
            is_quota_429 = "429" in error_message or "RESOURCE_EXHAUSTED" in error_message
            is_transient_503 = "503" in error_message or "UNAVAILABLE" in error_message
 
            if is_quota_429:
                if _is_daily_quota_error(error_message):
                    raise LLMQuotaExhaustedError(
                        f"Gemini daily quota exhausted for {agent_type} agent."
                    ) from e
                if attempt < MAX_RETRIES:
                    print(f"Per-minute rate limit hit (attempt {attempt}/{MAX_RETRIES}), retrying in {RETRY_DELAY_SECONDS}s...")
                    time.sleep(RETRY_DELAY_SECONDS)
                    continue
                raise LLMQuotaExhaustedError(
                    f"Gemini rate limit persisted after retries for {agent_type} agent."
                ) from e
 
            if is_transient_503 and attempt < MAX_RETRIES:
                print(f"Transient API error (attempt {attempt}/{MAX_RETRIES}), retrying in {RETRY_DELAY_SECONDS}s...")
                time.sleep(RETRY_DELAY_SECONDS)
                continue
 
            raise last_error from e
 
 
def embed_texts(texts: list[str]) -> list[list[float]]:
    """
    Get embeddings for a list of texts using Gemini's remote embedding API
    -- NOT a local model. This is deliberately a remote API call, not a
    locally-loaded sentence-transformers model, because loading torch +
    a local model exceeded memory limits on constrained hosting (Render's
    free tier, 512MB RAM). A remote call trades a bit of latency for a
    much smaller, more deployable application.
    """
    embeddings = []
    for text in texts:
        result = _client.models.embed_content(
            model=EMBEDDING_MODEL_NAME,
            contents=text,
        )
        embeddings.append(result.embeddings[0].values)
    return embeddings