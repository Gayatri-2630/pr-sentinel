"""
Standalone test for the style agent -- using deliberately poor naming
and a missing docstring to confirm real detection.
"""

from app.agents.style_agent import run_style_agent

fake_diff = """
diff --git a/app/calc.py b/app/calc.py
+ def x(a, b, c, d):
+     r = a * b
+     if c == 1:
+         r = r + d
+     return r
"""

findings = run_style_agent(fake_diff)

print(f"Found {len(findings)} style findings:\n")

for finding in findings:
    print(
        f"- [{finding['severity'].upper()}] "
        f"{finding['file_path']} "
        f"line {finding['line_number']}: "
        f"{finding['message']}"
    )
