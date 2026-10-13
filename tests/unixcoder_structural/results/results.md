# UniXcoder structural-transformation results (Python)

Model `microsoft/unixcoder-base-nine`. 31 pairs, 31 passed verification, 0 failed. Production = `normalize_code` -> encode -> `semantic_similarity` (what the app uses); raw = unprocessed source (informational).

Baselines: identical code = **1.000**; unrelated controls (different tasks) = production **0.385-0.637** (mean 0.516), raw 0.140-0.435. Semantic review threshold: 0.8.

Behaviour was verified by executing both programs on edge cases plus 200 seeded random inputs. Scores are similarity measurements, not plagiarism labels.

## Ranked by production score drop (structural and equivalent pairs)

| Rank | TC | Category | Transformation | Production | Drop from 1.0 | Position | Raw | Behaviour |
|---|---|---|---|---|---|---|---|---|
| 1 | TC14 | equivalent | iteration -> recursion | 0.642 | 0.358 | below review threshold | 0.872 | preserved |
| 2 | TC19 | equivalent | different implementation details, same output (manual dict -> Counter) | 0.776 | 0.224 | below review threshold | 0.762 | preserved |
| 3 | TC20 | equivalent | fundamentally different algorithm (bubble sort -> merge sort) | 0.789 | 0.211 | below review threshold | 0.671 | preserved |
| 4 | TC13 | equivalent | recursion -> iteration | 0.792 | 0.208 | below review threshold | 0.795 | preserved |
| 5 | TC07 | structural | extract part of a function into a helper | 0.820 | 0.180 | at/above review threshold | 0.939 | preserved |
| 6 | TC05 | structural | list comprehension -> explicit loop | 0.831 | 0.169 | at/above review threshold | 0.959 | preserved |
| 7 | TC06 | structural | explicit loop -> list comprehension | 0.853 | 0.147 | at/above review threshold | 0.947 | preserved |
| 8 | TC11 | structural | split one function into multiple functions | 0.877 | 0.123 | at/above review threshold | 0.862 | preserved |
| 9 | TC12 | structural | merge multiple functions into one | 0.881 | 0.119 | at/above review threshold | 0.852 | preserved |
| 10 | TC08 | structural | inline a helper function | 0.892 | 0.108 | at/above review threshold | 0.941 | preserved |
| 11 | TC17 | structural | add dead code | 0.893 | 0.107 | at/above review threshold | 0.760 | preserved |
| 12 | TC18 | structural | change control-flow structure (nested if -> guard clauses) | 0.938 | 0.062 | at/above review threshold | 0.864 | preserved |
| 13 | TC01 | structural | for loop -> while loop | 0.958 | 0.042 | at/above review threshold | 0.984 | preserved |
| 14 | TC10 | structural | reorder independent function definitions | 0.966 | 0.034 | at/above review threshold | 0.982 | preserved |
| 15 | TC15 | structural | equivalent arithmetic expressions | 0.969 | 0.031 | at/above review threshold | 0.989 | preserved |
| 16 | TC02 | structural | while loop -> for loop | 0.978 | 0.022 | at/above review threshold | 0.987 | preserved |
| 17 | TC04 | structural | conditional expression -> if/else statement | 0.987 | 0.013 | at/above review threshold | 0.984 | preserved |
| 18 | TC03 | structural | if/else statement -> conditional expression | 0.991 | 0.009 | at/above review threshold | 0.987 | preserved |
| 19 | TC09 | structural | reorder independent statements | 0.994 | 0.006 | at/above review threshold | 0.993 | preserved |
| 20 | TC16 | structural | add unused variables | 1.000 | 0.000 | at/above review threshold | 0.777 | preserved |

## By category (production)

| Category | Pairs | Min | Mean | Max |
|---|---|---|---|---|
| Same source, superficial changes | 3 | 0.976 | 0.992 | 1.000 |
| Similar implementation, structural changes | 16 | 0.820 | 0.927 | 1.000 |
| Functionally equivalent, different implementation | 4 | 0.642 | 0.750 | 0.792 |
| Unrelated code (control) | 8 | 0.385 | 0.516 | 0.637 |

## All pairs

| ID | Category | Transformation | Production | Raw | Erased by preprocessing | Verification | Status |
|---|---|---|---|---|---|---|---|
| REF-A1 | superficial | identical copy | 1.000 | 1.000 | yes | identical results on 203 inputs (3 edge cases + 200 random) | PASS |
| REF-A2 | superficial | comments added + formatting changed | 0.976 | 0.869 | no | identical results on 203 inputs (3 edge cases + 200 random) | PASS |
| REF-A3 | superficial | all local names renamed | 1.000 | 0.768 | yes | identical results on 203 inputs (3 edge cases + 200 random) | PASS |
| TC01 | structural | for loop -> while loop | 0.958 | 0.984 | no | identical results on 205 inputs (5 edge cases + 200 random) | PASS |
| TC02 | structural | while loop -> for loop | 0.978 | 0.987 | no | identical results on 204 inputs (4 edge cases + 200 random) | PASS |
| TC03 | structural | if/else statement -> conditional expression | 0.991 | 0.987 | no | identical results on 203 inputs (3 edge cases + 200 random) | PASS |
| TC04 | structural | conditional expression -> if/else statement | 0.987 | 0.984 | no | identical results on 203 inputs (3 edge cases + 200 random) | PASS |
| TC05 | structural | list comprehension -> explicit loop | 0.831 | 0.959 | no | identical results on 203 inputs (3 edge cases + 200 random) | PASS |
| TC06 | structural | explicit loop -> list comprehension | 0.853 | 0.947 | no | identical results on 203 inputs (3 edge cases + 200 random) | PASS |
| TC07 | structural | extract part of a function into a helper | 0.820 | 0.939 | no | identical results on 203 inputs (3 edge cases + 200 random) | PASS |
| TC08 | structural | inline a helper function | 0.892 | 0.941 | no | identical results on 203 inputs (3 edge cases + 200 random) | PASS |
| TC09 | structural | reorder independent statements | 0.994 | 0.993 | no | identical results on 203 inputs (3 edge cases + 200 random) | PASS |
| TC10 | structural | reorder independent function definitions | 0.966 | 0.982 | no | identical results on 202 inputs (2 edge cases + 200 random) | PASS |
| TC11 | structural | split one function into multiple functions | 0.877 | 0.862 | no | identical results on 203 inputs (3 edge cases + 200 random) | PASS |
| TC12 | structural | merge multiple functions into one | 0.881 | 0.852 | no | identical results on 203 inputs (3 edge cases + 200 random) | PASS |
| TC15 | structural | equivalent arithmetic expressions | 0.969 | 0.989 | no | identical results on 203 inputs (3 edge cases + 200 random) | PASS |
| TC16 | structural | add unused variables | 1.000 | 0.777 | yes | identical results on 203 inputs (3 edge cases + 200 random) | PASS |
| TC17 | structural | add dead code | 0.893 | 0.760 | no | identical results on 203 inputs (3 edge cases + 200 random) | PASS |
| TC18 | structural | change control-flow structure (nested if -> guard clauses) | 0.938 | 0.864 | no | identical results on 205 inputs (5 edge cases + 200 random) | PASS |
| TC13 | equivalent | recursion -> iteration | 0.792 | 0.795 | no | identical results on 205 inputs (5 edge cases + 200 random) | PASS |
| TC14 | equivalent | iteration -> recursion | 0.642 | 0.872 | no | identical results on 204 inputs (4 edge cases + 200 random) | PASS |
| TC19 | equivalent | different implementation details, same output (manual dict -> Counter) | 0.776 | 0.762 | no | identical results on 203 inputs (3 edge cases + 200 random) | PASS |
| TC20 | equivalent | fundamentally different algorithm (bubble sort -> merge sort) | 0.789 | 0.671 | no | identical results on 204 inputs (4 edge cases + 200 random) | PASS |
| UNREL-1 | unrelated | TC13 vs TC06 (different tasks) | 0.544 | 0.140 | no | different tasks; behaviour not comparable | PASS |
| UNREL-2 | unrelated | TC20 vs TC19 (different tasks) | 0.479 | 0.257 | no | different tasks; behaviour not comparable | PASS |
| UNREL-3 | unrelated | TC18 vs TC14 (different tasks) | 0.522 | 0.186 | no | different tasks; behaviour not comparable | PASS |
| UNREL-4 | unrelated | TC11 vs TC10 (different tasks) | 0.637 | 0.435 | no | different tasks; behaviour not comparable | PASS |
| UNREL-5 | unrelated | TC01 vs TC12 (different tasks) | 0.521 | 0.181 | no | different tasks; behaviour not comparable | PASS |
| UNREL-6 | unrelated | TC02 vs TC15 (different tasks) | 0.385 | 0.212 | no | different tasks; behaviour not comparable | PASS |
| UNREL-7 | unrelated | TC09 vs TC03 (different tasks) | 0.473 | 0.370 | no | different tasks; behaviour not comparable | PASS |
| UNREL-8 | unrelated | TC08 vs TC05 (different tasks) | 0.564 | 0.149 | no | different tasks; behaviour not comparable | PASS |

## Assumptions and limitations

- Python only: behaviour is verified by execution, and list comprehensions / conditional expressions are Python constructs. Earlier batches showed scores vary by language, so these numbers are not assumed to transfer to other languages.
- Equivalence is checked on representative and random inputs, not proven for all inputs.
- Programs are small (5-20 lines); in a larger submission one transformed function is diluted by the unchanged code around it, so whole-submission drops would usually be smaller.
- TC17's dead branches never execute on any input (the `elif` condition is implied false by the preceding `if`), so behaviour is unchanged by construction as well as by test.
