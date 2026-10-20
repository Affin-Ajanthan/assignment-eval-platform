"""
Jupyter notebooks (.ipynb) as code.

A notebook is a JSON file of cells. For every check the platform runs on code
(token similarity, UniXcoder, the dead-code cleanup, code analysis, the
AI-code signal, the grader's view of the code) only the *code cells* matter,
as one Python program:

* outputs are dropped -- printed results, tracebacks and base64 images are not
  the student's code, and two students running the same code would otherwise
  look alike because of identical output;
* IPython-only lines (``%matplotlib inline``, ``%%time``, ``!pip install x``)
  are blanked, since they are not Python;
* markdown cells are kept separately: they are the student's explanation and
  feed the cross-modal consistency check as documentation.

Notebooks are given the name ``<name>.ipynb.py`` when passed on, so everything
that picks a language from the file extension treats them as Python.
"""

from __future__ import annotations

import json
from pathlib import Path

NOTEBOOK_SUFFIX = ".ipynb"


def _cells(text: str) -> list[dict]:
    """The cells of a notebook (nbformat 4, or the older 3 with worksheets);
    [] for anything that isn't a readable notebook."""
    try:
        data = json.loads(text)
    except (ValueError, RecursionError):
        return []
    if not isinstance(data, dict):
        return []
    cells = data.get("cells")
    if cells is None:  # nbformat 3
        cells = [c for sheet in data.get("worksheets") or [] if isinstance(sheet, dict)
                 for c in sheet.get("cells") or []]
    return [c for c in cells if isinstance(c, dict)] if isinstance(cells, list) else []


def _source(cell: dict) -> str:
    source = cell.get("source", cell.get("input", ""))  # "input" in nbformat 3 code cells
    if isinstance(source, list):
        return "".join(s for s in source if isinstance(s, str))
    return source if isinstance(source, str) else ""


def _is_ipython_line(line: str) -> bool:
    stripped = line.lstrip()
    return stripped.startswith(("%", "!"))


def notebook_code(text: str) -> str:
    """The code cells of a notebook as one Python source (cells separated by a
    blank line, IPython magics and shell lines blanked). '' if unreadable."""
    blocks = []
    for cell in _cells(text):
        if cell.get("cell_type") != "code":
            continue
        source = _source(cell)
        if source.lstrip().startswith("%%"):  # a cell magic (%%time, %%bash, ...) changes the whole cell
            if source.lstrip().startswith(("%%time", "%%timeit", "%%capture")):
                source = source.split("\n", 1)[1] if "\n" in source else ""
            else:
                continue
        lines = ["" if _is_ipython_line(line) else line for line in source.splitlines()]
        if any(line.strip() for line in lines):
            blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def notebook_markdown(text: str) -> str:
    """The markdown cells of a notebook (the student's explanations)."""
    return "\n\n".join(_source(c) for c in _cells(text) if c.get("cell_type") == "markdown").strip()


def read_code(path: Path) -> tuple[str, str]:
    """(name to use for language detection, source text) of one code file.
    A notebook becomes its code cells under the name `<name>.ipynb.py`."""
    path = Path(path)
    text = path.read_text(encoding="utf-8", errors="ignore")
    if path.suffix.lower() == NOTEBOOK_SUFFIX:
        return path.name + ".py", notebook_code(text)
    return path.name, text
