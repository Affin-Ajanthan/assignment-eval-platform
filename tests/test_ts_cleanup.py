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
    # Every accepted language has a cleanup now; a file in any other language is left alone.
    kotlin = "fun main() {\n    val unused = 5\n}"
    assert "5" in normalize_code(kotlin, "Main.kt")


# ---- C and C++ ------------------------------------------------------------------

def c(code: str, external=None) -> str:
    return " ".join(strip_dead_code(code, "c", external).split())


def cpp(code: str, external=None) -> str:
    return " ".join(strip_dead_code(code, "cpp", external).split())


C_ORIGINAL = """#include <stdio.h>
double average(int marks[], int n) {
    int sum = 0;
    for (int i = 0; i < n; i++) {
        sum += marks[i];
    }
    return (double) sum / n;
}"""

C_JUNK = """#include <stdio.h>
static int unused_global = 7;
double average(int marks[], int n) {
    int unused_counter = 100;
    int *spare = NULL, buffer[16];
    int sum = 0;
    double root = sqrt(16.0);
    for (int i = 0; i < n; i++) {
        int doubled = marks[i] * 2;
        sum += marks[i];
    }
    if (0) {
        printf("never");
    }
    return (double) sum / n;
    printf("unreachable");
}"""

CPP_ORIGINAL = """#include <vector>
double average(const std::vector<int>& marks) {
    int sum = 0;
    for (int m : marks) {
        sum += m;
    }
    return static_cast<double>(sum) / marks.size();
}"""

CPP_JUNK = """#include <vector>
double average(const std::vector<int>& marks) {
    std::string label = "average";
    std::vector<int> temp;
    auto count = marks.size();
    int sum = 0;
    for (int m : marks) {
        int doubled = m * 2;
        sum += m;
    }
    if (false) {
        std::cout << "never";
    }
    return static_cast<double>(sum) / marks.size();
}"""


def test_c_junk_filled_copy_normalizes_like_the_original():
    assert normalize_code(C_JUNK, "average.c") == normalize_code(C_ORIGINAL, "average.c")


def test_cpp_junk_filled_copy_normalizes_like_the_original():
    assert normalize_code(CPP_JUNK, "average.cpp") == normalize_code(CPP_ORIGINAL, "average.cpp")


def test_c_keeps_side_effects_extern_volatile_macros_and_labels():
    out = c("""#define LIMIT counter_max
int counter_max = 10;
int main(void) {
    int x = read_input();
    int *mem = malloc(8);
    volatile int hw = 0;
    extern int shared;
    switch (x) { case 1: return 1; case 2: puts("two"); break; }
    return x;
err:
    return -1;
}""")
    for kept in ("int counter_max = 10;", "read_input()", "malloc(8)", "volatile int hw", "extern int shared",
                 "case 2:", "err:"):
        assert kept in out, kept


def test_cpp_keeps_objects_whose_construction_may_matter():
    out = cpp("""int main() {
    std::lock_guard<std::mutex> lk(m);
    std::ofstream out("log.txt");
    Widget w;
    int* heap = new int[5];
    std::vector<int> unused_vec;
    return 0;
}""")
    for kept in ("lock_guard", "std::ofstream out", "Widget w;", "new int[5]"):
        assert kept in out, kept
    assert "unused_vec" not in out


def test_c_top_level_variable_used_by_another_file_is_kept():
    out = c("int shared_count = 0;\nint junk_total = 0;\nint f(void) { return 1; }", {"shared_count"})
    assert "shared_count" in out and "junk_total" not in out


def test_c_and_cpp_for_loop_variables_are_not_touched():
    assert "int i = 0" in c("void f(void) { for (int i = 0; i < 3; i++) { g(); } }")
    assert "int x : v" in cpp("void f() { for (int x : v) { g(x); } }")


def test_header_files_use_the_cpp_grammar():
    # A .h file is cleaned with the C++ grammar (which also reads C headers).
    header = "static inline int twice(int x) {\n    int junk = 4;\n    return 2 * x;\n}"
    assert "junk" not in normalize_code(header, "util.h") and "4" not in normalize_code(header, "util.h")


# ---- C#, Go, Ruby, PHP --------------------------------------------------------------

def clean(code: str, lang: str, external=None) -> str:
    return " ".join(strip_dead_code(code, lang, external).split())


ORIGINALS = {
    "Grades.cs": """class Grades {
    static double Average(int[] marks) {
        int sum = 0;
        foreach (int m in marks) {
            sum += m;
        }
        return (double) sum / marks.Length;
    }
}""",
    "grades.go": """package main

func average(marks []int) float64 {
    sum := 0
    for _, m := range marks {
        sum += m
    }
    return float64(sum) / float64(len(marks))
}""",
    "grades.rb": """def average(marks)
  sum = 0
  marks.each do |m|
    sum += m
  end
  sum.to_f / marks.length
end""",
    "grades.php": """<?php
function average($marks) {
    $sum = 0;
    foreach ($marks as $m) {
        $sum += $m;
    }
    return $sum / count($marks);
}""",
}

JUNK = {
    "Grades.cs": """class Grades {
    static double Average(int[] marks) {
        int unusedCounter = 100;
        var label = "average".Trim();
        var temp = new List<int>();
        int sum = 0;
        foreach (int m in marks) {
            int doubled = m * 2;
            sum += m;
        }
        if (false) {
            Console.WriteLine("never");
        }
        return (double) sum / marks.Length;
    }
}""",
    "grades.go": """package main

var debugMode = false

func average(marks []int) float64 {
    unusedCounter := 100
    var label string = "average"
    _ = unusedCounter
    _ = label
    sum := 0
    for _, m := range marks {
        sum += m
    }
    if false {
        println("never")
    }
    return float64(sum) / float64(len(marks))
}""",
    "grades.rb": """def average(marks)
  unused_counter = 100
  label = "average".upcase
  sum = 0
  marks.each do |m|
    doubled = m * 2
    sum += m
  end
  if false
    puts "never"
  end
  sum.to_f / marks.length
end""",
    "grades.php": """<?php
function average($marks) {
    $unusedCounter = 100;
    $label = strtoupper("average");
    $sum = 0;
    foreach ($marks as $m) {
        $doubled = $m * 2;
        $sum += $m;
    }
    if (false) {
        echo "never";
    }
    return $sum / count($marks);
}""",
}


def test_junk_filled_copies_normalize_like_the_originals():
    for name, original in ORIGINALS.items():
        assert normalize_code(JUNK[name], name) == normalize_code(original, name), name


def test_csharp_keeps_using_var_objects_with_effects_and_fields():
    out = clean("""class P {
    int field = 3;
    void F() {
        using var f = File.Open("a");
        var w = new StreamWriter("log.txt");
        int x = Read();
        var unusedList = new List<int>();
    }
}""", "csharp")
    for kept in ("int field = 3;", "using var f", "new StreamWriter", "Read()"):
        assert kept in out, kept
    assert "unusedList" not in out


def test_go_removes_blank_silencers_but_keeps_exported_and_receives():
    out = clean("""package main
var helper = 1
var Exported = 2
func f() int {
    junk := 5
    _ = junk
    v := <-ch
    return v
}""", "go")
    assert "junk" not in out and "_ =" not in out and "helper" not in out
    assert "var Exported = 2" in out and "<-ch" in out


def test_ruby_keeps_bare_method_calls_and_rescue_after_return():
    out = clean("""def f
  x = read_input
  y = 3 if false
  return x
  puts "dead"
rescue
  puts "err"
end""", "ruby")
    assert "x = read_input" in out and "rescue" in out and 'puts "err"' in out
    assert "y = 3" not in out and "dead" not in out


def test_php_keeps_variables_used_in_strings_and_dynamic_files():
    out = clean("<?php\nfunction f() {\n  $name = 'Ann';\n  $junk = 5;\n  echo \"Hello $name\";\n}", "php")
    assert "$name" in out and "$junk" not in out
    dynamic = "<?php\nfunction f() {\n  $a = 1;\n  return compact('a');\n}"
    assert strip_dead_code(dynamic, "php") == dynamic


def test_php_top_level_variable_used_by_another_file_is_kept():
    out = clean("<?php\n$config = 1;\n$junk = 2;\nfunction f() { return 1; }", "php", {"config"})
    assert "$config" in out and "$junk" not in out
