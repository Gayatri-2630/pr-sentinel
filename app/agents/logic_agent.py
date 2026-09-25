"""
Logic agent for PR Sentinel.

Looks for likely bugs in the added lines of a diff -- incorrect
conditionals, off-by-one errors, unhandled None/null cases, and similar
logic mistakes. Deliberately separate from the Security agent so each
agent's prompt stays narrowly focused on one kind of concern.
"""

import json

from app.llm_client import call_llm

LOGIC_PROMPT_TEMPLATE = """
You are a software code-review assistant inside an automated
pull-request review system.

Inspect ONLY the added lines beginning with "+" in the supplied diff.

Identify likely LOGIC bugs, such as:

1. Off-by-one errors in loops or index/slice operations.
2. A value that could be None/null being used without a check
   (e.g. calling a method on it, or indexing into it).
3. A conditional that looks like it inverts the intended logic
   (e.g. using "==" where "!=" was likely intended, or vice versa).
4. An unhandled edge case (e.g. dividing without checking for zero,
   accessing a list/dict without checking it's non-empty).
5. A loop or recursive call that appears to have no valid exit condition.

Only report something if you can point to a SPECIFIC line and give a
concrete, plausible reason it's a bug -- do not report vague style
opinions or things that are merely unusual but correct.

Return ONLY a JSON array.
Do not use markdown.
Do not explain your reasoning outside the JSON.
Do not include any text outside the JSON array.

Each finding MUST contain exactly these fields:

{{
  "file_path": "string",
  "line_number": integer,
  "severity": "low | medium | high | critical",
  "message": "short factual description of the specific bug"
}}

If there are no matches, return:

[]

DIFF:

{diff_text}
"""


def run_logic_agent(diff_text: str) -> list[dict]:
    prompt = LOGIC_PROMPT_TEMPLATE.format(diff_text=diff_text)

    raw_response = call_llm(prompt, agent_type="logic")

    try:
        findings = json.loads(raw_response)

        if not isinstance(findings, list):
            print("Logic agent returned JSON, but it was not a list.")
            return []

        return findings

    except json.JSONDecodeError:
        print("Logic agent returned invalid JSON:", raw_response[:500])
        return []
