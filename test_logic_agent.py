"""
Standalone test for the logic agent -- using deliberately buggy code
(an off-by-one error and a missing None check) to confirm real detection.
"""

from app.agents.logic_agent import run_logic_agent

fake_diff = """
diff --git a/app/utils.py b/app/utils.py
+ def get_last_n_items(items, n):
+     return items[len(items) - n - 1:]
+
+ def get_user_email(user):
+     return user.profile.email.lower()
"""

findings = run_logic_agent(fake_diff)

print(f"Found {len(findings)} logic findings:\n")

for finding in findings:
    print(
        f"- [{finding['severity'].upper()}] "
        f"{finding['file_path']} "
        f"line {finding['line_number']}: "
        f"{finding['message']}"
    )
