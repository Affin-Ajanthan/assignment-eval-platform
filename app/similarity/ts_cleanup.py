"""
Remove code that does nothing from Java, JavaScript, C, C++, C#, Go, Ruby and
PHP before semantic comparison -- the counterpart of python_cleanup for
languages Python's `ast` can't read. Parsing uses tree-sitter (one grammar
package per language).

Why: an exact copy padded with unused variables scored like different code,
because ``anonymize_identifiers`` numbers names by first appearance and every
junk declaration renumbers the names after it.

Removed (conservatively -- when in doubt, code is kept):

* local variable declarations whose every declared name is never used again
  anywhere in the file, when the initial value has no side effects
  (literals, names, arithmetic, read-only methods such as ``trim()`` or
  ``length()``, and ``new`` of plain collections). ``int x = readInput();``
  is kept;
* JavaScript top-level ``let``/``const``/``var`` likewise, unless another file
  of the submission mentions the name (``external_names``) or it is exported;
* ``if (false) {...}`` (an ``else`` branch is kept) and ``while (false) {...}``;
* statements after ``return``/``throw``/``break``/``continue`` in the same
  block (JavaScript function declarations are kept: they are hoisted).

* C/C++ top-level variables likewise, unless another file mentions them.

C and C++ are handled more carefully still: in C++ creating an object can do
something even when its name is never used (a lock guard, a file stream), so a
C++ declaration is only removed when its type is a built-in type, ``auto`` or a
plain standard container/string; ``extern`` and ``volatile`` declarations are
kept; ``case`` and ``goto`` labels after a ``return`` stay (they can still be
reached); names used inside ``#define`` bodies count as used.

C#: ``using var`` and ``ref`` locals and objects other than plain collections
are kept (creating them can matter). Go: the compiler already rejects unused
locals, so junk is silenced with ``_ = x``; those blank assignments are removed
too, then the variable they kept alive. Exported (Capitalized) package
variables are kept. Ruby: a bare word on the right (``x = read_input``) may be
a method call, so it only counts as side-effect-free when it is a known local;
``rescue``/``ensure`` after a ``return`` stay. PHP: names inside strings
(``"Hello $name"``) count as used, and a file that uses ``compact()``,
``extract()`` or variable variables (``$$x``) keeps every variable.

Never touched: Java fields, destructuring patterns, exported declarations.
Code with syntax errors is returned unchanged (stray Markdown code fences
from a pasted chat answer are dropped first). If nothing would be left, the
source is returned unchanged. The source is cut at exact byte positions,
never rewritten.
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache

log = logging.getLogger(__name__)

_FENCE_LINE = re.compile(r"^[ \t]*```[\w+-]*[ \t]*$", re.MULTILINE)

LANGUAGE_BY_EXTENSION = {
    ".java": "java", ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".c": "c",
    # Headers use the C++ grammar: it reads C headers too, and .h is common in C++ courses.
    ".h": "cpp", ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".hpp": "cpp", ".hh": "cpp", ".hxx": "cpp",
    ".cs": "csharp", ".go": "go", ".rb": "ruby", ".php": "php",
}
_C_FAMILY = {"c", "cpp"}

# Calls/constructors that only read or build plain values.
_PURE_METHODS = {
    "java": {"length", "size", "get", "charAt", "substring", "trim", "strip", "toUpperCase", "toLowerCase",
             "equals", "equalsIgnoreCase", "contains", "isEmpty", "indexOf", "lastIndexOf", "startsWith",
             "endsWith", "valueOf", "toString", "abs", "max", "min", "sqrt", "pow", "round", "floor", "ceil",
             "keySet", "values", "entrySet", "split", "format", "parseInt", "parseDouble", "asList", "of",
             "compareTo", "hashCode", "containsKey", "getOrDefault", "toCharArray", "replace", "repeat"},
    "javascript": {"trim", "trimStart", "trimEnd", "toUpperCase", "toLowerCase", "slice", "substring", "charAt",
                   "indexOf", "lastIndexOf", "includes", "startsWith", "endsWith", "split", "join", "concat",
                   "toString", "toFixed", "keys", "values", "entries", "isArray", "abs", "max", "min", "sqrt",
                   "pow", "round", "floor", "ceil", "parseInt", "parseFloat", "String", "Number", "Boolean",
                   "repeat", "padStart", "padEnd", "at", "has", "get", "stringify"},
    "c": {"strlen", "abs", "labs", "fabs", "sqrt", "pow", "floor", "ceil", "round", "fmax", "fmin", "toupper",
          "tolower", "isdigit", "isalpha", "isalnum", "isspace", "isupper", "islower", "atoi", "atol", "atof",
          "strcmp", "strncmp", "strchr", "strstr"},
}
_PURE_METHODS["cpp"] = _PURE_METHODS["c"] | {
    "size", "length", "empty", "at", "front", "back", "begin", "end", "cbegin", "cend", "substr", "find",
    "rfind", "c_str", "data", "count", "contains", "max", "min", "to_string", "stoi", "stol", "stod",
    "compare", "starts_with", "ends_with", "max_element", "min_element", "accumulate", "get"}
_PURE_METHODS["csharp"] = {
    "Trim", "TrimStart", "TrimEnd", "ToUpper", "ToLower", "Substring", "IndexOf", "LastIndexOf", "Contains",
    "StartsWith", "EndsWith", "Split", "Replace", "ToString", "Equals", "CompareTo", "GetHashCode", "Abs",
    "Max", "Min", "Sqrt", "Pow", "Round", "Floor", "Ceiling", "Parse", "TryParse", "ToInt32", "ToDouble",
    "Format", "Join", "Concat", "IsNullOrEmpty", "IsNullOrWhiteSpace", "Count", "Sum", "Average", "Any",
    "All", "Where", "Select", "OrderBy", "OrderByDescending", "First", "FirstOrDefault", "Last", "ToList",
    "ToArray", "Distinct", "Reverse", "ContainsKey", "GetValueOrDefault", "Length"}
_PURE_METHODS["go"] = {
    "len", "cap", "make", "new", "min", "max", "Itoa", "Atoi", "ParseInt", "ParseFloat", "FormatInt", "Sprintf",
    "Sprint", "Sprintln", "ToUpper", "ToLower", "TrimSpace", "Trim", "Split", "Join", "Contains", "HasPrefix",
    "HasSuffix", "Index", "Replace", "ReplaceAll", "Repeat", "Fields", "Abs", "Sqrt", "Pow", "Floor", "Ceil",
    "Round", "Max", "Min", "Inf", "IsNaN"}
_PURE_METHODS["ruby"] = {
    "length", "size", "count", "upcase", "downcase", "capitalize", "strip", "chomp", "to_s", "to_i", "to_f",
    "to_a", "to_sym", "round", "abs", "floor", "ceil", "sum", "max", "min", "first", "last", "empty?",
    "include?", "keys", "values", "sort", "reverse", "join", "split", "uniq", "flatten", "zero?", "even?",
    "odd?", "nil?", "freeze", "dup", "sqrt", "new"}
_PURE_METHODS["php"] = {
    "strlen", "count", "strtoupper", "strtolower", "ucfirst", "trim", "ltrim", "rtrim", "abs", "sqrt", "pow",
    "round", "floor", "ceil", "max", "min", "intval", "floatval", "strval", "boolval", "implode", "explode",
    "str_repeat", "substr", "strpos", "str_replace", "array_keys", "array_values", "array_sum", "in_array",
    "array_merge", "array_slice", "array_reverse", "number_format", "sprintf", "is_numeric", "is_array",
    "array_key_exists", "range", "json_encode"}
# C++ types whose construction has no effect worth keeping (std:: prefix and template arguments ignored).
_PURE_CPP_TYPES = {"string", "vector", "map", "set", "unordered_map", "unordered_set", "array", "pair", "list",
                   "deque", "tuple", "optional", "string_view"}
_PURE_CONSTRUCTORS = {
    "java": {"ArrayList", "LinkedList", "HashMap", "TreeMap", "LinkedHashMap", "HashSet", "TreeSet",
             "LinkedHashSet", "ArrayDeque", "StringBuilder", "String", "Object", "Integer", "Double"},
    "javascript": {"Array", "Map", "Set", "Object", "WeakMap", "WeakSet", "String", "Number", "Date"},
}
_PURE_CONSTRUCTORS["csharp"] = {"List", "Dictionary", "HashSet", "Queue", "Stack", "StringBuilder", "SortedList",
                                "SortedDictionary", "LinkedList", "String", "Object", "Random"}
# Node types that make an initializer impure regardless of what they contain.
_IMPURE_NODES = {
    "java": {"assignment_expression", "update_expression"},
    "javascript": {"assignment_expression", "augmented_assignment_expression", "update_expression",
                   "await_expression", "yield_expression"},
    "c": {"assignment_expression", "update_expression"},
    "cpp": {"assignment_expression", "update_expression", "new_expression", "delete_expression",
            "throw_expression", "co_await_expression", "co_yield_statement"},
    "csharp": {"assignment_expression", "await_expression", "throw_expression"},
    "go": {"send_statement", "inc_statement", "dec_statement", "go_statement"},
    "ruby": {"assignment", "operator_assignment", "yield", "super"},
    "php": {"assignment_expression", "augmented_assignment_expression", "update_expression",
            "object_creation_expression", "include_expression", "include_once_expression",
            "require_expression", "require_once_expression", "print_intrinsic", "exit_statement"},
}
_LOCAL_DECLARATIONS = {"java": {"local_variable_declaration"},
                       "javascript": {"lexical_declaration", "variable_declaration"},
                       "c": {"declaration"}, "cpp": {"declaration"},
                       "csharp": {"local_declaration_statement"},
                       "go": {"short_var_declaration", "var_declaration", "assignment_statement"},
                       "ruby": {"assignment"}, "php": {"expression_statement"}}
_FUNCTION_NODES = {
    "java": {"method_declaration", "constructor_declaration", "lambda_expression"},
    "javascript": {"function_declaration", "function_expression", "arrow_function", "method_definition",
                   "generator_function_declaration", "generator_function"},
    "c": {"function_definition"},
    "cpp": {"function_definition", "lambda_expression"},
    "csharp": {"method_declaration", "constructor_declaration", "local_function_statement", "lambda_expression",
               "anonymous_method_expression", "accessor_declaration", "operator_declaration",
               "destructor_declaration"},
    "go": {"function_declaration", "method_declaration", "func_literal"},
    "ruby": {"method", "singleton_method", "lambda", "do_block", "block"},
    "php": {"function_definition", "method_declaration", "anonymous_function", "arrow_function"},
}
_BLOCKS = {"java": {"block", "switch_block_statement_group"}, "javascript": {"statement_block", "switch_case"},
           "c": {"compound_statement", "case_statement"}, "cpp": {"compound_statement", "case_statement"},
           "csharp": {"block", "switch_section"}, "go": {"statement_list"},
           "ruby": {"body_statement", "then", "else", "do"},
           "php": {"compound_statement", "case_statement", "default_statement"}}
# Statements that can be reached even after a return: a switch case, a goto
# label, or Ruby's rescue/ensure/else clauses of a method body.
_STILL_REACHABLE = {"switch_label", "case_statement", "labeled_statement", "default_statement",
                    "rescue", "ensure", "else"}
_TERMINATORS = {"return_statement", "throw_statement", "break_statement", "continue_statement",
                "return", "break", "next"}
_HOISTED = {"function_declaration", "generator_function_declaration", "class_declaration"}
_NAME_NODES = {"identifier", "shorthand_property_identifier", "shorthand_property_identifier_pattern"}


@lru_cache(maxsize=None)
def _parser(language: str):
    """A tree-sitter parser for `language`, or None if tree-sitter isn't installed."""
    try:
        from tree_sitter import Language, Parser
        if language == "php":  # its PHP-with-HTML grammar: student files usually start with <?php
            import tree_sitter_php as php
            return Parser(Language(php.language_php()))
        if language == "csharp":
            import tree_sitter_c_sharp as grammar
        elif language == "go":
            import tree_sitter_go as grammar
        elif language == "ruby":
            import tree_sitter_ruby as grammar
        elif language == "java":
            import tree_sitter_java as grammar
        elif language == "c":
            import tree_sitter_c as grammar
        elif language == "cpp":
            import tree_sitter_cpp as grammar
        else:
            import tree_sitter_javascript as grammar
        return Parser(Language(grammar.language()))
    except Exception as exc:  # ImportError or a grammar/ABI mismatch: cleanup is skipped
        log.warning("tree-sitter %s parser unavailable, no dead-code cleanup: %s", language, exc)
        return None


def _walk(node):
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(reversed(current.children))


def _text(node) -> str:
    return node.text.decode("utf-8", errors="replace")


def _false_condition(node) -> bool:
    """`(false)` / `(0)` as an if/while condition (C++ wraps it in a condition_clause)."""
    inner = node
    while inner is not None and inner.type in ("parenthesized_expression", "condition_clause") \
            and inner.named_child_count == 1:
        inner = inner.named_children[0]
    if inner is None:
        return False
    if inner.type in ("false", "boolean_literal", "boolean"):
        return _text(inner).lower() == "false"
    return inner.type in ("decimal_integer_literal", "number", "number_literal") and _text(inner) == "0"


def _declared_name(declarator):
    """(name node, extra expressions) of a C/C++ declarator: `x`, `*x`, `x[n]`,
    `&x`; None for anything else (a function declarator, a structured binding)."""
    extras = []
    node = declarator
    while node is not None and node.type in ("pointer_declarator", "array_declarator", "reference_declarator"):
        if node.type == "array_declarator" and node.child_by_field_name("size") is not None:
            extras.append(node.child_by_field_name("size"))
        inner = node.child_by_field_name("declarator")
        node = inner if inner is not None else (node.named_children[-1] if node.named_child_count else None)
    return (node, extras) if node is not None and node.type == "identifier" else None


class _Cleaner:
    def __init__(self, language: str, root, external: set[str]):
        self.lang = language
        self.root = root
        self.external = external
        self.ruby_locals: set[str] = set()
        self.php_dynamic = False
        if language == "ruby":
            for node in _walk(root):
                if node.type in ("assignment", "operator_assignment"):
                    left = node.child_by_field_name("left")
                    if left is not None and left.type == "identifier":
                        self.ruby_locals.add(_text(left))
                elif node.type in ("method_parameters", "block_parameters", "lambda_parameters"):
                    self.ruby_locals.update(_text(c) for c in node.named_children if c.type == "identifier")
        self.removed: list[tuple[int, int]] = []  # byte ranges
        self.removed_ids: set[int] = set()

    # ---- helpers ------------------------------------------------------------

    def _inside_removed(self, node) -> bool:
        return any(start <= node.start_byte and node.end_byte <= end for start, end in self.removed)

    def _remove(self, start: int, end: int, node=None) -> None:
        self.removed.append((start, end))
        if node is not None:
            self.removed_ids.add(node.id)

    def _enclosing_function(self, node):
        parent = node.parent
        while parent is not None:
            if parent.type in _FUNCTION_NODES[self.lang]:
                return parent
            if parent.type in ("class_body", "class_declaration") and self.lang == "java":
                return None
            parent = parent.parent
        return None

    def _call_name(self, call):
        """The called function or method name of a call node, for the new languages."""
        if self.lang == "csharp":
            fn = call.child_by_field_name("function")
            if fn is not None and fn.type == "member_access_expression":
                fn = fn.child_by_field_name("name")
        elif self.lang == "go":
            fn = call.child_by_field_name("function")
            if fn is not None and fn.type == "selector_expression":
                fn = fn.child_by_field_name("field")
        elif self.lang == "ruby":
            fn = call.child_by_field_name("method")
        else:  # php
            fn = call.child_by_field_name("name") or call.child_by_field_name("function")
        words = re.findall(r"[\w?!]+", _text(fn).split("<")[0]) if fn is not None else []
        return words[-1] if words else ""

    def _pure_new(self, node) -> bool:
        calls = {"csharp": ("invocation_expression",), "go": ("call_expression",), "ruby": ("call",),
                 "php": ("function_call_expression", "member_call_expression", "scoped_call_expression",
                         "nullsafe_member_call_expression")}[self.lang]
        method_ids = set()
        for sub in _walk(node):
            if sub.type in _IMPURE_NODES[self.lang]:
                return False
            if sub.type in ("postfix_unary_expression", "prefix_unary_expression") and \
                    ("++" in _text(sub) or "--" in _text(sub)):
                return False
            if self.lang == "go" and sub.type == "unary_expression" and _text(sub).startswith("<-"):
                return False  # a channel receive
            if sub.type in calls:
                if self._call_name(sub) not in _PURE_METHODS[self.lang]:
                    return False
                if self.lang == "ruby" and sub.child_by_field_name("method") is not None:
                    method_ids.add(sub.child_by_field_name("method").id)
            if sub.type == "object_creation_expression" and self.lang == "csharp":
                type_node = sub.child_by_field_name("type")
                base = re.findall(r"\w+", _text(type_node).split("<")[0]) if type_node is not None else []
                if not base or base[-1] not in _PURE_CONSTRUCTORS["csharp"]:
                    return False
            if self.lang == "ruby" and sub.type == "identifier" and sub.id not in method_ids \
                    and _text(sub) not in self.ruby_locals:
                return False  # a bare word that is not a known local is a method call
        return True

    def _pure(self, node) -> bool:
        if node is None:
            return True
        if self.lang in ("csharp", "go", "ruby", "php"):
            return self._pure_new(node)
        for sub in _walk(node):
            if sub.type in _IMPURE_NODES[self.lang]:
                return False
            if sub.type in ("method_invocation", "call_expression"):
                name = sub.child_by_field_name("name") if self.lang == "java" else None
                if self.lang == "javascript":
                    fn = sub.child_by_field_name("function")
                    if fn is not None and fn.type == "member_expression":
                        name = fn.child_by_field_name("property")
                    else:
                        name = fn
                if self.lang in _C_FAMILY:
                    fn = sub.child_by_field_name("function")
                    if fn is not None and fn.type == "field_expression":
                        fn = fn.child_by_field_name("field")
                    words = re.findall(r"\w+", _text(fn).split("<")[0]) if fn is not None else []
                    if not words or words[-1] not in _PURE_METHODS[self.lang]:  # std::max -> max
                        return False
                    continue
                if name is None or _text(name) not in _PURE_METHODS[self.lang]:
                    return False
            if sub.type in ("object_creation_expression", "new_expression") and self.lang not in _C_FAMILY:
                ctor = sub.child_by_field_name("type" if self.lang == "java" else "constructor")
                ctor_name = _text(ctor).split("<")[0].split(".")[-1] if ctor is not None else ""
                if ctor_name not in _PURE_CONSTRUCTORS[self.lang]:
                    return False
        return True

    def _name_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for node in _walk(self.root):
            if node.type in _NAME_NODES and not self._inside_removed(node):
                name = _text(node)
                counts[name] = counts.get(name, 0) + 1
            elif node.type == "variable_name" and self.lang == "php":
                name = _text(node).lstrip("$")
                counts["$" + name] = counts.get("$" + name, 0) + 1
            elif node.type == "preproc_arg":
                # A #define body is not parsed: any name in it counts as used.
                for name in re.findall(r"[A-Za-z_]\w*", _text(node)):
                    counts[name] = counts.get(name, 0) + 2
        return counts

    def _new_declaration(self, node, counts, top_level) -> bool:
        """Whether a C# / Go / Ruby / PHP declaration statement can go."""
        def unused(name: str, bare: str | None = None) -> bool:
            bare = bare if bare is not None else name
            return counts.get(name, 0) <= 1 and not (top_level and bare in self.external)

        if self.lang == "csharp":
            text = _text(node)
            if text.startswith(("using", "ref ", "await ")) or " ref " in text.split("=")[0]:
                return False
            decl = next((c for c in node.named_children if c.type == "variable_declaration"), None)
            declarators = [c for c in decl.named_children if c.type == "variable_declarator"] if decl else []
            if not declarators:
                return False
            for d in declarators:
                name = d.child_by_field_name("name")
                values = [c for c in d.named_children if c != name and c.type != "bracketed_argument_list"]
                if name is None or not unused(_text(name)) or not all(self._pure(v) for v in values):
                    return False
            return True

        if self.lang == "go":
            if node.type == "assignment_statement":  # `_ = x`, `_, _ = a, b`: silencing the compiler
                left, right = node.child_by_field_name("left"), node.child_by_field_name("right")
                return (left is not None and all(_text(c) == "_" for c in left.named_children)
                        and _text(node).split("=")[0].strip().endswith("_") and ":" not in _text(node).split("=")[0]
                        and self._pure(right))
            if node.type == "short_var_declaration":
                names = node.child_by_field_name("left")
                values = node.child_by_field_name("right")
                ids = names.named_children if names is not None else []
            else:  # var_declaration, possibly grouped: var ( a = 1; b = 2 )
                specs = [c for c in _walk(node) if c.type == "var_spec"]
                ids = [n for sp in specs for n in sp.children_by_field_name("name")]
                values = node
                if any(sp.child_by_field_name("value") is None and sp.child_by_field_name("type") is None
                       for sp in specs):
                    return False
            if not ids or any(i.type != "identifier" for i in ids):
                return False
            for i in ids:
                name = _text(i)
                if name == "_":
                    continue
                if (top_level and name[:1].isupper()) or not unused(name):
                    return False  # exported, or used
            if node.type == "var_declaration":
                return all(self._pure(sp.child_by_field_name("value")) for sp in
                           (c for c in _walk(node) if c.type == "var_spec"))
            return self._pure(values)

        if self.lang == "ruby":
            if node.parent is None or node.parent.type not in (_BLOCKS["ruby"] | {"program"}):
                return False  # only a statement of its own, not `a = b = 1` or `x = 1 if y`
            left = node.child_by_field_name("left")
            if left is None or left.type != "identifier":
                return False  # @ivar, Constant, a.b = ... are not locals
            return unused(_text(left)) and self._pure(node.child_by_field_name("right"))

        # php: an expression statement that is only `$x = <value>;`
        if self.php_dynamic or node.named_child_count != 1:
            return False
        expr = node.named_children[0]
        if expr.type != "assignment_expression":
            return False
        left = expr.child_by_field_name("left")
        if left is None or left.type != "variable_name":
            return False
        bare = _text(left).lstrip("$")
        return unused("$" + bare, bare) and self._pure(expr.child_by_field_name("right"))

    def _c_declaration(self, node, counts, top_level) -> bool:
        """Whether a C/C++ `declaration` can go: every name unused, every value pure,
        and (C++) a type whose construction does nothing worth keeping."""
        words = {_text(c) for c in node.children if c.type in ("storage_class_specifier", "type_qualifier")}
        if words & {"extern", "volatile"}:
            return False
        if self.lang == "cpp":
            type_node = node.child_by_field_name("type")
            if type_node is None:
                return False
            base = re.findall(r"\w+", _text(type_node).split("<")[0])
            if type_node.type not in ("primitive_type", "sized_type_specifier", "placeholder_type_specifier") \
                    and (not base or base[-1] not in _PURE_CPP_TYPES):
                return False
        declarators = node.children_by_field_name("declarator")
        if not declarators:
            return False
        for decl in declarators:
            value = None
            if decl.type == "init_declarator":
                value = decl.child_by_field_name("value")
                decl = decl.child_by_field_name("declarator")
            found = _declared_name(decl) if decl is not None else None
            if found is None:
                return False
            name, extras = found
            text = _text(name)
            if counts.get(text, 0) > 1 or not all(self._pure(x) for x in [value, *extras]):
                return False
            if top_level and text in self.external:
                return False
        return True

    # ---- passes ----------------------------------------------------------------

    def dead_code(self) -> None:
        """Unreachable statements and constant-false if/while: independent of names."""
        for node in _walk(self.root):
            if node.type in _BLOCKS[self.lang]:
                stmts = [c for c in node.named_children if c.type != "comment"]
                for i, stmt in enumerate(stmts):
                    if stmt.type in _TERMINATORS:
                        for dead in stmts[i + 1:]:
                            if self.lang == "javascript" and dead.type in _HOISTED:
                                continue
                            if dead.type in _STILL_REACHABLE or dead.type.startswith("preproc"):
                                continue
                            self._remove(dead.start_byte, dead.end_byte, dead)
                        break
            elif node.type in ("while_statement", "while") and _false_condition(node.child_by_field_name("condition")):
                self._remove(node.start_byte, node.end_byte, node)
            elif node.type == "if_modifier" and _false_condition(node.child_by_field_name("condition")):
                self._remove(node.start_byte, node.end_byte, node)  # Ruby: `x = 3 if false`
            elif node.type == "if" and _false_condition(node.child_by_field_name("condition")):
                alternative = node.child_by_field_name("alternative")  # Ruby: if ... else ... end
                if alternative is None:
                    self._remove(node.start_byte, node.end_byte, node)
                elif alternative.type == "else" and alternative.named_child_count:
                    kept = alternative.named_children
                    self._remove(node.start_byte, kept[0].start_byte)
                    self._remove(kept[-1].end_byte, node.end_byte)
            elif node.type == "if_statement" and _false_condition(node.child_by_field_name("condition")):
                alternative = node.child_by_field_name("alternative")
                if alternative is not None and alternative.type in ("else_if_clause", "elsif"):
                    continue  # an else-if chain: leave it
                if alternative is None:
                    self._remove(node.start_byte, node.end_byte, node)
                else:
                    # JavaScript wraps the else part in an else_clause; keep only its body.
                    body = alternative
                    if body.type == "else_clause" and body.named_child_count:
                        body = body.named_children[-1]
                    self._remove(node.start_byte, body.start_byte)

    def unused_declarations(self) -> None:
        """Declarations nobody reads, repeated until nothing changes."""
        while True:
            counts = self._name_counts()
            changed = False
            for node in _walk(self.root):
                if node.type not in _LOCAL_DECLARATIONS[self.lang] or self._inside_removed(node):
                    continue
                if node.parent is not None and node.parent.type in ("export_statement", "for_statement",
                                                                     "for_in_statement", "enhanced_for_statement",
                                                                     "for_range_loop", "condition_clause"):
                    continue
                top_level = self._enclosing_function(node) is None
                if self.lang == "java" and top_level:
                    continue  # (fields are field_declaration anyway)
                if self.lang in ("csharp", "go", "ruby", "php"):
                    if self._new_declaration(node, counts, top_level):
                        self._remove(node.start_byte, node.end_byte, node)
                        changed = True
                    continue
                if self.lang in _C_FAMILY:
                    if self._c_declaration(node, counts, top_level):
                        self._remove(node.start_byte, node.end_byte, node)
                        changed = True
                    continue
                declarators = [c for c in node.named_children if c.type == "variable_declarator"]
                if not declarators:
                    continue
                removable = True
                for decl in declarators:
                    name = decl.child_by_field_name("name")
                    value = decl.child_by_field_name("value")
                    if name is None or name.type != "identifier":
                        removable = False  # destructuring or something unusual
                        break
                    text = _text(name)
                    if counts.get(text, 0) > 1 or not self._pure(value):
                        removable = False
                        break
                    if top_level and text in self.external:
                        removable = False
                        break
                if removable:
                    self._remove(node.start_byte, node.end_byte, node)
                    changed = True
            if not changed:
                return

    def everything_removed(self) -> bool:
        statements = [c for c in self.root.named_children if c.type != "comment"]
        return bool(statements) and all(self._inside_removed(s) for s in statements)


def strip_dead_code(source: str, language: str, external_names: set[str] | None = None) -> str:
    """`source` (Java, JavaScript, C or C++) without unused local declarations,
    dead branches and unreachable statements. Unparseable code comes back unchanged."""
    parser = _parser(language)
    if parser is None:
        return source
    # Fence lines are tried first: in JavaScript ``` is a valid (template
    # string) token, so a pasted fence doesn't even show up as a syntax error.
    tree = None
    if _FENCE_LINE.search(source):
        unfenced = _FENCE_LINE.sub("", source)
        candidate = parser.parse(unfenced.encode("utf-8"))
        if not candidate.root_node.has_error:
            source, tree = unfenced, candidate
    data = source.encode("utf-8")
    if tree is None:
        tree = parser.parse(data)
        if tree.root_node.has_error:
            return source

    cleaner = _Cleaner(language, tree.root_node, external_names or set())
    # PHP variables can be read by name at run time; then no variable is safe to drop.
    cleaner.php_dynamic = language == "php" and bool(re.search(r"\bcompact\s*\(|\bextract\s*\(|\$\$|"
                                                                   r"get_defined_vars", source))
    cleaner.dead_code()
    cleaner.unused_declarations()
    if not cleaner.removed or cleaner.everything_removed():
        return source

    merged: list[list[int]] = []
    for start, end in sorted(cleaner.removed):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    out, last = [], 0
    for start, end in merged:
        out.append(data[last:start])
        last = end
    out.append(data[last:])
    return b"".join(out).decode("utf-8", errors="replace")
