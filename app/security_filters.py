"""
Basic secret scanning -- redacts text that looks like a real secret
(API keys, tokens, etc.) before it's ever sent to an LLM. This is a
safety net, not a replacement for proper secret management: even if a
developer accidentally commits a real credential, it should never leave
our system and reach a third-party API.
"""
 
import re
 
# Each pattern matches a common, recognizable secret FORMAT (not just a
# suspicious variable name) -- reduces false positives on normal code.
SECRET_PATTERNS = [
    (r"AKIA[0-9A-Z]{16}", "AWS_ACCESS_KEY"),                          # AWS access key ID
    (r"sk-[a-zA-Z0-9]{20,}", "API_KEY_SK_PREFIX"),                    # OpenAI/Stripe-style sk- keys
    (r"ghp_[a-zA-Z0-9]{30,}", "GITHUB_TOKEN"),                         # GitHub personal access token
    (r"eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}", "JWT_TOKEN"),  # JWTs
    (r"-----BEGIN (RSA |EC )?PRIVATE KEY-----", "PRIVATE_KEY_BLOCK"),  # PEM private key headers
]
 
 
def redact_secrets(text: str) -> str:
    """
    Scan text for known secret formats and replace them with a clear
    placeholder, e.g. [REDACTED_AWS_ACCESS_KEY]. Safe to call on any
    diff/code text before it's included in a prompt.
    """
    redacted_text = text
    for pattern, label in SECRET_PATTERNS:
        redacted_text = re.sub(pattern, f"[REDACTED_{label}]", redacted_text)
    return redacted_text