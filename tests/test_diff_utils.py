from app.diff_utils import commentable_lines

DIFF = "\n".join([
    "diff --git a/app/x.py b/app/x.py",
    "index 111..222 100644",
    "--- a/app/x.py",
    "+++ b/app/x.py",
    "@@ -1,3 +1,4 @@",
    " import os",
    "+import pickle",
    " ",
    " def f():",
    "@@ -10,2 +11,3 @@ def g():",
    "     a = 1",
    "-    b = 2",
    "+    b = 3",
    "+    c = 4",
])


def test_added_and_context_lines_are_commentable():
    assert commentable_lines(DIFF) == {"app/x.py": {1, 2, 3, 4, 11, 12, 13}}


def test_removed_lines_are_not_counted():
    # The removed line "b = 2" must not shift numbering: new lines are 11, 12, 13.
    lines = commentable_lines(DIFF)["app/x.py"]
    assert 14 not in lines


def test_new_file():
    diff = "\n".join([
        "diff --git a/new.py b/new.py",
        "new file mode 100644",
        "--- /dev/null",
        "+++ b/new.py",
        "@@ -0,0 +1,2 @@",
        "+a = 1",
        "+b = 2",
    ])
    assert commentable_lines(diff) == {"new.py": {1, 2}}


def test_deleted_file_has_nothing_to_comment_on():
    diff = "\n".join([
        "diff --git a/old.py b/old.py",
        "deleted file mode 100644",
        "--- a/old.py",
        "+++ /dev/null",
        "@@ -1,2 +0,0 @@",
        "-a = 1",
        "-b = 2",
    ])
    assert commentable_lines(diff) == {}


def test_multiple_files_are_kept_separate():
    diff = "\n".join([
        "diff --git a/a.py b/a.py",
        "--- a/a.py",
        "+++ b/a.py",
        "@@ -1 +1 @@",
        "-x = 1",
        "+x = 2",
        "diff --git a/b.py b/b.py",
        "--- a/b.py",
        "+++ b/b.py",
        "@@ -5 +5,2 @@",
        " y = 1",
        "+z = 2",
    ])
    assert commentable_lines(diff) == {"a.py": {1}, "b.py": {5, 6}}


def test_no_newline_marker_is_ignored():
    diff = "\n".join([
        "diff --git a/a.py b/a.py",
        "--- a/a.py",
        "+++ b/a.py",
        "@@ -1 +1 @@",
        "-x = 1",
        "\\ No newline at end of file",
        "+x = 2",
        "\\ No newline at end of file",
    ])
    assert commentable_lines(diff) == {"a.py": {1}}


def test_empty_diff():
    assert commentable_lines("") == {}