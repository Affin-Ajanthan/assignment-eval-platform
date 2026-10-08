"""Code samples shared by the semantic-similarity tests (and useful for
re-calibrating the thresholds in app/similarity/semantic.py by hand).

GRADES_* are one small "grade report" program in several disguises;
the DIFFERENT_* samples are unrelated programs."""

import textwrap

GRADES_ORIGINAL = textwrap.dedent('''
    def load_scores(path):
        """Read one 'name,score' pair per line."""
        scores = {}
        with open(path) as handle:
            for line in handle:
                name, score = line.strip().split(",")
                scores[name] = float(score)
        return scores


    def average(scores):
        total = 0
        for value in scores.values():
            total += value
        return total / len(scores)


    def letter_grade(score):
        if score >= 90:
            return "A"
        elif score >= 80:
            return "B"
        elif score >= 70:
            return "C"
        elif score >= 60:
            return "D"
        return "F"


    def report(path):
        scores = load_scores(path)
        mean = average(scores)
        for name in sorted(scores):
            print(name, scores[name], letter_grade(scores[name]))
        print("class average:", round(mean, 2))
''')

# Same program, every identifier renamed, comments changed.
GRADES_RENAMED = textwrap.dedent('''
    def read_marks(filename):
        # parse the marks file
        marks = {}
        with open(filename) as f:
            for row in f:
                student, mark = row.strip().split(",")
                marks[student] = float(mark)
        return marks


    def mean_of(marks):
        acc = 0
        for m in marks.values():
            acc += m
        return acc / len(marks)


    def to_letter(mark):
        if mark >= 90:
            return "A"
        elif mark >= 80:
            return "B"
        elif mark >= 70:
            return "C"
        elif mark >= 60:
            return "D"
        return "F"


    def print_report(filename):
        marks = read_marks(filename)
        avg = mean_of(marks)
        for student in sorted(marks):
            print(student, marks[student], to_letter(marks[student]))
        print("class average:", round(avg, 2))
''')

# Same logic, rewritten to defeat token matching: functions reordered,
# loops turned into builtins/comprehensions, if-chain turned into a
# table lookup, new names.
GRADES_RESTRUCTURED = textwrap.dedent('''
    GRADE_BANDS = [(90, "A"), (80, "B"), (70, "C"), (60, "D")]


    def grade_for(points):
        for cutoff, letter in GRADE_BANDS:
            if points >= cutoff:
                return letter
        return "F"


    def summarize(results_file):
        results = parse_results(results_file)
        class_mean = sum(results.values()) / len(results)
        for pupil in sorted(results):
            print(pupil, results[pupil], grade_for(results[pupil]))
        print("class average:", round(class_mean, 2))


    def parse_results(results_file):
        with open(results_file) as fh:
            pairs = [ln.strip().split(",") for ln in fh if ln.strip()]
        return {who: float(pts) for who, pts in pairs}
''')

# A different, independent program from the same course: a bank account.
DIFFERENT_BANK = textwrap.dedent('''
    class Account:
        def __init__(self, owner, balance=0.0):
            self.owner = owner
            self.balance = balance
            self.history = []

        def deposit(self, amount):
            if amount <= 0:
                raise ValueError("deposit must be positive")
            self.balance += amount
            self.history.append(("deposit", amount))

        def withdraw(self, amount):
            if amount > self.balance:
                raise ValueError("insufficient funds")
            self.balance -= amount
            self.history.append(("withdraw", amount))

        def statement(self):
            lines = [f"Statement for {self.owner}"]
            for kind, amount in self.history:
                lines.append(f"{kind:>10} {amount:10.2f}")
            lines.append(f"{'balance':>10} {self.balance:10.2f}")
            return "\\n".join(lines)
''')

# Another unrelated program: breadth-first search over a grid maze.
DIFFERENT_MAZE = textwrap.dedent('''
    from collections import deque


    def shortest_path(grid, start, goal):
        rows, cols = len(grid), len(grid[0])
        queue = deque([(start, 0)])
        seen = {start}
        while queue:
            (r, c), dist = queue.popleft()
            if (r, c) == goal:
                return dist
            for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nr, nc = r + dr, c + dc
                if 0 <= nr < rows and 0 <= nc < cols and grid[nr][nc] != "#" and (nr, nc) not in seen:
                    seen.add((nr, nc))
                    queue.append(((nr, nc), dist + 1))
        return -1
''')

GRADES_JAVA = textwrap.dedent('''
    import java.util.*;
    import java.nio.file.*;

    public class Grades {
        // Read one "name,score" pair per line.
        static Map<String, Double> loadScores(String path) throws Exception {
            Map<String, Double> scores = new TreeMap<>();
            for (String line : Files.readAllLines(Paths.get(path))) {
                String[] parts = line.trim().split(",");
                scores.put(parts[0], Double.parseDouble(parts[1]));
            }
            return scores;
        }

        static double average(Map<String, Double> scores) {
            double total = 0;
            for (double v : scores.values()) total += v;
            return total / scores.size();
        }

        static String letterGrade(double score) {
            if (score >= 90) return "A";
            else if (score >= 80) return "B";
            else if (score >= 70) return "C";
            else if (score >= 60) return "D";
            return "F";
        }

        public static void main(String[] args) throws Exception {
            Map<String, Double> scores = loadScores(args[0]);
            for (Map.Entry<String, Double> e : scores.entrySet())
                System.out.println(e.getKey() + " " + e.getValue() + " " + letterGrade(e.getValue()));
            System.out.println("class average: " + average(scores));
        }
    }
''')

DIFFERENT_JS = textwrap.dedent('''
    // Debounce: run fn only after `wait` ms without another call.
    function debounce(fn, wait) {
      let timer = null;
      return function (...args) {
        clearTimeout(timer);
        timer = setTimeout(() => fn.apply(this, args), wait);
      };
    }

    function throttle(fn, limit) {
      let waiting = false;
      return function (...args) {
        if (waiting) return;
        fn.apply(this, args);
        waiting = true;
        setTimeout(() => { waiting = false; }, limit);
      };
    }

    module.exports = { debounce, throttle };
''')

# Five solutions to the same grade-report task, written independently
# (no shared source): what an honest cohort looks like.
INDEPENDENT_SOLUTIONS = {
"h_csv": '''
import csv
import statistics

def main(filename):
    with open(filename, newline="") as f:
        rows = list(csv.reader(f))
    marks = [(r[0], int(r[1])) for r in rows]
    for student, mark in marks:
        if mark < 60:
            g = "F"
        elif mark < 70:
            g = "D"
        elif mark < 80:
            g = "C"
        elif mark < 90:
            g = "B"
        else:
            g = "A"
        print(f"{student}: {mark} ({g})")
    print("Average", statistics.mean(m for _, m in marks))
''',
"h_class": '''
class Gradebook:
    def __init__(self):
        self.entries = []

    def add(self, name, score):
        self.entries.append((name, score))

    @staticmethod
    def grade(score):
        return "ABCDF"[min(4, max(0, (99 - int(score)) // 10))] if score >= 60 else "F"

    def summary(self):
        total = sum(s for _, s in self.entries)
        out = []
        for name, score in self.entries:
            out.append(name + " -> " + self.grade(score))
        out.append("mean=" + str(total / len(self.entries)))
        return out


def run(path):
    book = Gradebook()
    for line in open(path):
        if "," in line:
            n, s = line.split(",")
            book.add(n, float(s))
    print("\\n".join(book.summary()))
''',
"h_procedural": '''
names = []
scores = []
f = open("scores.txt")
for line in f.readlines():
    parts = line.split(",")
    names.append(parts[0])
    scores.append(int(parts[1]))
f.close()

total = 0
i = 0
while i < len(names):
    s = scores[i]
    total = total + s
    if s >= 90: letter = "A"
    elif s >= 80: letter = "B"
    elif s >= 70: letter = "C"
    elif s >= 60: letter = "D"
    else: letter = "F"
    print(names[i], s, letter)
    i = i + 1
print("Average:", total / len(names))
''',
"h_dict": '''
import sys

BOUNDARIES = {"A": 90, "B": 80, "C": 70, "D": 60}

def classify(mark):
    for letter, minimum in BOUNDARIES.items():
        if mark >= minimum:
            return letter
    return "F"

def read(path):
    data = {}
    for raw in open(path).read().splitlines():
        if not raw:
            continue
        who, mark = raw.split(",")
        data[who.strip()] = float(mark)
    return data

if __name__ == "__main__":
    data = read(sys.argv[1])
    for who, mark in sorted(data.items(), key=lambda kv: -kv[1]):
        print(f"{who:<12}{mark:6.1f}  {classify(mark)}")
    print("Mean:", sum(data.values()) / len(data))
''',
"h_func": '''
from functools import reduce

def parse(line):
    name, value = line.rstrip("\\n").split(",")
    return name, float(value)

def letter(v):
    return next((g for g, lo in (("A", 90), ("B", 80), ("C", 70), ("D", 60)) if v >= lo), "F")

def grade_file(path):
    with open(path) as src:
        records = list(map(parse, filter(str.strip, src)))
    for name, value in records:
        print(name, value, letter(value))
    mean = reduce(lambda acc, r: acc + r[1], records, 0.0) / len(records)
    print("average", mean)
''',
}
INDEPENDENT_SOLUTIONS = {k: textwrap.dedent(v) for k, v in INDEPENDENT_SOLUTIONS.items()}
