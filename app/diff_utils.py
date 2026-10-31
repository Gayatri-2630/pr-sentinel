"""
Helpers for reading a unified diff.

GitHub only accepts an inline review comment on a line that is part of the
diff (an added line or an unchanged context line inside a hunk). Anything
else makes the API reject the comment, so we work out the valid lines first.
"""

import re

_HUNK_HEADER = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def commentable_lines(diff_text: str) -> dict[str, set[int]]:
    """Return {file_path: {line numbers on the NEW side that can be commented on}}."""
    result: dict[str, set[int]] = {}
    current_path = None
    new_line = 0
    in_hunk = False

    for raw in diff_text.splitlines():
        if raw.startswith("diff --git "):
            current_path = None
            in_hunk = False
            continue

        if not in_hunk:
            if raw.startswith("+++ "):
                target = raw[4:].split("\t")[0].strip()
                if target == "/dev/null":
                    current_path = None
                else:
                    current_path = target[2:] if target.startswith("b/") else target
                    result.setdefault(current_path, set())
                continue
            match = _HUNK_HEADER.match(raw)
            if match and current_path is not None:
                new_line = int(match.group(1))
                in_hunk = True
            continue

        # Inside a hunk.
        match = _HUNK_HEADER.match(raw)
        if match:
            new_line = int(match.group(1))
            continue
        if raw.startswith("\\"):          # "\ No newline at end of file"
            continue
        if raw.startswith("-"):           # removed line: not on the new side
            continue
        if current_path is not None and (raw.startswith("+") or raw.startswith(" ") or raw == ""):
            result[current_path].add(new_line)
            new_line += 1

    return result