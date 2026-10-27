"""The metric helpers of scripts/evaluate_self_check.py (the script itself
needs the labelled data on disk, so it is not run here)."""

import importlib.util
import json
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
_spec = importlib.util.spec_from_file_location("evaluate_self_check", SCRIPTS / "evaluate_self_check.py")
ev = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ev)


def test_groups_are_not_merged_into_each_other():
    # 01 copied by 03, and 10 paraphrased 01: 03 and 10 are NOT a known pair.
    pairs = ev.positive_pairs([["01", "03"], ["01", "10"]])
    assert pairs == {frozenset({"01", "03"}), frozenset({"01", "10"})}
    assert ev.positive_students([["01", "03"], ["01", "10"]]) == {"01", "03", "10"}


def test_every_pair_inside_a_group_is_a_copy_pair():
    pairs = ev.positive_pairs([["1", "2", "3"]])
    assert pairs == {frozenset({"1", "2"}), frozenset({"1", "3"}), frozenset({"2", "3"})}
    assert ev.positive_pairs(None) == set()


def test_confusion_counts_and_rates():
    c = ev.confusion(predicted={"a", "b", "x"}, actual={"a", "b", "c"}, universe={"a", "b", "c", "x", "y"})
    assert (c["tp"], c["fp"], c["fn"], c["tn"]) == (2, 1, 1, 1)
    assert c["precision"] == round(2 / 3, 3) and c["recall"] == round(2 / 3, 3)
    empty = ev.confusion(set(), set(), {"a"})
    assert empty["precision"] is None and empty["recall"] is None and empty["tn"] == 1


def test_totals_add_up_across_sets():
    total = {}
    ev.add(total, ev.confusion({"a"}, {"a", "b"}, {"a", "b", "c"}))
    ev.add(total, ev.confusion({"x", "y"}, {"x"}, {"x", "y"}))
    assert (total["tp"], total["fp"], total["fn"], total["tn"]) == (2, 1, 1, 1)
    assert total["precision"] == round(2 / 3, 3)


def test_manifest_is_well_formed():
    manifest = json.loads((SCRIPTS / "self_check_eval_sets.json").read_text(encoding="utf-8"))
    assert manifest["sets"]
    for s in manifest["sets"]:
        students = set(s["students"])
        for part in ("code", "report"):
            for group in s.get(f"{part}_groups") or []:
                assert set(group) <= students, (s["name"], group)
        if s.get("report_groups"):
            assert all("report" in files for files in s["students"].values()), s["name"]
        assert all("code" in files for files in s["students"].values()), s["name"]
