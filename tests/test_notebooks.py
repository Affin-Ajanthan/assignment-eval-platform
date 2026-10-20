"""Jupyter notebooks (.ipynb): code cells are read as Python by every code
check (app/notebook.py), outputs and IPython-only lines are ignored."""

import io
import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.evaluator.code_analysis import analyze_directory, read_sources
from app.evaluator.semantic_consistency import extract_code_documentation
from app.main import app as fastapi_app
from app.notebook import notebook_code, notebook_markdown, read_code
from app.similarity.semantic import normalize_code
from tests.auth_helpers import auth_headers, setup_subject_with_users, submit

client = TestClient(fastapi_app)

PROGRAM = '''def average(marks):
    total = 0
    for m in marks:
        total += m
    return total / len(marks)


print(average([70, 80, 90]))
'''


def notebook(cells, nbformat=4) -> str:
    def cell(kind, source, outputs=None):
        c = {"cell_type": kind, "metadata": {}, "source": source.splitlines(keepends=True)}
        if kind == "code":
            c.update(execution_count=1, outputs=outputs or [])
        return c

    return json.dumps({"nbformat": nbformat, "nbformat_minor": 5, "metadata": {},
                       "cells": [cell(*c) for c in cells]})


NOTEBOOK = notebook([
    ("markdown", "# Grade average\nThis notebook computes the class average of the marks."),
    ("code", "%matplotlib inline\n!pip install numpy\n" + PROGRAM.split("\n\n\n")[0],
     [{"output_type": "stream", "name": "stdout", "text": ["something printed\n"]},
      {"output_type": "display_data", "data": {"image/png": "iVBORw0KGgoAAAANSUhEUg" * 50}}]),
    ("code", "print(average([70, 80, 90]))"),
])


# ---- conversion -------------------------------------------------------------------

def test_code_cells_become_python_and_outputs_magics_are_dropped():
    code = notebook_code(NOTEBOOK)
    assert "def average(marks):" in code and "print(average([70, 80, 90]))" in code
    assert "%matplotlib" not in code and "pip install" not in code
    assert "something printed" not in code and "iVBORw0K" not in code
    assert "# Grade average" not in code  # markdown is not code
    compile(code, "nb.py", "exec")  # valid Python


def test_markdown_cells_are_kept_separately():
    assert "computes the class average" in notebook_markdown(NOTEBOOK)


def test_cell_magics():
    nb = notebook([("code", "%%time\nx = 1\nprint(x)"), ("code", "%%bash\nls -la"), ("code", "print(2)")])
    code = notebook_code(nb)
    assert "x = 1" in code and "print(2)" in code and "ls -la" not in code


def test_old_nbformat_3_and_invalid_files():
    nb3 = json.dumps({"nbformat": 3, "worksheets": [{"cells": [
        {"cell_type": "code", "input": ["x = 5\n", "print(x)\n"], "outputs": []}]}]})
    assert "x = 5" in notebook_code(nb3)
    assert notebook_code("not json at all") == ""
    assert notebook_code("[1, 2, 3]") == ""


def test_read_code_names_notebooks_as_python(tmp_path):
    (tmp_path / "work.ipynb").write_text(NOTEBOOK, encoding="utf-8")
    name, source = read_code(tmp_path / "work.ipynb")
    assert name == "work.ipynb.py" and "def average" in source


def test_notebook_and_py_file_normalize_the_same():
    # The same program as a .py file and as a notebook looks identical to UniXcoder.
    assert normalize_code(notebook_code(NOTEBOOK), "work.ipynb.py") == normalize_code(PROGRAM, "work.py")


# ---- the code checks see notebooks ---------------------------------------------------

def test_code_analysis_grader_view_and_documentation_include_notebooks(tmp_path):
    (tmp_path / "work.ipynb").write_text(NOTEBOOK, encoding="utf-8")
    reports = analyze_directory(tmp_path)
    assert len(reports) == 1 and reports[0].filename == "work.ipynb"
    sources = read_sources(tmp_path)
    assert "def average" in sources["work.ipynb"] and "iVBORw0K" not in sources["work.ipynb"]
    assert "computes the class average" in extract_code_documentation(tmp_path)


def test_single_notebook_upload_and_similarity_against_a_py_copy():
    subject, tok, _ = setup_subject_with_users(client)
    name = "Notebook Assignment"
    nb = submit(client, subject["id"], name,
                {"code": ("analysis.ipynb", io.BytesIO(NOTEBOOK.encode()), "application/x-ipynb+json")})
    assert nb.status_code == 200, nb.text
    py = submit(client, subject["id"], name, {"code": ("analysis.py", io.BytesIO(PROGRAM.encode()), "text/x-python")})
    assert py.status_code == 200, py.text

    body = client.post(f"/subjects/{subject['id']}/assignments/{name}/check-similarity", headers=auth_headers(tok)).json()
    (pair,) = body["pairs"]
    assert pair["jaccard"] == 1.0 and pair["flag_level"] == "high"  # same code: one is a notebook, one a .py file


def test_notebook_inside_a_zip_is_checked():
    subject, tok, _ = setup_subject_with_users(client)
    name = "Notebook Zip Assignment"
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("project/analysis.ipynb", NOTEBOOK)
    buf.seek(0)
    assert submit(client, subject["id"], name, {"code": ("project.zip", buf, "application/zip")}).status_code == 200
    submit(client, subject["id"], name, {"code": ("analysis.py", io.BytesIO(PROGRAM.encode()), "text/x-python")})
    body = client.post(f"/subjects/{subject['id']}/assignments/{name}/check-similarity", headers=auth_headers(tok)).json()
    assert body["pairs"][0]["jaccard"] == 1.0
