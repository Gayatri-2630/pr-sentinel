"""
Self-verification pass for PR Sentinel.
 
Takes the raw findings from the three agents and, for each one, asks a
fresh LLM call: "given the actual diff, is this a real, legitimate issue,
or a false positive?" This catches cases where an agent technically
followed its instructions but flagged something that isn't actually a
problem in context -- a well-known weak point in single-pass LLM analysis.
"""
 
import json
 
from app.llm_client import call_llm
 
VERIFICATION_PROMPT_TEMPLATE = """
You are double-checking a finding that another automated reviewer
produced, to confirm whether it is a genuine, legitimate issue or a
false positive.
 
ORIGINAL DIFF:
{diff_text}
 
FINDING TO VERIFY:
File: {file_path}
Line: {line_number}
Severity: {severity}
Claim: {message}
 
Based on the actual diff above, is this claim accurate and does it
describe a real issue? Consider whether the described problem genuinely
exists in the code as shown -- not whether it's merely plausible-sounding.
 
Respond ONLY with a JSON object (no other text, no markdown fences) with
exactly these fields:
 
{{
  "verified": true or false,
  "reason": "one short sentence explaining your decision"
}}
"""
 
 
def verify_finding(diff_text: str, finding: dict) -> dict:
    """
    Check one finding against the original diff. Returns the same finding
    dict with "verified" (bool) and "verification_reason" (str) added.
    Fails safe: if verification itself errors out, we mark it unverified
    rather than silently trusting an unchecked finding.
    """
    prompt = VERIFICATION_PROMPT_TEMPLATE.format(
        diff_text=diff_text,
        file_path=finding.get("file_path", "unknown"),
        line_number=finding.get("line_number", "unknown"),
        severity=finding.get("severity", "unknown"),
        message=finding.get("message", ""),
    )
 
    try:
        raw_response = call_llm(prompt)
        result = json.loads(raw_response)
 
        # Gemini sometimes wraps the answer in a list (e.g. [{"verified": true, ...}])
        # instead of a bare object -- handle both shapes rather than assuming one.
        if isinstance(result, list):
            result = result[0] if result else {}
 
        finding["verified"] = bool(result.get("verified", False))
        finding["verification_reason"] = result.get("reason", "")
    except Exception as e:
        print(f"Verification failed for a finding, marking unverified: {e}")
        finding["verified"] = False
        finding["verification_reason"] = "Verification step failed to run."
 
    return finding
 
 
def verify_all_findings(diff_text: str, findings: list[dict]) -> list[dict]:
    """Run verification on every finding in the list, one at a time."""
    return [verify_finding(diff_text, finding) for finding in findings]
 