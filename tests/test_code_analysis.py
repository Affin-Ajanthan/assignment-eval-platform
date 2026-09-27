import textwrap

from app.evaluator.code_analysis import analyze_directory, analyze_python


GOOD_CODE = textwrap.dedent(
    '''
    def bubble_sort(items):
        """Sort a list of numbers in ascending order."""
        n = len(items)
        for i in range(n):
            for j in range(0, n - i - 1):
                if items[j] > items[j + 1]:
                    items[j], items[j + 1] = items[j + 1], items[j]
        return items
    '''
)

MESSY_CODE = textwrap.dedent(
    """
    def BadlyNamedFunction(x):
        # TODO: fix this
        try:
            if x > 0:
                if x > 10:
                    if x > 100:
                        if x > 1000:
                            return x * 2
            return x
        except:
            pass
    """
)

BROKEN_CODE = "def broken(:\n    pass"


def test_analyze_python_good_code():
    report = analyze_python(GOOD_CODE, "solution.py")
    assert report.function_count == 1
    assert report.docstring_coverage == 1.0
    assert report.parse_error is None
    assert report.quality_score > 80


def test_analyze_python_messy_code_flags_issues():
    report = analyze_python(MESSY_CODE, "messy.py")
    assert report.function_count == 1
    assert any("not snake_case" in v for v in report.naming_violations)
    assert any("bare 'except:'" in issue for issue in report.issues)
    assert any("TODO" in issue for issue in report.issues)
    assert report.avg_complexity > 3
    assert report.quality_score < 80


def test_analyze_python_syntax_error_does_not_crash():
    report = analyze_python(BROKEN_CODE, "broken.py")
    assert report.parse_error is not None
    assert report.function_count == 0
    assert report.issues


def test_analyze_directory(tmp_path):
    (tmp_path / "a.py").write_text(GOOD_CODE)
    (tmp_path / "b.py").write_text(MESSY_CODE)
    reports = analyze_directory(tmp_path)
    assert len(reports) == 2
    names = {r.filename for r in reports}
    assert names == {"a.py", "b.py"}


def test_identifiers_property():
    report = analyze_python(GOOD_CODE, "solution.py")
    assert "bubble_sort" in report.identifiers
