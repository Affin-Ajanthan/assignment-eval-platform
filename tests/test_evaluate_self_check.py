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


def test_sample_subsets_are_seeded_unique_and_built_around_copies():
    ids = [str(i) for i in range(1, 11)]
    groups = [["1", "2", "3"], ["5", "6"]]
    a = ev.sample_subsets(ids, groups, 3, 20, seed=7)
    assert a == ev.sample_subsets(ids, groups, 3, 20, seed=7)      # same seed, same classes
    assert a != ev.sample_subsets(ids, groups, 3, 20, seed=8)
    assert len(a) == len(set(a)) == 20 and all(len(s) == 3 and len(set(s)) == 3 for s in a)
    pairs = ev.positive_pairs(groups)
    with_copy = [s for s in a if any(frozenset(p) in pairs for p in __import__("itertools").combinations(s, 2))]
    assert len(with_copy) >= 10                                      # every other class is built around a copy
    # asking for more classes than exist stops instead of looping forever
    assert len(ev.sample_subsets(ids, groups, 2, 500, seed=1)) <= 45
    assert ev.sample_subsets(ids, None, 2, 5, seed=1)               # no known copies: uniform draws only


def test_tally_counts_each_pair_under_the_old_and_new_rule():
    counts = {}
    ev.tally(counts, copy=True, old_band="low", new_band="moderate")    # a copy the new rule catches
    ev.tally(counts, copy=True, old_band="high", new_band="high")
    ev.tally(counts, copy=False, old_band="low", new_band="low")
    ev.tally(counts, copy=False, old_band="low", new_band="moderate")   # an honest pair newly flagged
    assert counts == {"pairs": 4, "copy": 2, "copy_old": 1, "copy_new": 2,
                      "honest": 2, "honest_old": 0, "honest_new": 1}
