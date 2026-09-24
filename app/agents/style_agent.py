"""
Style agent for PR Sentinel.

Looks for style and best-practice issues in the added lines of a diff --
poor naming, overly long/complex functions, missing docstrings on public
functions, and obvious duplicated logic. Lower stakes than Security or
Logic findings, so severities here should rarely go above "medium."
"""

import json

from app.llm_client import call_llm

STYLE_PROMPT_TEMPLATE = """
You are a software code-review assistant inside an automated
pull-request review system.

Inspect ONLY the added lines beginning with "+" in the supplied diff.

Identify STYLE and best-practice issues, such as:

1. Unclear or misleading variable/function names (e.g. single letters
   outside of short loop counters, or names that don't match what the
   code actually does).
2. A function that is doing clearly too many distinct things and should
   likely be split up.
3. A public function with no docstring explaining what it does.
4. Obvious duplicated logic that appears more than once and could be
   extracted into a shared helper.
5. Magic numbers or strings used directly in logic without being named
   as a constant.

These are lower-stakes than security or logic bugs -- use "low" or
"medium" severity almost always. Only use "high" for something that
would seriously hurt readability or maintainability.

Return ONLY a JSON array.
Do not use markdown.
Do not explain your reasoning outside the JSON.
Do not include any text outside the JSON array.

Each finding MUST contain exactly these fields:

{{
  "file_path": "string",
  "line_number": integer,
  "severity": "low | medium | high | critical",
  "message": "short factual description of the specific issue"
}}

If there are no matches, return:

[]

DIFF:

{diff_text}
"""


def run_style_agent(diff_text: str) -> list[dict]:
    prompt = STYLE_PROMPT_TEMPLATE.format(diff_text=diff_text)

    raw_response = call_llm(prompt, agent_type="style")

    try:
        findings = json.loads(raw_response)

        if not isinstance(findings, list):
            print("Style agent returned JSON, but it was not a list.")
            return []

        return findings

    except json.JSONDecodeError:
        print("Style agent returned invalid JSON:", raw_response[:500])
        return []
