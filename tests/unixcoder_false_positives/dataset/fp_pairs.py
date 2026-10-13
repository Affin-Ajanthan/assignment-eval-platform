"""
Known-negative pairs for the UniXcoder false-positive batch.

Every pair is NOT a copy: the two programs were written separately, with
deliberately different approaches. ``why_similar`` records, BEFORE measuring,
why a similarity model might still rate the pair as close.

Caveat: all programs were authored for this test by one author (deliberately
varying style and approach). They stand in for independent student work but
are not a sample of real students.
"""

from __future__ import annotations

import textwrap


def d(src: str) -> str:
    return textwrap.dedent(src).strip("\n") + "\n"


STARTER = d('''
    # CS101 Assignment 3 - Library fines
    # DO NOT MODIFY read_input() or main(); implement calculate_fine().

    def read_input():
        n = int(input())
        records = []
        for _ in range(n):
            name, days = input().split()
            records.append((name, int(days)))
        return records


    def calculate_fine(days_late):
    {body}


    def main():
        records = read_input()
        for name, days in records:
            print(name, calculate_fine(days))


    if __name__ == "__main__":
        main()
    ''')


def starter(body: str) -> str:
    return STARTER.replace("{body}", textwrap.indent(textwrap.dedent(body).strip("\n"), "    "))


# Six independent calculate_fine() solutions for the starter-code cohort simulation.
STARTER_SOLUTIONS = {
    "tiers": """
        if days_late <= 0:
            return 0.0
        elif days_late <= 7:
            return days_late * 0.25
        elif days_late <= 30:
            return 1.75 + (days_late - 7) * 0.5
        return 20.0
        """,
    "formula": """
        return min(max(days_late, 0) * 0.5, 20.0)
        """,
    "loop": """
        fine = 0.0
        for day in range(1, days_late + 1):
            fine += 0.25 if day <= 7 else 0.5
        return min(fine, 20.0)
        """,
    "table": """
        rates = [(30, 1.0), (7, 0.5), (0, 0.25)]
        for limit, rate in rates:
            if days_late > limit:
                return round(days_late * rate, 2)
        return 0.0
        """,
    "flat": """
        if days_late > 0:
            return 2.0 + days_late // 7
        return 0
        """,
    "weeks": """
        weeks, extra = divmod(max(days_late, 0), 7)
        total = weeks * 1.5 + extra * 0.3
        return total if total < 25 else 25
        """,
}

PAIRS = [
    {"id": "TC01", "language": "Python", "relationship": "same task (maximum), different algorithm",
     "why_similar": "same task; both iterate over the same list and compare elements",
     "files": ("max_loop.py", "max_divide.py"),
     "a": d("""
        def largest(values):
            best = values[0]
            for v in values[1:]:
                if v > best:
                    best = v
            return best
        """),
     "b": d("""
        def largest(values):
            if len(values) == 1:
                return values[0]
            middle = len(values) // 2
            left = largest(values[:middle])
            right = largest(values[middle:])
            return left if left >= right else right
        """)},
    {"id": "TC02", "language": "Python", "relationship": "same task (maximum), manual vs standard library",
     "why_similar": "same function signature and purpose; very short",
     "files": ("max_manual.py", "max_builtin.py"),
     "a": d("""
        def largest(values):
            if not values:
                return None
            best = values[0]
            for v in values:
                if v > best:
                    best = v
            return best
        """),
     "b": d("""
        def largest(values):
            return max(values, default=None)
        """)},
    {"id": "TC03", "language": "Python", "relationship": "same task (average), different implementation",
     "why_similar": "same task; both accumulate a sum over a list",
     "files": ("avg_loop.py", "avg_running.py"),
     "a": d("""
        def average(numbers):
            total = 0
            count = 0
            for n in numbers:
                total += n
                count += 1
            return total / count if count else 0.0
        """),
     "b": d("""
        def average(numbers):
            mean = 0.0
            for index, value in enumerate(numbers, start=1):
                mean += (value - mean) / index
            return mean
        """)},
    {"id": "TC04", "language": "Python", "relationship": "same task (sorting), different algorithms",
     "why_similar": "same task and output; both are loop-heavy list manipulation",
     "files": ("insertion.py", "quick.py"),
     "a": d("""
        def sort_list(items):
            result = list(items)
            for i in range(1, len(result)):
                key = result[i]
                j = i - 1
                while j >= 0 and result[j] > key:
                    result[j + 1] = result[j]
                    j -= 1
                result[j + 1] = key
            return result
        """),
     "b": d("""
        def sort_list(items):
            if len(items) <= 1:
                return list(items)
            pivot = items[0]
            smaller = [x for x in items[1:] if x < pivot]
            larger = [x for x in items[1:] if x >= pivot]
            return sort_list(smaller) + [pivot] + sort_list(larger)
        """)},
    {"id": "TC05", "language": "Python", "relationship": "same task (search), linear vs binary",
     "why_similar": "same task; both loop and compare against a target",
     "files": ("linear.py", "binary.py"),
     "a": d("""
        def find_index(items, target):
            for position, item in enumerate(items):
                if item == target:
                    return position
            return -1
        """),
     "b": d("""
        def find_index(items, target):
            low, high = 0, len(items) - 1
            while low <= high:
                mid = (low + high) // 2
                if items[mid] == target:
                    return mid
                if items[mid] < target:
                    low = mid + 1
                else:
                    high = mid - 1
            return -1
        """)},
    {"id": "TC06", "language": "Python", "relationship": "same algorithm (binary search), written independently",
     "why_similar": "the binary-search algorithm has one canonical shape (low/high/mid loop)",
     "files": ("bsearch_closed.py", "bsearch_halfopen.py"),
     "a": d("""
        def binary_search(sorted_items, wanted):
            low, high = 0, len(sorted_items) - 1
            while low <= high:
                mid = (low + high) // 2
                if sorted_items[mid] < wanted:
                    low = mid + 1
                elif sorted_items[mid] > wanted:
                    high = mid - 1
                else:
                    return mid
            return -1
        """),
     "b": d("""
        def binary_search(data, key):
            left, right = 0, len(data)
            while left < right:
                centre = left + (right - left) // 2
                if data[centre] >= key:
                    right = centre
                else:
                    left = centre + 1
            if left < len(data) and data[left] == key:
                return left
            return -1
        """)},
    {"id": "TC07", "language": "Python", "relationship": "same string problem (palindrome), different approach",
     "why_similar": "same task; both normalise case and compare characters",
     "files": ("pal_pointers.py", "pal_reverse.py"),
     "a": d("""
        def is_palindrome(text):
            i, j = 0, len(text) - 1
            while i < j:
                if not text[i].isalnum():
                    i += 1
                elif not text[j].isalnum():
                    j -= 1
                elif text[i].lower() != text[j].lower():
                    return False
                else:
                    i += 1
                    j -= 1
            return True
        """),
     "b": d("""
        import re


        def is_palindrome(text):
            cleaned = re.sub(r"[^a-z0-9]", "", text.lower())
            return cleaned == cleaned[::-1]
        """)},
    {"id": "TC08", "language": "Python", "relationship": "same array problem (second largest), different approach",
     "why_similar": "same task; both track the largest values of a list",
     "files": ("second_pass.py", "second_sort.py"),
     "a": d("""
        def second_largest(values):
            first = second = None
            for v in values:
                if first is None or v > first:
                    first, second = v, first
                elif v != first and (second is None or v > second):
                    second = v
            return second
        """),
     "b": d("""
        def second_largest(values):
            distinct = sorted(set(values), reverse=True)
            return distinct[1] if len(distinct) > 1 else None
        """)},
    {"id": "TC09", "language": "Python", "relationship": "different tasks (FizzBuzz vs grade bands) using common loops/conditions",
     "why_similar": "both are a for loop over a range/list with an if/elif/else chain",
     "files": ("fizzbuzz.py", "grades.py"),
     "a": d("""
        def fizzbuzz(limit):
            lines = []
            for n in range(1, limit + 1):
                if n % 15 == 0:
                    lines.append("FizzBuzz")
                elif n % 3 == 0:
                    lines.append("Fizz")
                elif n % 5 == 0:
                    lines.append("Buzz")
                else:
                    lines.append(str(n))
            return lines
        """),
     "b": d("""
        def grade_bands(marks):
            bands = []
            for mark in marks:
                if mark >= 70:
                    bands.append("First")
                elif mark >= 60:
                    bands.append("Upper second")
                elif mark >= 40:
                    bands.append("Pass")
                else:
                    bands.append("Fail")
            return bands
        """)},
    {"id": "TC10", "language": "Python", "relationship": "different tasks sharing the same import block",
     "why_similar": "identical import statements at the top of both files",
     "files": ("config_tool.py", "geometry_tool.py"),
     "a": d("""
        import json
        import math
        import os
        import sys


        def load_settings(path):
            if not os.path.exists(path):
                return {}
            with open(path) as handle:
                settings = json.load(handle)
            settings.setdefault("debug", False)
            return settings
        """),
     "b": d("""
        import json
        import math
        import os
        import sys


        def circle_report(radius):
            area = math.pi * radius ** 2
            circumference = 2 * math.pi * radius
            return json.dumps({"area": round(area, 2), "circumference": round(circumference, 2)})
        """)},
    {"id": "TC11", "language": "Java", "relationship": "different tasks sharing class/main/Scanner boilerplate",
     "why_similar": "identical class declaration, main method and Scanner setup",
     "files": ("Main.java", "Main.java"),
     "a": d("""
        import java.util.Scanner;

        public class Main {
            public static void main(String[] args) {
                Scanner scanner = new Scanner(System.in);
                double celsius = scanner.nextDouble();
                double fahrenheit = celsius * 9 / 5 + 32;
                System.out.println("Fahrenheit: " + fahrenheit);
                scanner.close();
            }
        }
        """),
     "b": d("""
        import java.util.Scanner;

        public class Main {
            public static void main(String[] args) {
                Scanner scanner = new Scanner(System.in);
                int size = scanner.nextInt();
                for (int row = 1; row <= size; row++) {
                    StringBuilder line = new StringBuilder();
                    for (int col = 1; col <= size; col++) {
                        line.append(row * col).append(' ');
                    }
                    System.out.println(line.toString().trim());
                }
                scanner.close();
            }
        }
        """)},
    {"id": "TC12", "language": "Python", "relationship": "different tasks using the same standard-library modules",
     "why_similar": "both lean on collections.Counter/defaultdict and itertools",
     "files": ("anagrams.py", "bigrams.py"),
     "a": d("""
        from collections import Counter, defaultdict
        from itertools import chain


        def group_anagrams(words):
            groups = defaultdict(list)
            for word in words:
                groups["".join(sorted(word))].append(word)
            return [g for g in groups.values() if len(g) > 1]
        """),
     "b": d("""
        from collections import Counter, defaultdict
        from itertools import chain


        def top_bigrams(sentences, n):
            words = list(chain.from_iterable(s.lower().split() for s in sentences))
            pairs = Counter(zip(words, words[1:]))
            return pairs.most_common(n)
        """)},
    {"id": "TC13", "language": "Python", "relationship": "different tasks with the same exception-handling structure",
     "why_similar": "same try/with open/except FileNotFoundError/except ValueError skeleton",
     "files": ("sum_file.py", "grep_file.py"),
     "a": d("""
        def sum_numbers_in_file(path):
            try:
                with open(path) as handle:
                    return sum(float(line) for line in handle if line.strip())
            except FileNotFoundError:
                print("file not found:", path)
                return None
            except ValueError:
                print("file contains a non-number")
                return None
        """),
     "b": d("""
        def count_matching_lines(path, keyword):
            try:
                with open(path) as handle:
                    return sum(1 for line in handle if keyword.lower() in line.lower())
            except FileNotFoundError:
                print("file not found:", path)
                return 0
            except UnicodeDecodeError:
                print("file is not text")
                return 0
        """)},
    {"id": "TC14", "language": "Python", "relationship": "very short programs, same beginner exercise (even/odd), written separately",
     "why_similar": "tiny programs for a common exercise have very few possible shapes",
     "files": ("even_a.py", "even_b.py"),
     "a": d("""
        def is_even(number):
            return number % 2 == 0
        """),
     "b": d("""
        def is_even(n):
            if n % 2:
                return False
            return True
        """)},
    {"id": "TC15", "language": "Python", "relationship": "different tasks with the same variable names",
     "why_similar": "shares names like values/total/count/result (removed by normalisation)",
     "files": ("price_total.py", "temperature_stats.py"),
     "a": d("""
        def order_total(values):
            total = 0
            count = 0
            for item in values:
                total += item["price"] * item["qty"]
                count += item["qty"]
            result = {"total": total, "items": count}
            return result
        """),
     "b": d("""
        def temperature_range(values):
            total = max(values) - min(values)
            count = sum(1 for v in values if v < 0)
            result = {"range": total, "freezing_days": count}
            return result
        """)},
    {"id": "TC16", "language": "Python", "relationship": "different tasks with the same function name",
     "why_similar": "both define and call `process(data)` (names removed by normalisation)",
     "files": ("process_text.py", "process_numbers.py"),
     "a": d("""
        def process(data):
            words = data.split()
            return " ".join(w.capitalize() for w in words)


        print(process("hello student world"))
        """),
     "b": d("""
        def process(data):
            squares = [x * x for x in data if x > 0]
            return sum(squares) / len(squares) if squares else 0


        print(process([3, -1, 4]))
        """)},
    {"id": "TC17", "language": "Python", "relationship": "instructor starter code + independent student logic",
     "why_similar": "most of each file is the identical instructor-provided starter code",
     "files": ("student_a.py", "student_b.py"),
     "a": starter(STARTER_SOLUTIONS["tiers"]), "b": starter(STARTER_SOLUTIONS["formula"])},
    {"id": "TC18", "language": "JavaScript", "relationship": "different apps sharing Express framework boilerplate",
     "why_similar": "identical Express setup: require, app, middleware, listen",
     "files": ("server.js", "server.js"),
     "a": d("""
        const express = require('express');
        const app = express();
        app.use(express.json());

        const todos = [];

        app.get('/todos', (req, res) => {
          res.json(todos);
        });

        app.post('/todos', (req, res) => {
          const todo = { id: todos.length + 1, title: req.body.title, done: false };
          todos.push(todo);
          res.status(201).json(todo);
        });

        app.listen(3000, () => console.log('Listening on port 3000'));
        """),
     "b": d("""
        const express = require('express');
        const app = express();
        app.use(express.json());

        app.get('/convert/:celsius', (req, res) => {
          const celsius = Number(req.params.celsius);
          if (Number.isNaN(celsius)) {
            return res.status(400).json({ error: 'not a number' });
          }
          res.json({ celsius, fahrenheit: celsius * 9 / 5 + 32 });
        });

        app.listen(3000, () => console.log('Listening on port 3000'));
        """)},
    {"id": "TC19", "language": "Python", "relationship": "different logic under the same step-by-step comments",
     "why_similar": "identical comment outline (removed by normalisation)",
     "files": ("steps_a.py", "steps_b.py"),
     "a": d("""
        def analyse(scores):
            # Step 1: read and validate the data
            valid = [s for s in scores if 0 <= s <= 100]
            # Step 2: process the data
            valid.sort()
            middle = len(valid) // 2
            # Step 3: produce the output
            return valid[middle] if valid else None
        """),
     "b": d("""
        def analyse(scores):
            # Step 1: read and validate the data
            cleaned = {}
            for name, score in scores.items():
                cleaned[name.strip().title()] = int(score)
            # Step 2: process the data
            ranking = sorted(cleaned, key=cleaned.get, reverse=True)
            # Step 3: produce the output
            return ranking[:3]
        """)},
    {"id": "TC20", "language": "Python", "relationship": "same nested-loop structure, different functionality",
     "why_similar": "identical nested for-loop/if/counter skeleton",
     "files": ("pair_sums.py", "inversions.py"),
     "a": d("""
        def count_pairs_with_sum(values, target):
            count = 0
            for i in range(len(values)):
                for j in range(i + 1, len(values)):
                    if values[i] + values[j] == target:
                        count += 1
            return count
        """),
     "b": d("""
        def count_inversions(values):
            count = 0
            for i in range(len(values)):
                for j in range(i + 1, len(values)):
                    if values[i] > values[j]:
                        count += 1
            return count
        """)},
]
