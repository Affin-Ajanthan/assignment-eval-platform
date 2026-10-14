"""Removing do-nothing code from Java and JavaScript before the semantic
comparison (app/similarity/ts_cleanup.py, tree-sitter)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.similarity.semantic import normalize_code
from app.similarity.ts_cleanup import strip_dead_code


def java(code: str, external=None) -> str:
    return " ".join(strip_dead_code(code, "java", external).split())


def js(code: str, external=None) -> str:
    return " ".join(strip_dead_code(code, "javascript", external).split())


JAVA_ORIGINAL = """public class Grades {
    static double average(int[] marks) {
        int sum = 0;
        for (int m : marks) {
            sum += m;
        }
        return (double) sum / marks.length;
    }
}"""

JAVA_JUNK = """public class Grades {
    static double average(int[] marks) {
        int unusedCounter = 100;
        String label = "average".trim();
        List<Integer> temp = new ArrayList<>();
        boolean debug = false;
        int sum = 0;
        for (int m : marks) {
            int doubled = m * 2;
            sum += m;
        }
        if (false) {
            System.out.println("never");
        }
        return (double) sum / marks.length;
    }
}"""

JS_ORIGINAL = """function average(marks) {
  let sum = 0;
  for (const m of marks) {
    sum += m;
  }
  return sum / marks.length;
}"""

JS_JUNK = """const unusedTop = 42;
function average(marks) {
  let unusedCounter = 0;
  const temp = [];
  var label = "avg".toUpperCase();
  let sum = 0;
  for (const m of marks) {
    const doubled = m * 2;
    sum += m;
  }
  if (false) {
    console.log("never");
  }
  return sum / marks.length;
  console.log("unreachable");
}"""


# ---- the headline cases ----------------------------------------------------------

def test_java_junk_filled_copy_normalizes_like_the_original():
    assert normalize_code(JAVA_JUNK, "Grades.java") == normalize_code(JAVA_ORIGINAL, "Grades.java")


def test_javascript_junk_filled_copy_normalizes_like_the_original():
    assert normalize_code(JS_JUNK, "grades.js") == normalize_code(JS_ORIGINAL, "grades.js")


# ---- Java -----------------------------------------------------------------------

def test_java_keeps_side_effects_fields_and_used_variables():
    out = java("""class A {
        private int field = 3;
        void f() {
            int x = readInput();
            int y = list.remove(0);
            Scanner sc = new Scanner(System.in);
            int used = 2;
            System.out.println(used);
        }
    }""")
    for kept in ("private int field = 3;", "readInput()", "list.remove(0)", "new Scanner(System.in)", "int used = 2;"):
        assert kept in out


def test_java_chain_of_unused_variables_is_removed():
    assert java("class A { void f() { int b = 1; int a = b + 1; System.out.println(0); } }") == \
        "class A { void f() { System.out.println(0); } }"


def test_java_if_false_keeps_else_and_unreachable_is_removed():
    out = java("class A { int f() { if (false) { g(); } else { h(); } return 1; x(); } }")
    assert "g()" not in out and "h()" in out and "x()" not in out


def test_java_for_loop_variable_is_not_touched():
    out = java("class A { void f() { for (int i = 0; i < 3; i++) { g(); } } }")
    assert "int i = 0" in out


# ---- JavaScript -----------------------------------------------------------------

def test_js_keeps_calls_destructuring_exports_and_hoisted_functions():
    out = js("""export const KEEP = 1;
    function f() {
      const data = fetchData();
      const last = items.pop();
      const {a, b} = obj;
      return 1;
      function hoisted() { return 2; }
    }""")
    for kept in ("export const KEEP = 1;", "fetchData()", "items.pop()", "const {a, b} = obj;", "function hoisted()"):
        assert kept in out


def test_js_top_level_name_used_by_another_file_is_kept():
    code = "const API_URL = 'x';\nconst junk = 5;\nfunction f() { return 1; }"
    out = js(code, {"API_URL"})
    assert "API_URL" in out and "junk" not in out


def test_js_shorthand_property_counts_as_a_use():
    assert "const name = 'x';" in js("function f() { const name = 'x'; return { name }; }")


def test_js_if_false_with_else():
    assert js("function f() { if (false) { a(); } else { b(); } }") == "function f() { { b(); } }"


# ---- safety ---------------------------------------------------------------------

def test_syntax_errors_return_the_source_unchanged():
    broken = "class A { void f( { int x = 1; }"
    assert strip_dead_code(broken, "java") == broken
    broken_js = "function f( { let x = 1;"
    assert strip_dead_code(broken_js, "javascript") == broken_js


def test_stray_markdown_fences_are_ignored():
    pasted = "```javascript\nfunction f() {\n  let junk = 5;\n  return 1;\n}\n```\n"
    assert js(pasted) == "function f() { return 1; }"


def test_file_that_would_become_empty_is_kept():
    assert js("const a = 1;\nconst b = 2;") == "const a = 1; const b = 2;"


def test_other_languages_are_not_touched():
    c_code = "int main() { int unused = 5; return 0; }"
    assert "5" in normalize_code(c_code, "main.c")
