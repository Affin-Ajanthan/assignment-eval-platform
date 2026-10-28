"""Token fingerprints read Java, JavaScript, C, C++, C#, Go, Ruby and PHP with
tree-sitter (the parsers ts_cleanup already uses) instead of the regex, so
names, literals and each language's own keywords are recognised properly."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.similarity.core import _generic_tokens, normalize_tokens, normalize_tokens_with_lines


def test_renamed_names_give_the_same_tokens_in_every_language():
    pairs = {
        "a.php": ("<?php\n$total = 0;\nforeach ($marks as $m) { $total += $m; }\necho $total;\n",
                  "<?php\n$sum = 0;\nforeach ($scores as $s) { $sum += $s; }\necho $sum;\n"),
        "a.rb": ("@total = 0\nmarks.each { |m| @total += m }\nputs @total\n",
                 "@sum = 0\nscores.each { |s| @sum += s }\nputs @sum\n"),
        "a.go": ("package main\nfunc avg(xs []int) int { t := 0; for _, x := range xs { t += x }; return t }\n",
                 "package main\nfunc mean(vs []int) int { s := 0; for _, v := range vs { s += v }; return s }\n"),
        "A.java": ("class A { int f(int[] xs) { int t = 0; for (int x : xs) t += x; return t; } }",
                   "class B { int g(int[] vs) { int s = 0; for (int v : vs) s += v; return s; } }"),
        "a.c": ("#include <stdio.h>\nint f(int n) { int t = 0; while (n--) t += n; return t; }\n",
                "#include <stdio.h>\nint g(int k) { int s = 0; while (k--) s += k; return s; }\n"),
    }
    for name, (a, b) in pairs.items():
        assert normalize_tokens(a, name) == normalize_tokens(b, name), name


def test_a_contextual_keyword_used_as_a_name_is_still_a_name():
    # C#: `file`, `value`, `record` are keywords only in some places; as a variable they are names
    a = "class A { void M() { var writer = new StreamWriter(p); writer.Write(1); } }"
    b = "class A { void M() { var file = new StreamWriter(p); file.Write(1); } }"
    assert normalize_tokens(a, "A.cs") == normalize_tokens(b, "A.cs")
    assert "var" in normalize_tokens(a, "A.cs")                      # the real keyword is kept


def test_literals_fold_and_comments_are_dropped():
    js = "// total\nconst msg = `Average: ${avg} of ${n}`; /* end */ let x = 0x1F;\n"
    tokens = normalize_tokens(js, "a.js")
    assert tokens == ["const", "ID", "=", "STR", ";", "let", "ID", "=", "NUM", ";"]
    assert "STR" in normalize_tokens("<?php\necho <<<TEXT\nHello $name\nTEXT;\n", "a.php")


def test_each_languages_own_keywords_are_kept():
    # the regex knew only a shared keyword list, so `elsif`, `unless`, `foreach`, `func` became names
    assert "elsif" in normalize_tokens("if a\n  b\nelsif c\n  d\nend\n", "a.rb")
    assert "foreach" in normalize_tokens("<?php foreach ($a as $b) {}", "a.php")
    assert "func" in normalize_tokens("package main\nfunc f() {}\n", "a.go")
    assert "ID" in [t for t, _ in _generic_tokens("elsif")]          # what the regex did


def test_c_includes_count_instead_of_being_read_as_comments():
    tokens = normalize_tokens("#include <stdio.h>\nint main() { return 0; }\n", "a.c")
    assert tokens[:2] == ["#include", "STR"]


def test_code_with_a_syntax_error_is_still_tokenized():
    good = "class A { int f(int x) { int y = x * 2; return y + 1; } }"
    broken = "class A { int f(int x) { int y = x * 2 return y + 1; } }"   # missing ;
    a, b = normalize_tokens(good, "A.java"), normalize_tokens(broken, "A.java")
    assert len(b) >= len(a) - 2 and a[:10] == b[:10]


def test_tokens_carry_their_source_line():
    src = "<?php\n\n$x = 1;\n\necho $x;\n"
    lines = {t: ln for t, ln in normalize_tokens_with_lines(src, "a.php")}
    assert lines["="] == 3 and lines["echo"] == 5


def test_languages_without_a_parser_still_use_the_regex():
    kotlin = "fun main() { val x = 1 }"
    assert normalize_tokens(kotlin, "a.kt") == [t for t, _ in _generic_tokens(kotlin)]
