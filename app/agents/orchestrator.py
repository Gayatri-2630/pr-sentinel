"""
Orchestrator for PR Sentinel's multi-agent analysis layer.
 
Runs the Security, Logic, and Style AI agents PLUS deterministic static
analysis tools (bandit, pylint) on the same diff/repo, tags every finding
with its source, merges everything into one combined list, then runs the
self-verification pass on top. This is the "hybrid AI + static analysis"
design: AI catches context-dependent issues, static tools catch known,
well-defined patterns with zero hallucination risk.
"""
 
from app.agents.logic_agent import run_logic_agent
from app.agents.security_agent import run_security_agent
from app.agents.style_agent import run_style_agent
from app.agents.verifier import verify_all_findings
from app.static_analysis import run_bandit, run_pylint
 
 
def run_all_agents(diff_text: str, repo_path: str = None) -> list[dict]:
    """
    Run AI agents plus deterministic static analysis tools.

    AI findings are sent through LLM verification.
    Static-analysis findings are trusted directly because they come
    from deterministic tools (Bandit/Pylint).
    """
    agent_runs = [
        ("security", run_security_agent),
        ("logic", run_logic_agent),
        ("style", run_style_agent),
    ]

    ai_findings = []
    static_findings = []

    # Run AI agents
    for agent_type, agent_function in agent_runs:
        try:
            findings = agent_function(diff_text)
        except Exception as e:
            print(f"{agent_type} agent failed with an error: {e}")
            findings = []

        for finding in findings:
            finding["agent_type"] = agent_type

        ai_findings.extend(findings)

    # Run deterministic static analysis
    if repo_path:
        for tool_name, tool_function in [
            ("bandit", run_bandit),
            ("pylint", run_pylint),
        ]:
            try:
                tool_findings = tool_function(repo_path)
            except Exception as e:
                print(f"{tool_name} failed with an error: {e}")
                tool_findings = []

            for finding in tool_findings:
                finding["verified"] = True
                finding["verification_reason"] = (
                    "Deterministic static analysis tool"
                )

            static_findings.extend(tool_findings)

    # Only AI-generated findings go through LLM verification.
    verified_ai_findings = verify_all_findings(diff_text, ai_findings)

    # Static findings are already trusted.
    return verified_ai_findings + static_findings