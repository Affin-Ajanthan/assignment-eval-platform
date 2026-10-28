"""
Remove code that does nothing from Python source before semantic comparison.

Adding unused variables, junk imports or dead branches is a cheap way to
disguise a copy. Because ``anonymize_identifiers`` numbers names in order of
first appearance, one inserted variable renumbers every later name, and on
small programs UniXcoder's score for an exact copy dropped from 1.0 to about
0.70 (tests/unixcoder_structural, TC16/TC17). Removing the junk first undoes
that.

What is removed (conservatively -- when in doubt, code is kept):

* assignments (``x = ...``, ``x: int = ...``, ``x += ...``) to a simple name
  that is never read anywhere in the file, when the value has no side
  effects (literals, names, arithmetic, subscripts, comprehensions and a few
  pure builtins such as len/sorted -- ``x = save()`` is kept);
* imports whose names are never used;
* ``if``/``while`` blocks whose condition is a false constant
  (``if False:``, ``if 0:``); an ``else`` branch is kept;
* statements after ``return``/``raise``/``break``/``continue`` in a block.

A module-level name is only removed if it also doesn't appear in any other
file of the same submission (``external_names``): another file may import a
constant. Never touched: class-body assignments (they are attributes, read
as ``self.x``), names declared ``global``/``nonlocal``, and dunder names.
If nothing at all would be left, the file is returned unchanged (it is data
rather than junk added to real code).
Removal repeats until nothing changes, since dropping one junk statement can
make another one unused. The source is cut at exact positions, never
rewritten, so everything that remains is character-for-character the same.
Code that doesn't parse is returned unchanged.
"""

from __future__ import annotations

import ast
import re

_PURE_CALLS = {"len", "str", "int", "float", "bool", "list", "dict", "set", "tuple", "range", "abs",
               "min", "max", "sum", "sorted", "round", "reversed", "enumerate", "zip", "frozenset"}
# Methods that only read (str/list/dict/set): `x = data.values()` is junk if x
# is never used. Anything that changes state (pop, append, write, ...) is not here.
_PURE_METHODS = {"values", "keys", "items", "get", "copy", "count", "index", "find", "rfind",
                 "strip", "lstrip", "rstrip", "split", "rsplit", "splitlines", "lower", "upper", "title",
                 "capitalize", "casefold", "replace", "join", "format", "startswith", "endswith",
                 "isdigit", "isalpha", "isalnum", "isnumeric", "isspace", "isupper", "islower",
                 "ljust", "rjust", "center", "zfill", "encode", "decode", "union", "intersection",
                 "difference", "issubset", "issuperset"}
_IMPURE = (ast.Await, ast.Yield, ast.YieldFrom, ast.NamedExpr)
# Markdown code fences (``` or ```python) left in a file pasted from a chat or web page.
_FENCE_LINE = re.compile(r"^[ \t]*```[\w+-]*[ \t]*$", re.MULTILINE)
_TERMINATORS = (ast.Return, ast.Raise, ast.Break, ast.Continue)
_BLOCK_FIELDS = ("body", "orelse", "finalbody")


def _pure(node: ast.AST | None) -> bool:
    """True if evaluating the expression can't have side effects we care about."""
    if node is None:
        return True
    for sub in ast.walk(node):
        if isinstance(sub, _IMPURE):
            return False
        if isinstance(sub, ast.Call):
            func = sub.func
            if not ((isinstance(func, ast.Name) and func.id in _PURE_CALLS)
                    or (isinstance(func, ast.Attribute) and func.attr in _PURE_METHODS)):
                return False
    return True


def _false_constant(test: ast.AST) -> bool:
    return isinstance(test, ast.Constant) and not test.value


def _blocks(tree: ast.AST):
    """Every statement list in the tree (function/loop/if/try bodies, except
    handlers and match cases are all visited by ast.walk)."""
    for node in ast.walk(tree):
        for field in _BLOCK_FIELDS:
            block = getattr(node, field, None)
            if isinstance(block, list) and block and isinstance(block[0], ast.stmt):
                yield block


def _inside(node: ast.AST, removed: set[int]) -> bool:
    return id(node) in removed


def names_in(source: str) -> set[str]:
    """Every identifier-like word in a file (code, strings and comments alike):
    a deliberately generous answer to "might this file use that name?"."""
    return set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", source))


def _find_removals(tree: ast.Module, external: set[str]) -> list[tuple[ast.AST, ast.AST | None]]:
    """(node, keep_from) pairs: remove `node`; if `keep_from` is set, only up
    to where that statement starts (used to keep an ``else`` branch)."""
    parents: dict[int, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[id(child)] = parent

    protected: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Global, ast.Nonlocal)):
            protected.update(node.names)

    def scope(node: ast.AST) -> str:
        """'function', 'class' or 'module': the nearest enclosing scope."""
        parent = parents.get(id(node))
        while parent is not None:
            if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                return "function"
            if isinstance(parent, ast.ClassDef):
                return "class"
            parent = parents.get(id(parent))
        return "module"

    removed: set[int] = set()  # ids of removed nodes (and everything inside them)
    result: list[tuple[ast.AST, ast.AST | None]] = []

    def remove(node: ast.AST, keep_from: ast.AST | None = None) -> None:
        result.append((node, keep_from))
        keep = set()
        if keep_from is not None:
            for stmt in node.orelse:
                keep.update(id(n) for n in ast.walk(stmt))
        for sub in ast.walk(node):
            if id(sub) not in keep:
                removed.add(id(sub))

    # Dead branches and unreachable statements don't depend on name usage: once.
    for block in list(_blocks(tree)):
        for i, stmt in enumerate(block):
            if isinstance(stmt, _TERMINATORS) and i + 1 < len(block):
                for dead in block[i + 1:]:
                    if not _inside(dead, removed):
                        remove(dead)
                break
    for node in ast.walk(tree):
        if _inside(node, removed):
            continue
        if isinstance(node, ast.While) and _false_constant(node.test) and not node.orelse:
            remove(node)
        elif isinstance(node, ast.If) and _false_constant(node.test):
            if not node.orelse:
                remove(node)
            elif not (len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If)):  # skip elif chains
                remove(node, keep_from=node.orelse[0])

    # Unused assignments and imports: repeat until stable.
    while True:
        used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Load, ast.Del))
                and not _inside(n, removed)}
        # (`x += 1` stores to x without a Load node, so it never counts as a use.)
        changed = False
        for node in ast.walk(tree):
            if _inside(node, removed):
                continue
            name = None
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                bound = [(a.asname or a.name).split(".")[0] for a in node.names]
                if "*" not in bound and not any(b in used or b in protected for b in bound):
                    remove(node)
                    changed = True
                continue
            where = scope(node)
            if where == "class":
                continue  # a class attribute, read as self.x
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                name, value = node.targets[0].id, node.value
            elif isinstance(node, (ast.AnnAssign, ast.AugAssign)) and isinstance(node.target, ast.Name):
                name, value = node.target.id, node.value
            if name is None or name in used or name in protected or name.startswith("__"):
                continue
            if where == "module" and name in external:
                continue  # another file of the submission may import it
            if _pure(value):
                remove(node)
                changed = True
        if not changed:
            return result


def strip_python_dead_code(source: str, external_names: set[str] | None = None,
                           keep_lines: bool = False) -> str:
    """`source` without unused assignments/imports, dead branches and
    unreachable statements. `external_names` are the names that appear in
    the submission's other files (module-level names among them are kept).
    Code that doesn't parse is returned unchanged, except that stray Markdown
    code fences (a file pasted from a chat window) are dropped first.
    `keep_lines`: removed code leaves its line breaks behind, so every remaining
    line keeps its line number (for fingerprints, whose matches are shown by line)."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError):
        unfenced = _FENCE_LINE.sub("", source)
        if unfenced == source:
            return source
        try:
            tree = ast.parse(unfenced)
        except (SyntaxError, ValueError, RecursionError):
            return source
        source = unfenced
    removals = _find_removals(tree, external_names or set())
    if not removals:
        return source
    fully_removed = {id(node) for node, keep_from in removals if keep_from is None}
    if all(id(stmt) in fully_removed for stmt in tree.body):
        return source  # nothing would be left: the file is data, not junk added to code

    data = source.encode("utf-8")  # ast column offsets are UTF-8 byte offsets
    line_starts = [0]
    for line in data.splitlines(keepends=True):
        line_starts.append(line_starts[-1] + len(line))

    def offset(lineno: int, col: int) -> int:
        return line_starts[lineno - 1] + col

    spans = []
    for node, keep_from in removals:
        start = offset(node.lineno, node.col_offset)
        end = (offset(keep_from.lineno, keep_from.col_offset) if keep_from is not None
               else offset(node.end_lineno, node.end_col_offset))
        spans.append((start, end))
    spans.sort()
    merged: list[list[int]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])

    out, last = [], 0
    for start, end in merged:
        out.append(data[last:start])
        if keep_lines:
            out.append(b"\n" * data.count(b"\n", start, end))
        last = end
    out.append(data[last:])
    return b"".join(out).decode("utf-8", errors="replace")
