"""
Orchestrator for PR Sentinel's multi-agent analysis layer.
 
Runs the Security, Logic, and Style AI agents PLUS deterministic static
analysis tools (bandit, pylint) on the same diff/repo, tags every finding
with its source, then runs self-verification ONLY on the AI-generated
findings -- static analysis tools are rule-based and don't hallucinate,
so LLM-verifying them wastes API quota for no real benefit.
 
Also tracks AI availability explicitly: if Gemini's quota is exhausted,
that's surfaced clearly as a status, not just buried in log lines --
PR Sentinel should still deliver full static-analysis results even when
the AI layer is temporarily unavailable.
"""
 
from app.agents.logic_agent import run_logic_agent
from app.agents.security_agent import run_security_agent
from app.agents.style_agent import run_style_agent
from app.agents.verifier import verify_all_findings
from app.llm_client import LLMQuotaExhaustedError
from app.static_analysis import run_bandit, run_pylint
 
 
def run_all_agents(diff_text: str, repo_path: str = None) -> tuple[list[dict], dict]:
    """
    Run all three AI agents on the diff, plus bandit/pylint on the full
    repo if a local path is given. Only AI findings go through the
    verification pass; static analysis findings are trusted as-is.
 
    Returns (findings, ai_status) where ai_status is a dict like:
        {"security": "ok", "logic": "quota_exhausted", "style": "ok"}
    so callers can build a clear picture of what actually ran.
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
        except Exception as e:
            print(f"{agent_type} agent failed with an error: {e}")
            ai_status[agent_type] = "error"
            findings = []
 
        for finding in findings:
            finding["agent_type"] = agent_type
 
        ai_findings.extend(findings)
 
    static_findings = []
    if repo_path:
        for tool_name, tool_function in [("bandit", run_bandit), ("pylint", run_pylint)]:
            try:
                tool_findings = tool_function(repo_path)
            except Exception as e:
                print(f"{tool_name} failed with an error: {e}")
                tool_findings = []
            static_findings.extend(tool_findings)
 
    # Only verify AI findings if at least one AI agent actually produced
    # something -- no point calling the verifier at all if every agent
    # failed (saves API calls when quota is already exhausted).
    if ai_findings:
        verified_ai_findings = verify_all_findings(diff_text, ai_findings)
    else:
        verified_ai_findings = []
 
    for finding in static_findings:
        finding["verified"] = True
        finding["verification_reason"] = "Deterministic static analysis tool -- not run through LLM verification."
 
    all_findings = verified_ai_findings + static_findings
    return all_findings, ai_status