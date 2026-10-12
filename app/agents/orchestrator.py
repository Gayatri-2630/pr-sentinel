"""
Orchestrator for PR Sentinel's analysis layer.
 
Runs the Security, Logic and Style AI agents on the diff, plus deterministic
static analysis (bandit, pylint) on the Python files that the PR changed.
Only AI-generated findings go through the LLM verification pass; static
analysis tools are rule-based and don't hallucinate, so verifying them
would waste API quota for no benefit.
 
AI availability is tracked explicitly: if the LLM provider is down or out
of quota, that is reported as a status, and static analysis still delivers
its results.
"""
 
from app.agents.logic_agent import run_logic_agent
from app.agents.security_agent import run_security_agent
from app.agents.style_agent import run_style_agent
from app.agents.verifier import verify_all_findings
from app.llm_client import LLMQuotaExhaustedError
from app.static_analysis import extract_changed_python_files, run_bandit, run_pylint
 
 
def run_all_agents(diff_text: str, repo_path: str = None) -> tuple[list[dict], dict]:
    """
    Returns (findings, ai_status), where ai_status looks like
    {"security": "ok", "logic": "quota_exhausted", "style": "error"}.
    """
    agent_runs = [
        ("security", run_security_agent),
        ("logic", run_logic_agent),
        ("style", run_style_agent),
    ]
 
    ai_findings = []
    ai_status = {}
 
    for agent_type, agent_function in agent_runs:
        try:
            findings = agent_function(diff_text)
            ai_status[agent_type] = "ok"
        except LLMQuotaExhaustedError as e:
            print(f"{agent_type} agent unavailable -- Gemini quota exhausted: {e}")
            ai_status[agent_type] = "quota_exhausted"
            findings = []
        except Exception as e:  # pylint: disable=broad-exception-caught
            print(f"{agent_type} agent failed with an error: {e}")
            ai_status[agent_type] = "error"
            findings = []
 
        for finding in findings:
            finding["agent_type"] = agent_type
 
        ai_findings.extend(findings)
 
    static_findings = []
    if repo_path:
        # Scan only what this PR touched, not the whole repository.
        changed_files = extract_changed_python_files(diff_text)
        print(f"Static analysis scope: {len(changed_files)} changed Python file(s).")
 
        if changed_files:
            for tool_name, tool_function in [("bandit", run_bandit), ("pylint", run_pylint)]:
                try:
                    tool_findings = tool_function(repo_path, changed_files)
                except Exception as e:  # pylint: disable=broad-exception-caught
                    print(f"{tool_name} failed with an error: {e}")
                    tool_findings = []
                static_findings.extend(tool_findings)
 
    # No point calling the verifier if no AI agent produced anything.
    if ai_findings:
        verified_ai_findings = verify_all_findings(diff_text, ai_findings)
    else:
        verified_ai_findings = []
 
    for finding in static_findings:
        finding["verified"] = True
        finding["verification_reason"] = "Deterministic static analysis tool -- not run through LLM verification."
 
    return verified_ai_findings + static_findings, ai_status