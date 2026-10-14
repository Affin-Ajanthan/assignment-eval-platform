"""
Remove code that does nothing from Java and JavaScript before semantic
comparison -- the counterpart of python_cleanup for languages Python's `ast`
can't read. Parsing uses tree-sitter (tree-sitter-java, tree-sitter-javascript).

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

LANGUAGE_BY_EXTENSION = {".java": "java", ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript"}

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
}
_PURE_CONSTRUCTORS = {
    "java": {"ArrayList", "LinkedList", "HashMap", "TreeMap", "LinkedHashMap", "HashSet", "TreeSet",
             "LinkedHashSet", "ArrayDeque", "StringBuilder", "String", "Object", "Integer", "Double"},
    "javascript": {"Array", "Map", "Set", "Object", "WeakMap", "WeakSet", "String", "Number", "Date"},
}
# Node types that make an initializer impure regardless of what they contain.
_IMPURE_NODES = {
    "java": {"assignment_expression", "update_expression"},
    "javascript": {"assignment_expression", "augmented_assignment_expression", "update_expression",
                   "await_expression", "yield_expression"},
}
_LOCAL_DECLARATIONS = {"java": {"local_variable_declaration"},
                       "javascript": {"lexical_declaration", "variable_declaration"}}
_FUNCTION_NODES = {
    "java": {"method_declaration", "constructor_declaration", "lambda_expression"},
    "javascript": {"function_declaration", "function_expression", "arrow_function", "method_definition",
                   "generator_function_declaration", "generator_function"},
}
_BLOCKS = {"java": {"block", "switch_block_statement_group"}, "javascript": {"statement_block", "switch_case"}}
_TERMINATORS = {"return_statement", "throw_statement", "break_statement", "continue_statement"}
_HOISTED = {"function_declaration", "generator_function_declaration", "class_declaration"}
_NAME_NODES = {"identifier", "shorthand_property_identifier", "shorthand_property_identifier_pattern"}


@lru_cache(maxsize=None)
def _parser(language: str):
    """A tree-sitter parser for `language`, or None if tree-sitter isn't installed."""
    try:
        from tree_sitter import Language, Parser
        if language == "java":
            import tree_sitter_java as grammar
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
    """`(false)` / `(0)` as an if/while condition."""
    inner = node
    while inner is not None and inner.type == "parenthesized_expression" and inner.named_child_count == 1:
        inner = inner.named_children[0]
    return inner is not None and (inner.type == "false" or (inner.type in ("decimal_integer_literal", "number")
                                                              and _text(inner) == "0"))


class _Cleaner:
    def __init__(self, language: str, root, external: set[str]):
        self.lang = language
        self.root = root
        self.external = external
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

    def _pure(self, node) -> bool:
        if node is None:
            return True
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
                if name is None or _text(name) not in _PURE_METHODS[self.lang]:
                    return False
            if sub.type in ("object_creation_expression", "new_expression"):
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
        return counts

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
                            if dead.type in ("switch_label",):
                                continue
                            self._remove(dead.start_byte, dead.end_byte, dead)
                        break
            elif node.type == "while_statement" and _false_condition(node.child_by_field_name("condition")):
                self._remove(node.start_byte, node.end_byte, node)
            elif node.type == "if_statement" and _false_condition(node.child_by_field_name("condition")):
                alternative = node.child_by_field_name("alternative")
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
                                                                     "for_in_statement", "enhanced_for_statement"):
                    continue
                top_level = self._enclosing_function(node) is None
                if self.lang == "java" and top_level:
                    continue  # (fields are field_declaration anyway)
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
    """`source` (Java or JavaScript) without unused local declarations, dead
    branches and unreachable statements. Unparseable code comes back unchanged."""
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
