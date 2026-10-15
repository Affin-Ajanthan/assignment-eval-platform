"""Removing do-nothing code from Python before the semantic comparison
(app/similarity/python_cleanup.py) and its effect on normalize_code."""

import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.similarity.python_cleanup import strip_python_dead_code
from app.similarity.semantic import normalize_code


def clean(code: str) -> str:
    return " ".join(strip_python_dead_code(textwrap.dedent(code)).split())


ORIGINAL = textwrap.dedent('''
    def average(marks):
        total = 0
        for m in marks:
            total += m
        return total / len(marks)
''')


def test_junk_filled_copy_normalizes_like_the_original():
    copy = textwrap.dedent('''
        import os
        def average(marks):
            temp = 5
            unused_list = []
            debug = False
            total = 0
            counter = 0
            for m in marks:
                total += m
                counter += 1
            if False:
                print("never")
            return total / len(marks)
            print("unreachable")
    ''')
    assert normalize_code(copy, "a.py") == normalize_code(ORIGINAL, "a.py")


def test_unused_variable_removed_used_variable_kept():
    assert clean("def f():\n    x = 1\n    y = 2\n    print(y)") == "def f(): y = 2 print(y)"


def test_chain_of_unused_variables_is_removed_completely():
    # b is only used by a, and a is never used: both go.
    assert clean("def f():\n    b = 1\n    a = b + 1\n    print('hi')") == "def f(): print('hi')"


def test_assignments_with_side_effects_are_kept():
    assert "save()" in clean("def f():\n    x = save()")
    assert "items.pop()" in clean("def f():\n    x = items.pop()")
    assert "input()" in clean("def f():\n    name = input()")


def test_pure_builtin_call_is_removed():
    assert clean("def f(data):\n    n = len(data)\n    print(data)") == "def f(data): print(data)"


def test_unused_module_level_variables_are_removed():
    code = "LIMIT = 3\nunused_counter = 100\nunused_flag = True\ndef f():\n    return LIMIT\n"
    assert clean(code) == "LIMIT = 3 def f(): return LIMIT"


def test_module_level_name_used_by_another_file_is_kept():
    # main.py does `from config import MAX_BOOKS`: config.py alone never reads it.
    config = "MAX_BOOKS = 3\nDEBUG = False\ndef helper():\n    return 1\n"
    out = " ".join(strip_python_dead_code(config, {"MAX_BOOKS", "helper", "main"}).split())
    assert "MAX_BOOKS = 3" in out and "DEBUG" not in out


def test_file_that_would_become_empty_is_kept():
    # Only data, no code to protect: removing everything would leave nothing to compare.
    assert clean("x = 1\ny = 2") == "x = 1 y = 2"


def test_unused_imports_removed_used_ones_kept():
    assert clean("import os\nimport sys\nfrom math import sqrt, pi\nprint(sys.argv, sqrt(4))") == \
        "import sys from math import sqrt, pi print(sys.argv, sqrt(4))"
    assert clean("import os\nprint(1)") == "print(1)"
    assert clean("from os.path import *\nprint(1)").startswith("from os.path import *")


def test_dead_branches():
    assert clean("if False:\n    print('a')\nprint('b')") == "print('b')"
    assert clean("while 0:\n    print('a')\nprint('b')") == "print('b')"
    assert clean("if False:\n    print('a')\nelse:\n    print('c')") == "print('c')"
    # elif chains are left alone
    assert "elif" in clean("if False:\n    print('a')\nelif x:\n    print('c')")


def test_unreachable_statements_after_return_raise_break_continue():
    assert clean("def f():\n    return 1\n    print('x')") == "def f(): return 1"
    assert clean("for i in r:\n    continue\n    print(i)") == "for i in r: continue"
    assert clean("def f():\n    raise ValueError()\n    y = 2") == "def f(): raise ValueError()"


def test_class_attributes_global_and_dunder_names_are_kept():
    code = "class Shop:\n    limit = 3\n__version__ = '1'\ndef f():\n    global counter\n    counter = 1"
    out = clean(code)
    assert "limit = 3" in out and "__version__" in out and "counter = 1" in out


def test_augmented_assignment_to_a_read_name_is_kept():
    assert clean("def f():\n    count = 0\n    count += 1\n    print(count)") == \
        "def f(): count = 0 count += 1 print(count)"
    assert clean("def f():\n    junk = 0\n    junk += 1\n    return 2") == "def f(): return 2"


def test_unparseable_code_is_returned_unchanged():
    broken = "def f(:\n    x = 1\n"
    assert strip_python_dead_code(broken) == broken


def test_multiline_statements_and_unicode_are_cut_exactly():
    code = "def f():\n    名前 = 'ü'\n    unused = [\n        1,\n        2,\n    ]\n    print(名前)\n"
    assert clean(code) == "def f(): 名前 = 'ü' print(名前)"


def test_languages_without_a_cleanup_are_not_touched():
    # Every accepted language has a cleanup (see test_ts_cleanup); other files are left alone.
    kotlin = "fun main() {\n    val unused = 5\n}"
    assert "5" in normalize_code(kotlin, "Main.kt")


def test_read_only_method_calls_are_removed_mutating_ones_kept():
    assert clean("def f(d):\n    junk = list(d.values())\n    return d") == "def f(d): return d"
    assert clean("def f(s):\n    junk = s.strip().lower()\n    return s") == "def f(s): return s"
    assert "d.pop()" in clean("def f(d):\n    x = d.pop()\n    return d")
    assert "out.write(" in clean("def f(out):\n    n = out.write('x')\n    return 1")


def test_stray_markdown_fences_are_ignored():
    pasted = "```python\ndef f():\n    junk = 5\n    return 1\n```\n"
    assert clean(pasted) == "def f(): return 1"
    still_broken = "```\ndef f(:\n```\n"
    assert strip_python_dead_code(still_broken) == still_broken
