# UniXcoder false-positive results — EXPLORATORY

Model `microsoft/unixcoder-base-nine`, production path (`normalize_code` -> encode -> `semantic_similarity`). **20 known-negative pairs** (no pair is a copy). These thresholds were not calibrated on a representative dataset of real student work, and all programs were written by one author, so every rate below is exploratory, not conclusive. A high score is not evidence of plagiarism.

## False-positive rate by threshold (semantic score alone)

| Threshold | Flagged negatives | False-positive rate | 95% CI (Wilson) |
|---|---|---|---|
| 0.50 | 15/20 | 75% | 53%-89% |
| 0.60 | 13/20 | 65% | 43%-82% |
| 0.70 | 10/20 | 50% | 30%-70% |
| 0.75 | 7/20 | 35% | 18%-57% |
| 0.80 (production floor) | 6/20 | 30% | 15%-52% |
| 0.85 | 4/20 | 20% | 8%-42% |
| 0.90 | 2/20 | 10% | 3%-30% |
| 0.95 | 0/20 | 0% | 0%-16% |

Token check (Winnowing: Jaccard >= 0.60 or containment >= 0.75), which the app also runs: 2/20 flagged (10%, 95% CI 3%-30%).

Note: in production the semantic flag also requires the pair to be an outlier against the class's other pairs (cohort rule, >= 10 pairs); a single pair here can't be evaluated against a class, so the per-pair rates above are a worst case for the semantic signal. See the cohort simulation below.

## Highest-scoring negative pairs

| Rank | TC | Lang | Relationship | Production | Raw | Token J / C | Identical lines | Likely cause |
|---|---|---|---|---|---|---|---|---|
| 1 | TC06 | Python | same algorithm (binary search), written independently | **0.932** | 0.654 | 0.20 / 0.35 | 18% | the binary-search algorithm has one canonical shape (low/high/mid loop) |
| 2 | TC14 | Python | very short programs, same beginner exercise (even/odd), written separately | **0.922** | 0.895 | 0.00 / 0.00 | 0% | tiny programs for a common exercise have very few possible shapes |
| 3 | TC17 | Python | instructor starter code + independent student logic | **0.899** | 0.949 | 0.60 / 0.80 (**token flag**) | 94% | most of each file is the identical instructor-provided starter code |
| 4 | TC03 | Python | same task (average), different implementation | **0.851** | 0.757 | 0.11 / 0.20 | 20% | same task; both accumulate a sum over a list |
| 5 | TC04 | Python | same task (sorting), different algorithms | **0.831** | 0.524 | 0.00 / 0.00 | 14% | same task and output; both are loop-heavy list manipulation |
| 6 | TC20 | Python | same nested-loop structure, different functionality | **0.821** | 0.514 | 0.58 / 0.78 (**token flag**) | 71% | identical nested for-loop/if/counter skeleton |
| 7 | TC13 | Python | different tasks with the same exception-handling structure | **0.777** | 0.491 | 0.52 / 0.70 | 40% | same try/with open/except FileNotFoundError/except ValueError skeleton |
| 8 | TC11 | Java | different tasks sharing class/main/Scanner boilerplate | **0.739** | 0.355 | 0.28 / 0.52 | 70% | identical class declaration, main method and Scanner setup |
| 9 | TC02 | Python | same task (maximum), manual vs standard library | **0.709** | 0.761 | 0.00 / 0.00 | 50% | same function signature and purpose; very short |
| 10 | TC07 | Python | same string problem (palindrome), different approach | **0.705** | 0.725 | 0.03 / 0.09 | 25% | same task; both normalise case and compare characters |
| 11 | TC05 | Python | same task (search), linear vs binary | **0.688** | 0.610 | 0.06 / 0.22 | 40% | same task; both loop and compare against a target |
| 12 | TC01 | Python | same task (maximum), different algorithm | **0.661** | 0.669 | 0.00 / 0.00 | 17% | same task; both iterate over the same list and compare elements |
| 13 | TC12 | Python | different tasks using the same standard-library modules | **0.607** | 0.580 | 0.22 / 0.38 | 33% | both lean on collections.Counter/defaultdict and itertools |
| 14 | TC08 | Python | same array problem (second largest), different approach | **0.581** | 0.738 | 0.06 / 0.17 | 33% | same task; both track the largest values of a list |
| 15 | TC19 | Python | different logic under the same step-by-step comments | **0.572** | 0.633 | 0.12 / 0.29 | 50% | identical comment outline (removed by normalisation) |
| 16 | TC16 | Python | different tasks with the same function name | **0.456** | 0.314 | 0.06 / 0.14 | 25% | both define and call `process(data)` (names removed by normalisation) |
| 17 | TC15 | Python | different tasks with the same variable names | **0.440** | 0.427 | 0.12 / 0.21 | 20% | shares names like values/total/count/result (removed by normalisation) |
| 18 | TC10 | Python | different tasks sharing the same import block | **0.386** | 0.299 | 0.14 / 0.26 | 50% | identical import statements at the top of both files |
| 19 | TC18 | JavaScript | different apps sharing Express framework boilerplate | **0.339** | 0.281 | 0.31 / 0.47 | 46% | identical Express setup: require, app, middleware, listen |
| 20 | TC09 | Python | different tasks (FizzBuzz vs grade bands) using common loops/conditions | **0.273** | 0.236 | 0.32 / 0.53 | 8% | both are a for loop over a range/list with an if/elif/else chain |

## Starter-code cohort simulation (production decision rule)

6 students submit the same instructor starter code with independently written `calculate_fine()` bodies (15 pairs), run through `apply_semantic_signal` unchanged.

- Semantic scores: 0.857-0.941; cohort median 0.9022; effective review bar 0.9496 (the 0.80 floor raised by the cohort-outlier rule).
- Semantic-only review flags: **0/15**.
- Token (Winnowing) flags: **11/15**.
- Flagged pairs: formula-loop (high, semantic 0.941, J 0.65, C 0.86), flat-tiers (high, semantic 0.907, J 0.65, C 0.83), formula-weeks (high, semantic 0.885, J 0.64, C 0.83), flat-table (high, semantic 0.908, J 0.59, C 0.81), flat-weeks (high, semantic 0.857, J 0.63, C 0.81), flat-formula (high, semantic 0.879, J 0.65, C 0.80), formula-table (high, semantic 0.870, J 0.57, C 0.80), formula-tiers (high, semantic 0.899, J 0.60, C 0.80), flat-loop (high, semantic 0.868, J 0.57, C 0.78), loop-weeks (high, semantic 0.918, J 0.60, C 0.77), table-weeks (high, semantic 0.916, J 0.59, C 0.77).
