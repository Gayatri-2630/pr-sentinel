"""
Standalone test for the orchestrator -- one diff containing a security
issue, a logic bug, AND a style issue, to confirm all three agents run
and their findings come back correctly tagged and merged.
"""

from app.agents.orchestrator import run_all_agents

fake_diff = """
diff --git a/app/mixed.py b/app/mixed.py
+ def x(user, n):
+     API_KEY = "PLACEHOLDER_HARDCODED_SECRET_DO_NOT_USE_12345"
+     items = user.get_items()
+     return items[len(items) - n - 1:]
"""

findings = run_all_agents(fake_diff)

print(f"Found {len(findings)} total findings across all agents:\n")

for finding in findings:
    print(
        f"- [{finding['agent_type'].upper()}] "
        f"[{finding['severity'].upper()}] "
        f"{finding['file_path']} line {finding['line_number']}: "
        f"{finding['message']}"
    )
