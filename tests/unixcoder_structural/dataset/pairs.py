"""
Structural-transformation pairs for the UniXcoder robustness batch (Python).

Every pair defines the same entry function in an original and a modified
program. ``inputs`` are representative argument tuples (edge cases);
``random_inputs`` adds seeded random cases. The test executes both programs
and compares outputs to verify the claimed behaviour.

Categories (as requested):
  superficial  -- same source with superficial changes (reference)
  structural   -- similar implementation with structural changes
  equivalent   -- functionally equivalent but differently implemented
  unrelated    -- different tasks (control)
"""

from __future__ import annotations

import random
import textwrap


def d(src: str) -> str:
    return textwrap.dedent(src).strip("\n") + "\n"


def _ints(rng, n=8, lo=-20, hi=120):
    return [rng.randint(lo, hi) for _ in range(rng.randint(0, n))]


def _rand(fn):
    """Seeded random input generator: 200 argument tuples."""
    rng = random.Random(1234)
    return [fn(rng) for _ in range(200)]


WORDS = ["apple", "Banana", "kiwi", "", "fig", "apple", "Cherry", "banana", "date"]

PAIRS = [
    # ------------------------------------------------------------------ structural
    {"id": "TC01", "category": "structural", "transformation": "for loop -> while loop", "entry": "sum_even_squares",
     "original": d("""
        def sum_even_squares(n):
            total = 0
            for i in range(n + 1):
                if i % 2 == 0:
                    total += i * i
            return total
        """),
     "modified": d("""
        def sum_even_squares(n):
            total = 0
            i = 0
            while i <= n:
                if i % 2 == 0:
                    total += i * i
                i += 1
            return total
        """),
     "inputs": [(0,), (1,), (2,), (10,), (-3,)], "random": lambda r: (r.randint(-5, 300),)},

    {"id": "TC02", "category": "structural", "transformation": "while loop -> for loop", "entry": "count_vowels",
     "original": d("""
        def count_vowels(text):
            count = 0
            i = 0
            while i < len(text):
                if text[i].lower() in "aeiou":
                    count += 1
                i += 1
            return count
        """),
     "modified": d("""
        def count_vowels(text):
            count = 0
            for i in range(len(text)):
                if text[i].lower() in "aeiou":
                    count += 1
            return count
        """),
     "inputs": [("",), ("xyz",), ("AEIOU",), ("Programming is fun",)],
     "random": lambda r: ("".join(r.choice("abcdeEIOUxyz ") for _ in range(r.randint(0, 30))),)},

    {"id": "TC03", "category": "structural", "transformation": "if/else statement -> conditional expression",
     "entry": "classify",
     "original": d("""
        def classify(scores):
            labels = []
            for s in scores:
                if s >= 50:
                    label = "pass"
                else:
                    label = "fail"
                labels.append(label)
            return labels
        """),
     "modified": d("""
        def classify(scores):
            labels = []
            for s in scores:
                label = "pass" if s >= 50 else "fail"
                labels.append(label)
            return labels
        """),
     "inputs": [([],), ([49, 50, 51],), ([0, 100],)], "random": lambda r: (_ints(r),)},

    {"id": "TC04", "category": "structural", "transformation": "conditional expression -> if/else statement",
     "entry": "clamp_all",
     "original": d("""
        def clamp_all(values, low, high):
            out = []
            for v in values:
                v = low if v < low else v
                v = high if v > high else v
                out.append(v)
            return out
        """),
     "modified": d("""
        def clamp_all(values, low, high):
            out = []
            for v in values:
                if v < low:
                    v = low
                else:
                    v = v
                if v > high:
                    v = high
                else:
                    v = v
                out.append(v)
            return out
        """),
     "inputs": [([], 0, 10), ([-5, 5, 15], 0, 10), ([3], 3, 3)],
     "random": lambda r: (_ints(r), r.randint(-10, 20), r.randint(20, 100))},

    {"id": "TC05", "category": "structural", "transformation": "list comprehension -> explicit loop",
     "entry": "squares_of_odds",
     "original": d("""
        def squares_of_odds(values):
            return [v * v for v in values if v % 2 == 1]
        """),
     "modified": d("""
        def squares_of_odds(values):
            result = []
            for v in values:
                if v % 2 == 1:
                    result.append(v * v)
            return result
        """),
     "inputs": [([],), ([1, 2, 3, 4, 5],), ([-3, -2],)], "random": lambda r: (_ints(r),)},

    {"id": "TC06", "category": "structural", "transformation": "explicit loop -> list comprehension",
     "entry": "word_lengths",
     "original": d("""
        def word_lengths(words):
            lengths = []
            for w in words:
                if w:
                    lengths.append(len(w))
            return lengths
        """),
     "modified": d("""
        def word_lengths(words):
            return [len(w) for w in words if w]
        """),
     "inputs": [([],), (WORDS,), ([""],)], "random": lambda r: (r.sample(WORDS, r.randint(0, len(WORDS))),)},

    {"id": "TC07", "category": "structural", "transformation": "extract part of a function into a helper",
     "entry": "average_valid",
     "original": d("""
        def average_valid(scores):
            total = 0
            count = 0
            for s in scores:
                if 0 <= s <= 100:
                    total += s
                    count += 1
            if count == 0:
                return 0.0
            return total / count
        """),
     "modified": d("""
        def is_valid(score):
            return 0 <= score <= 100


        def average_valid(scores):
            total = 0
            count = 0
            for s in scores:
                if is_valid(s):
                    total += s
                    count += 1
            if count == 0:
                return 0.0
            return total / count
        """),
     "inputs": [([],), ([-1, 101],), ([0, 50, 100],)], "random": lambda r: (_ints(r),)},

    {"id": "TC08", "category": "structural", "transformation": "inline a helper function", "entry": "invoice_total",
     "original": d("""
        def tax(amount):
            return amount * 15 // 100


        def invoice_total(prices):
            subtotal = 0
            for p in prices:
                subtotal += p
            return subtotal + tax(subtotal)
        """),
     "modified": d("""
        def invoice_total(prices):
            subtotal = 0
            for p in prices:
                subtotal += p
            return subtotal + subtotal * 15 // 100
        """),
     "inputs": [([],), ([100],), ([19, 1, 33],)], "random": lambda r: (_ints(r, lo=0, hi=1000),)},

    {"id": "TC09", "category": "structural", "transformation": "reorder independent statements", "entry": "stats",
     "original": d("""
        def stats(values):
            count = len(values)
            smallest = min(values)
            largest = max(values)
            total = sum(values)
            mean = total / count
            return {"count": count, "min": smallest, "max": largest, "mean": mean}
        """),
     "modified": d("""
        def stats(values):
            total = sum(values)
            largest = max(values)
            count = len(values)
            smallest = min(values)
            mean = total / count
            return {"count": count, "min": smallest, "max": largest, "mean": mean}
        """),
     "inputs": [([5],), ([3, 1, 2],), ([-4, 4],)], "random": lambda r: ([r.randint(-50, 50) for _ in range(r.randint(1, 9))],)},

    {"id": "TC10", "category": "structural", "transformation": "reorder independent function definitions",
     "entry": "report",
     "original": d("""
        def mean(values):
            return sum(values) / len(values)


        def spread(values):
            return max(values) - min(values)


        def report(values):
            return round(mean(values), 2), spread(values)
        """),
     "modified": d("""
        def report(values):
            return round(mean(values), 2), spread(values)


        def spread(values):
            return max(values) - min(values)


        def mean(values):
            return sum(values) / len(values)
        """),
     "inputs": [([1],), ([1, 2, 3],)], "random": lambda r: ([r.randint(-50, 50) for _ in range(r.randint(1, 9))],)},

    {"id": "TC11", "category": "structural", "transformation": "split one function into multiple functions",
     "entry": "summarize_marks",
     "original": d("""
        def summarize_marks(lines):
            marks = []
            for line in lines:
                name, mark = line.split(",")
                mark = int(mark)
                if 0 <= mark <= 100:
                    marks.append(mark)
            if not marks:
                return None
            highest = max(marks)
            average = sum(marks) / len(marks)
            return highest, round(average, 1)
        """),
     "modified": d("""
        def parse_marks(lines):
            marks = []
            for line in lines:
                name, mark = line.split(",")
                marks.append(int(mark))
            return marks


        def keep_valid(marks):
            return [m for m in marks if 0 <= m <= 100]


        def summarize_marks(lines):
            marks = keep_valid(parse_marks(lines))
            if not marks:
                return None
            highest = max(marks)
            average = sum(marks) / len(marks)
            return highest, round(average, 1)
        """),
     "inputs": [([],), (["a,50", "b,101", "c,90"],), (["x,-1"],)],
     "random": lambda r: ([f"s{i},{r.randint(-10, 110)}" for i in range(r.randint(0, 8))],)},

    {"id": "TC12", "category": "structural", "transformation": "merge multiple functions into one",
     "entry": "normalize_name",
     "original": d("""
        def strip_spaces(name):
            return " ".join(name.split())


        def capitalize_words(name):
            return " ".join(part.capitalize() for part in name.split(" "))


        def normalize_name(name):
            cleaned = strip_spaces(name)
            return capitalize_words(cleaned)
        """),
     "modified": d("""
        def normalize_name(name):
            cleaned = " ".join(name.split())
            return " ".join(part.capitalize() for part in cleaned.split(" "))
        """),
     "inputs": [("",), ("  ada   lovelace ",), ("ALAN turing",)],
     "random": lambda r: (" ".join(r.choice(["ann", " BOB", "cy  ", "Dee"]) for _ in range(r.randint(0, 4))),)},

    {"id": "TC15", "category": "structural", "transformation": "equivalent arithmetic expressions", "entry": "bill",
     "original": d("""
        def bill(quantity, unit_price, discount_percent):
            gross = quantity * unit_price
            discount = gross * discount_percent // 100
            return gross - discount
        """),
     "modified": d("""
        def bill(quantity, unit_price, discount_percent):
            gross = unit_price * quantity
            discount = (discount_percent * gross) // 100
            return -discount + gross
        """),
     "inputs": [(0, 5, 10), (3, 99, 0), (7, 13, 100)],
     "random": lambda r: (r.randint(0, 50), r.randint(0, 500), r.randint(0, 100))},

    {"id": "TC16", "category": "structural", "transformation": "add unused variables", "entry": "find_max",
     "original": d("""
        def find_max(values):
            best = values[0]
            for v in values[1:]:
                if v > best:
                    best = v
            return best
        """),
     "modified": d("""
        def find_max(values):
            best = values[0]
            checked = 0
            label = "maximum"
            for v in values[1:]:
                previous = best
                if v > best:
                    best = v
            return best
        """),
     "inputs": [([7],), ([1, 9, 3],), ([-5, -2, -9],)], "random": lambda r: ([r.randint(-99, 99) for _ in range(r.randint(1, 9))],)},

    {"id": "TC17", "category": "structural", "transformation": "add dead code", "entry": "find_max",
     "original": d("""
        def find_max(values):
            best = values[0]
            for v in values[1:]:
                if v > best:
                    best = v
            return best
        """),
     "modified": d("""
        def find_max(values):
            best = values[0]
            if False:
                best = None
                print("never runs")
            for v in values[1:]:
                if v > best:
                    best = v
                elif v > best + 1000000:
                    best = -1
            return best
            best = 0
            return best
        """),
     "inputs": [([7],), ([1, 9, 3],), ([-5, -2, -9],)], "random": lambda r: ([r.randint(-99, 99) for _ in range(r.randint(1, 9))],)},

    {"id": "TC18", "category": "structural", "transformation": "change control-flow structure (nested if -> guard clauses)",
     "entry": "shipping_cost",
     "original": d("""
        def shipping_cost(weight, express):
            if weight <= 0:
                cost = 0
            else:
                if express:
                    if weight > 10:
                        cost = 30
                    else:
                        cost = 20
                else:
                    if weight > 10:
                        cost = 15
                    else:
                        cost = 8
            return cost
        """),
     "modified": d("""
        def shipping_cost(weight, express):
            if weight <= 0:
                return 0
            heavy = weight > 10
            if express and heavy:
                return 30
            if express:
                return 20
            if heavy:
                return 15
            return 8
        """),
     "inputs": [(0, True), (10, False), (11, True), (11, False), (-3, False)],
     "random": lambda r: (r.randint(-5, 30), r.choice([True, False]))},

    # ------------------------------------------------------------------ equivalent
    {"id": "TC13", "category": "equivalent", "transformation": "recursion -> iteration", "entry": "fib",
     "original": d("""
        def fib(n):
            if n < 2:
                return n
            return fib(n - 1) + fib(n - 2)
        """),
     "modified": d("""
        def fib(n):
            if n < 2:
                return n
            previous, current = 0, 1
            for _ in range(n - 1):
                previous, current = current, previous + current
            return current
        """),
     "inputs": [(0,), (1,), (2,), (10,), (20,)], "random": lambda r: (r.randint(0, 18),)},

    {"id": "TC14", "category": "equivalent", "transformation": "iteration -> recursion", "entry": "power",
     "original": d("""
        def power(base, exp):
            result = 1
            for _ in range(exp):
                result *= base
            return result
        """),
     "modified": d("""
        def power(base, exp):
            if exp == 0:
                return 1
            return base * power(base, exp - 1)
        """),
     "inputs": [(2, 0), (2, 10), (-3, 3), (0, 5)], "random": lambda r: (r.randint(-9, 9), r.randint(0, 12))},

    {"id": "TC19", "category": "equivalent", "transformation": "different implementation details, same output (manual dict -> Counter)",
     "entry": "word_counts",
     "original": d("""
        def word_counts(text):
            counts = {}
            for word in text.lower().split():
                if word in counts:
                    counts[word] += 1
                else:
                    counts[word] = 1
            return sorted(counts.items())
        """),
     "modified": d("""
        from collections import Counter


        def word_counts(text):
            return sorted(Counter(text.lower().split()).items())
        """),
     "inputs": [("",), ("a A a b",), ("The cat and the hat",)],
     "random": lambda r: (" ".join(r.choice(WORDS) for _ in range(r.randint(0, 12))),)},

    {"id": "TC20", "category": "equivalent", "transformation": "fundamentally different algorithm (bubble sort -> merge sort)",
     "entry": "sort_numbers",
     "original": d("""
        def sort_numbers(values):
            items = list(values)
            n = len(items)
            for i in range(n):
                for j in range(n - i - 1):
                    if items[j] > items[j + 1]:
                        items[j], items[j + 1] = items[j + 1], items[j]
            return items
        """),
     "modified": d("""
        def sort_numbers(values):
            if len(values) <= 1:
                return list(values)
            middle = len(values) // 2
            left = sort_numbers(values[:middle])
            right = sort_numbers(values[middle:])
            merged = []
            i = j = 0
            while i < len(left) and j < len(right):
                if left[i] <= right[j]:
                    merged.append(left[i])
                    i += 1
                else:
                    merged.append(right[j])
                    j += 1
            return merged + left[i:] + right[j:]
        """),
     "inputs": [([],), ([1],), ([3, 1, 2],), ([5, 5, -1, 0],)], "random": lambda r: (_ints(r, n=12),)},
]

# Superficial references: same source, only layout/comments/names change.
SUPERFICIAL = [
    {"id": "REF-A1", "category": "superficial", "transformation": "identical copy", "entry": "average_valid",
     "original": PAIRS[6]["original"], "modified": PAIRS[6]["original"],
     "inputs": PAIRS[6]["inputs"], "random": PAIRS[6]["random"]},
    {"id": "REF-A2", "category": "superficial", "transformation": "comments added + formatting changed",
     "entry": "average_valid", "original": PAIRS[6]["original"],
     "modified": d("""
        # Average of the valid marks (0-100).
        def average_valid(scores):

            total=0
            count=0
            for s in scores:   # check every mark
                if 0<=s<=100:
                    total+=s
                    count+=1

            if count==0:
                return 0.0
            return total/count
        """),
     "inputs": PAIRS[6]["inputs"], "random": PAIRS[6]["random"]},
    {"id": "REF-A3", "category": "superficial", "transformation": "all local names renamed", "entry": "average_valid",
     "original": PAIRS[6]["original"],
     "modified": d("""
        def average_valid(marks):
            running = 0
            seen = 0
            for m in marks:
                if 0 <= m <= 100:
                    running += m
                    seen += 1
            if seen == 0:
                return 0.0
            return running / seen
        """),
     "inputs": PAIRS[6]["inputs"], "random": PAIRS[6]["random"]},
]

_by_id = {p["id"]: p for p in PAIRS}
# Unrelated controls: originals of different tasks paired together.
UNRELATED = [
    {"id": f"UNREL-{i + 1}", "category": "unrelated", "transformation": f"{a} vs {b} (different tasks)",
     "entry": None, "original": _by_id[a]["original"], "modified": _by_id[b]["original"]}
    for i, (a, b) in enumerate([("TC13", "TC06"), ("TC20", "TC19"), ("TC18", "TC14"), ("TC11", "TC10"),
                                ("TC01", "TC12"), ("TC02", "TC15"), ("TC09", "TC03"), ("TC08", "TC05")])
]


def all_cases() -> list[dict]:
    cases = SUPERFICIAL + sorted(PAIRS, key=lambda p: p["id"]) + UNRELATED
    for c in cases:
        if c.get("random"):
            c["random_inputs"] = _rand(c["random"])
    return cases
