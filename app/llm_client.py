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
THINKING_LEVEL = os.getenv("LLM_THINKING_LEVEL", "minimal")  # "default" turns this off
INPUT_USD_PER_M = 0.75
OUTPUT_USD_PER_M = 3.75
 
EMBEDDING_MODEL_NAME = "gemini-embedding-001"
 
if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY is not set in .env")
 
_client = genai.Client(
    api_key=GEMINI_API_KEY,
    http_options=types.HttpOptions(timeout=60_000),
)
 
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
                    thinking_config=(
                        None if THINKING_LEVEL == "default"
                        else types.ThinkingConfig(thinking_level=THINKING_LEVEL)
                    ),
                ),
            )
            latency_ms = int((time.time() - start_time) * 1000)
 
            usage = getattr(response, "usage_metadata", None)
            input_tokens = (getattr(usage, "prompt_token_count", 0) or 0) if usage else 0
            answer_tokens = (getattr(usage, "candidates_token_count", 0) or 0) if usage else 0
            thought_tokens = (getattr(usage, "thoughts_token_count", 0) or 0) if usage else 0
            output_tokens = answer_tokens + thought_tokens  # thinking is billed as output
            cost_usd = (input_tokens * INPUT_USD_PER_M + output_tokens * OUTPUT_USD_PER_M) / 1_000_000

            _usage_log.append({
                "agent_type": agent_type,
                "model": MODEL_NAME,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "latency_ms": latency_ms,
                "cost_estimate": round(cost_usd, 6),
            })
 
            return response.text
 
        except Exception as e:
            error_message = str(e)
            last_error = e
 
            is_quota_429 = "429" in error_message or "RESOURCE_EXHAUSTED" in error_message
            is_transient_503 = (
                "503" in error_message
                or "UNAVAILABLE" in error_message
                or "disconnected" in error_message.lower()
                or "timed out" in error_message.lower()
                or "timeout" in f"{type(e).__name__}{error_message}".lower()
            )
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
 
 
EMBEDDING_BATCH_SIZE = 20
 
 
def embed_texts(texts: list[str]) -> list[list[float]]:
    """
    Get embeddings from Gemini's remote embedding API (NOT a local model:
    loading torch + a local model exceeded the 512MB limit on Render's free
    tier). Texts are sent in batches instead of one request per text.
    If a batched request fails or returns the wrong number of vectors, we
    fall back to one request per text, so the result is always correct.
    """
    embeddings = []
    for start in range(0, len(texts), EMBEDDING_BATCH_SIZE):
        batch = texts[start:start + EMBEDDING_BATCH_SIZE]
        try:
            result = _client.models.embed_content(
                model=EMBEDDING_MODEL_NAME,
                contents=batch,
            )
            vectors = [item.values for item in result.embeddings]
            if len(vectors) != len(batch):
                raise ValueError(f"expected {len(batch)} embeddings, got {len(vectors)}")
        except Exception as e:  # pylint: disable=broad-exception-caught
            print(f"Batched embedding failed ({e}); falling back to one request per chunk.")
            vectors = []
            for text in batch:
                single = _client.models.embed_content(model=EMBEDDING_MODEL_NAME, contents=text)
                vectors.append(single.embeddings[0].values)
        embeddings.extend(vectors)
    return embeddings