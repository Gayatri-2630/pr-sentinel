"""
Orchestrator for PR Sentinel's multi-agent analysis layer.
 
Runs the Security, Logic, and Style agents on the same diff, tags each
finding with which agent produced it, and merges everything into one
combined list. This is the single entry point main.py will call, instead
of calling each agent separately.
"""
 
from app.agents.logic_agent import run_logic_agent
from app.agents.security_agent import run_security_agent
from app.agents.style_agent import run_style_agent
from app.agents.verifier import verify_all_findings
 
 
def run_all_agents(diff_text: str) -> list[dict]:
    """
    Run all three agents on the same diff, tag and merge their findings,
    then run every finding through the self-verification pass before
    returning them.
    """
    agent_runs = [
        ("security", run_security_agent),
        ("logic", run_logic_agent),
        ("style", run_style_agent),
    ]
 
    all_findings = []
 
    for agent_type, agent_function in agent_runs:
        try:
            findings = agent_function(diff_text)
        except Exception as e:
            # One agent failing (e.g. a transient API error) shouldn't
            # take down the other two -- log it and keep going.
            print(f"{agent_type} agent failed with an error: {e}")
            findings = []
 
        for finding in findings:
            finding["agent_type"] = agent_type
 
        all_findings.extend(findings)
 
    verified_findings = verify_all_findings(diff_text, all_findings)
    return verified_findings