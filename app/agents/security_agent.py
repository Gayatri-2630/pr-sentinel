"""
Security agent for PR Sentinel.

Looks for specific security-sensitive coding patterns
in pull-request diffs.
"""

import json

from app.llm_client import call_llm


SECURITY_PROMPT_TEMPLATE = """
You are a software code-review assistant inside an automated
pull-request review system.

Inspect ONLY the added lines beginning with "+" in the supplied diff.

Identify these specific security-sensitive patterns:

1. Hardcoded credentials:
   A literal string assigned to a variable whose name contains
   key, secret, password, token, or credential.

2. SQL injection risk:
   A SQL query is constructed using an f-string or string
   concatenation involving a variable.

3. Unsafe execution or deserialization:
   Examples:
   eval(...)
   exec(...)
   pickle.loads(...)
   yaml.load(...) without a safe loader.

4. Unsafe filesystem path construction:
   A filesystem path is directly constructed using a function
   parameter or other potentially untrusted value.

5. Weak cryptography:
   Examples include MD5, SHA1, or DES.

For every matching pattern, return one finding.

Return ONLY a JSON array.
Do not use markdown.
Do not explain your reasoning.
Do not include any text outside the JSON array.

Each finding MUST contain exactly these fields:

{{
  "file_path": "string",
  "line_number": integer,
  "severity": "low | medium | high | critical",
  "message": "short factual description"
}}

If there are no matches, return:

[]

DIFF:

{diff_text}
"""


def run_security_agent(diff_text: str) -> list[dict]:
    prompt = SECURITY_PROMPT_TEMPLATE.format(
        diff_text=diff_text
    )

    raw_response = call_llm(prompt)

    try:
        findings = json.loads(raw_response)

        if not isinstance(findings, list):
            print("Security agent returned JSON, but it was not a list.")
            return []

        return findings

    except json.JSONDecodeError:
        print(
            "Security agent returned invalid JSON:",
            raw_response[:500]
        )
        return []