"""
Standalone test for the security agent.

Uses deliberately insecure code so we can verify that
the agent catches real security issues.
"""

from app.agents.security_agent import run_security_agent


fake_diff = """
diff --git a/app/payments.py b/app/payments.py
+ API_KEY = "PLACEHOLDER_HARDCODED_SECRET_DO_NOT_USE_12345"
+
+ def get_user_by_name(db, username):
+     query = f"SELECT * FROM users WHERE username = '{username}'"
+     return db.execute(query)
"""


findings = run_security_agent(fake_diff)

print(f"Found {len(findings)} security findings:\n")

for finding in findings:
    print(
        f"- [{finding['severity'].upper()}] "
        f"{finding['file_path']} "
        f"line {finding['line_number']}: "
        f"{finding['message']}"
    )