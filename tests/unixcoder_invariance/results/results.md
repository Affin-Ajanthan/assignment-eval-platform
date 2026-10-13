# UniXcoder formatting/comment invariance results

Model `microsoft/unixcoder-base-nine`, production path (normalize_code -> encode -> semantic_similarity). Pairs: 90; passed 90, failed 0. Raw-mode scores are informational.

Full original/modified sources for every row are in `results.csv` / `results.json` (and `../dataset/cases.json`).

## Summary by transformation (difference = baseline - score)

| ID | Transformation | Production: normalised text identical | Production max drop | Raw max drop | Production result |
|---|---|---|---|---|---|
| TC01 | identical copy | 1/1 | 0.000000 | 0.000000 | 1/1 pass |
| TC02 | identical copy | 1/1 | 0.000000 | 0.000000 | 1/1 pass |
| TC03 | identical copy | 1/1 | 0.000000 | 0.000000 | 1/1 pass |
| TC04 | identical copy | 1/1 | 0.000000 | 0.000000 | 1/1 pass |
| TC05 | identical copy | 1/1 | 0.000000 | 0.000000 | 1/1 pass |
| TC06 | identical copy | 1/1 | 0.000000 | 0.000000 | 1/1 pass |
| TC07 | identical copy | 1/1 | 0.000000 | 0.000000 | 1/1 pass |
| TC08 | identical copy | 1/1 | 0.000000 | 0.000000 | 1/1 pass |
| TC09 | identical copy | 1/1 | 0.000000 | 0.000000 | 1/1 pass |
| TC10 | change indentation | 9/9 | 0.000000 | 0.003134 | 9/9 pass |
| TC11 | add blank lines | 9/9 | 0.000000 | 0.069202 | 9/9 pass |
| TC12 | change spaces around operators | 0/9 | 0.044910 | 0.048077 | 9/9 pass |
| TC13 | change spaces around commas and parentheses | 0/9 | 0.008051 | 0.005160 | 9/9 pass |
| TC14 | add comments to one submission | 9/9 | 0.000000 | 0.250768 | 9/9 pass |
| TC15 | change existing comments | 9/9 | 0.000000 | 0.094869 | 9/9 pass |
| TC16 | remove comments from one submission | 9/9 | 0.000000 | 0.062514 | 9/9 pass |
| TC17 | change line endings (LF -> CRLF) | 9/9 | 0.000000 | 0.025837 | 9/9 pass |
| TC18 | change the filename, identical source | 9/9 | 0.000000 | 0.000000 | 9/9 pass |

## All pairs

| ID | Language | Transformation | Mode | Preprocessed | Comments removed | Score | Baseline | Difference | Status | Outlier | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| TC01 | Python | identical copy (baseline) | production | yes | yes | 1.000000 | 1.000000 | +0.000000 | PASS |  |  |
| TC01 | Python | identical copy (baseline) | raw | no | no | 1.000000 | 1.000000 | +0.000000 | INFO |  |  |
| TC02 | Java | identical copy (baseline) | production | yes | yes | 1.000000 | 1.000000 | +0.000000 | PASS |  |  |
| TC02 | Java | identical copy (baseline) | raw | no | no | 1.000000 | 1.000000 | +0.000000 | INFO |  |  |
| TC03 | JavaScript | identical copy (baseline) | production | yes | yes | 1.000000 | 1.000000 | +0.000000 | PASS |  |  |
| TC03 | JavaScript | identical copy (baseline) | raw | no | no | 1.000000 | 1.000000 | +0.000000 | INFO |  |  |
| TC04 | C | identical copy (baseline) | production | yes | yes | 1.000000 | 1.000000 | +0.000000 | PASS |  |  |
| TC04 | C | identical copy (baseline) | raw | no | no | 1.000000 | 1.000000 | +0.000000 | INFO |  |  |
| TC05 | C++ | identical copy (baseline) | production | yes | yes | 1.000000 | 1.000000 | +0.000000 | PASS |  |  |
| TC05 | C++ | identical copy (baseline) | raw | no | no | 1.000000 | 1.000000 | +0.000000 | INFO |  |  |
| TC06 | C# | identical copy (baseline) | production | yes | yes | 1.000000 | 1.000000 | +0.000000 | PASS |  |  |
| TC06 | C# | identical copy (baseline) | raw | no | no | 1.000000 | 1.000000 | +0.000000 | INFO |  |  |
| TC07 | Go | identical copy (baseline) | production | yes | yes | 1.000000 | 1.000000 | +0.000000 | PASS |  |  |
| TC07 | Go | identical copy (baseline) | raw | no | no | 1.000000 | 1.000000 | +0.000000 | INFO |  |  |
| TC08 | PHP | identical copy (baseline) | production | yes | yes | 1.000000 | 1.000000 | +0.000000 | PASS |  |  |
| TC08 | PHP | identical copy (baseline) | raw | no | no | 1.000000 | 1.000000 | +0.000000 | INFO |  |  |
| TC09 | Ruby | identical copy (baseline) | production | yes | yes | 1.000000 | 1.000000 | +0.000000 | PASS |  |  |
| TC09 | Ruby | identical copy (baseline) | raw | no | no | 1.000000 | 1.000000 | +0.000000 | INFO |  |  |
| TC10 | C | change indentation | production | yes | yes | 1.000000 | 1.000000 | +0.000000 | PASS |  |  |
| TC10 | C | change indentation | raw | no | no | 0.998949 | 1.000000 | +0.001051 | INFO |  |  |
| TC10 | C# | change indentation | production | yes | yes | 1.000000 | 1.000000 | +0.000000 | PASS |  |  |
| TC10 | C# | change indentation | raw | no | no | 0.996866 | 1.000000 | +0.003134 | INFO |  |  |
| TC10 | C++ | change indentation | production | yes | yes | 1.000000 | 1.000000 | +0.000000 | PASS |  |  |
| TC10 | C++ | change indentation | raw | no | no | 0.998675 | 1.000000 | +0.001325 | INFO |  |  |
| TC10 | Go | change indentation | production | yes | yes | 1.000000 | 1.000000 | +0.000000 | PASS |  |  |
| TC10 | Go | change indentation | raw | no | no | 0.998304 | 1.000000 | +0.001696 | INFO |  |  |
| TC10 | Java | change indentation | production | yes | yes | 1.000000 | 1.000000 | +0.000000 | PASS |  |  |
| TC10 | Java | change indentation | raw | no | no | 0.998632 | 1.000000 | +0.001368 | INFO |  |  |
| TC10 | JavaScript | change indentation | production | yes | yes | 1.000000 | 1.000000 | +0.000000 | PASS |  |  |
| TC10 | JavaScript | change indentation | raw | no | no | 0.999350 | 1.000000 | +0.000650 | INFO |  |  |
| TC10 | PHP | change indentation | production | yes | yes | 1.000000 | 1.000000 | +0.000000 | PASS |  |  |
| TC10 | PHP | change indentation | raw | no | no | 0.999178 | 1.000000 | +0.000822 | INFO |  |  |
| TC10 | Python | change indentation | production | yes | yes | 1.000000 | 1.000000 | +0.000000 | PASS |  |  |
| TC10 | Python | change indentation | raw | no | no | 0.998511 | 1.000000 | +0.001488 | INFO |  |  |
| TC10 | Ruby | change indentation | production | yes | yes | 1.000000 | 1.000000 | +0.000000 | PASS |  |  |
| TC10 | Ruby | change indentation | raw | no | no | 0.999248 | 1.000000 | +0.000752 | INFO |  |  |
| TC11 | C | add blank lines | production | yes | yes | 1.000000 | 1.000000 | +0.000000 | PASS |  |  |
| TC11 | C | add blank lines | raw | no | no | 0.930798 | 1.000000 | +0.069202 | INFO |  |  |
| TC11 | C# | add blank lines | production | yes | yes | 1.000000 | 1.000000 | +0.000000 | PASS |  |  |
| TC11 | C# | add blank lines | raw | no | no | 0.991500 | 1.000000 | +0.008500 | INFO |  |  |
| TC11 | C++ | add blank lines | production | yes | yes | 1.000000 | 1.000000 | +0.000000 | PASS |  |  |
| TC11 | C++ | add blank lines | raw | no | no | 0.954126 | 1.000000 | +0.045874 | INFO |  |  |
| TC11 | Go | add blank lines | production | yes | yes | 1.000000 | 1.000000 | +0.000000 | PASS |  |  |
| TC11 | Go | add blank lines | raw | no | no | 0.948389 | 1.000000 | +0.051611 | INFO |  |  |
| TC11 | Java | add blank lines | production | yes | yes | 1.000000 | 1.000000 | +0.000000 | PASS |  |  |
| TC11 | Java | add blank lines | raw | no | no | 0.952099 | 1.000000 | +0.047901 | INFO |  |  |
| TC11 | JavaScript | add blank lines | production | yes | yes | 1.000000 | 1.000000 | +0.000000 | PASS |  |  |
| TC11 | JavaScript | add blank lines | raw | no | no | 0.946270 | 1.000000 | +0.053730 | INFO |  |  |
| TC11 | PHP | add blank lines | production | yes | yes | 1.000000 | 1.000000 | +0.000000 | PASS |  |  |
| TC11 | PHP | add blank lines | raw | no | no | 0.968945 | 1.000000 | +0.031055 | INFO |  |  |
| TC11 | Python | add blank lines | production | yes | yes | 1.000000 | 1.000000 | +0.000000 | PASS |  |  |
| TC11 | Python | add blank lines | raw | no | no | 0.991522 | 1.000000 | +0.008478 | INFO |  |  |
| TC11 | Ruby | add blank lines | production | yes | yes | 1.000000 | 1.000000 | +0.000000 | PASS |  |  |
| TC11 | Ruby | add blank lines | raw | no | no | 0.990532 | 1.000000 | +0.009468 | INFO |  |  |
| TC12 | C | change spaces around operators | production | yes | yes | 0.988184 | 1.000000 | +0.011815 | PASS |  |  |
| TC12 | C | change spaces around operators | raw | no | no | 0.951923 | 1.000000 | +0.048077 | INFO | **yes** |  |
| TC12 | C# | change spaces around operators | production | yes | yes | 0.988276 | 1.000000 | +0.011724 | PASS |  |  |
| TC12 | C# | change spaces around operators | raw | no | no | 0.985720 | 1.000000 | +0.014280 | INFO |  |  |
| TC12 | C++ | change spaces around operators | production | yes | yes | 0.991518 | 1.000000 | +0.008482 | PASS |  |  |
| TC12 | C++ | change spaces around operators | raw | no | no | 0.986811 | 1.000000 | +0.013189 | INFO |  |  |
| TC12 | Go | change spaces around operators | production | yes | yes | 0.955090 | 1.000000 | +0.044910 | PASS | **yes** |  |
| TC12 | Go | change spaces around operators | raw | no | no | 0.984748 | 1.000000 | +0.015252 | INFO |  |  |
| TC12 | Java | change spaces around operators | production | yes | yes | 0.986988 | 1.000000 | +0.013012 | PASS |  |  |
| TC12 | Java | change spaces around operators | raw | no | no | 0.960749 | 1.000000 | +0.039251 | INFO | **yes** |  |
| TC12 | JavaScript | change spaces around operators | production | yes | yes | 0.988695 | 1.000000 | +0.011305 | PASS |  |  |
| TC12 | JavaScript | change spaces around operators | raw | no | no | 0.986828 | 1.000000 | +0.013172 | INFO |  |  |
| TC12 | PHP | change spaces around operators | production | yes | yes | 0.958001 | 1.000000 | +0.041999 | PASS | **yes** |  |
| TC12 | PHP | change spaces around operators | raw | no | no | 0.983351 | 1.000000 | +0.016649 | INFO |  |  |
| TC12 | Python | change spaces around operators | production | yes | yes | 0.958077 | 1.000000 | +0.041923 | PASS | **yes** |  |
| TC12 | Python | change spaces around operators | raw | no | no | 0.967763 | 1.000000 | +0.032237 | INFO | **yes** |  |
| TC12 | Ruby | change spaces around operators | production | yes | yes | 0.972743 | 1.000000 | +0.027256 | PASS | **yes** |  |
| TC12 | Ruby | change spaces around operators | raw | no | no | 0.986354 | 1.000000 | +0.013646 | INFO |  |  |
| TC13 | C | change spaces around commas and parentheses | production | yes | yes | 0.996729 | 1.000000 | +0.003271 | PASS |  |  |
| TC13 | C | change spaces around commas and parentheses | raw | no | no | 0.994928 | 1.000000 | +0.005072 | INFO |  |  |
| TC13 | C# | change spaces around commas and parentheses | production | yes | yes | 0.991949 | 1.000000 | +0.008051 | PASS |  |  |
| TC13 | C# | change spaces around commas and parentheses | raw | no | no | 0.996225 | 1.000000 | +0.003775 | INFO |  |  |
| TC13 | C++ | change spaces around commas and parentheses | production | yes | yes | 0.996016 | 1.000000 | +0.003984 | PASS |  |  |
| TC13 | C++ | change spaces around commas and parentheses | raw | no | no | 0.994840 | 1.000000 | +0.005160 | INFO |  |  |
| TC13 | Go | change spaces around commas and parentheses | production | yes | yes | 0.998249 | 1.000000 | +0.001751 | PASS |  |  |
| TC13 | Go | change spaces around commas and parentheses | raw | no | no | 0.998699 | 1.000000 | +0.001301 | INFO |  |  |
| TC13 | Java | change spaces around commas and parentheses | production | yes | yes | 0.995713 | 1.000000 | +0.004287 | PASS |  |  |
| TC13 | Java | change spaces around commas and parentheses | raw | no | no | 0.997321 | 1.000000 | +0.002679 | INFO |  |  |
| TC13 | JavaScript | change spaces around commas and parentheses | production | yes | yes | 0.992702 | 1.000000 | +0.007298 | PASS |  |  |
| TC13 | JavaScript | change spaces around commas and parentheses | raw | no | no | 0.997861 | 1.000000 | +0.002139 | INFO |  |  |
| TC13 | PHP | change spaces around commas and parentheses | production | yes | yes | 0.992604 | 1.000000 | +0.007396 | PASS |  |  |
| TC13 | PHP | change spaces around commas and parentheses | raw | no | no | 0.995560 | 1.000000 | +0.004440 | INFO |  |  |
| TC13 | Python | change spaces around commas and parentheses | production | yes | yes | 0.997696 | 1.000000 | +0.002304 | PASS |  |  |
| TC13 | Python | change spaces around commas and parentheses | raw | no | no | 0.998085 | 1.000000 | +0.001915 | INFO |  |  |
| TC13 | Ruby | change spaces around commas and parentheses | production | yes | yes | 0.997388 | 1.000000 | +0.002612 | PASS |  |  |
| TC13 | Ruby | change spaces around commas and parentheses | raw | no | no | 0.999479 | 1.000000 | +0.000521 | INFO |  |  |
| TC14 | C | add comments to one submission | production | yes | yes | 1.000000 | 1.000000 | +0.000000 | PASS |  |  |
| TC14 | C | add comments to one submission | raw | no | no | 0.853952 | 1.000000 | +0.146048 | INFO |  |  |
| TC14 | C# | add comments to one submission | production | yes | yes | 1.000000 | 1.000000 | +0.000000 | PASS |  |  |
| TC14 | C# | add comments to one submission | raw | no | no | 0.793856 | 1.000000 | +0.206144 | INFO |  |  |
| TC14 | C++ | add comments to one submission | production | yes | yes | 1.000000 | 1.000000 | +0.000000 | PASS |  |  |
| TC14 | C++ | add comments to one submission | raw | no | no | 0.828235 | 1.000000 | +0.171764 | INFO |  |  |
| TC14 | Go | add comments to one submission | production | yes | yes | 1.000000 | 1.000000 | +0.000000 | PASS |  |  |
| TC14 | Go | add comments to one submission | raw | no | no | 0.858307 | 1.000000 | +0.141693 | INFO |  |  |
| TC14 | Java | add comments to one submission | production | yes | yes | 1.000000 | 1.000000 | +0.000000 | PASS |  |  |
| TC14 | Java | add comments to one submission | raw | no | no | 0.836062 | 1.000000 | +0.163938 | INFO |  |  |
| TC14 | JavaScript | add comments to one submission | production | yes | yes | 1.000000 | 1.000000 | +0.000000 | PASS |  |  |
| TC14 | JavaScript | add comments to one submission | raw | no | no | 0.790335 | 1.000000 | +0.209665 | INFO |  |  |
| TC14 | PHP | add comments to one submission | production | yes | yes | 1.000000 | 1.000000 | +0.000000 | PASS |  |  |
| TC14 | PHP | add comments to one submission | raw | no | no | 0.763174 | 1.000000 | +0.236826 | INFO |  |  |
| TC14 | Python | add comments to one submission | production | yes | yes | 1.000000 | 1.000000 | +0.000000 | PASS |  |  |
| TC14 | Python | add comments to one submission | raw | no | no | 0.749231 | 1.000000 | +0.250768 | INFO |  |  |
| TC14 | Ruby | add comments to one submission | production | yes | yes | 1.000000 | 1.000000 | +0.000000 | PASS |  |  |
| TC14 | Ruby | add comments to one submission | raw | no | no | 0.807813 | 1.000000 | +0.192187 | INFO |  |  |
| TC15 | C | change existing comments | production | yes | yes | 1.000000 | 1.000000 | +0.000000 | PASS |  |  |
| TC15 | C | change existing comments | raw | no | no | 0.918666 | 1.000000 | +0.081334 | INFO |  |  |
| TC15 | C# | change existing comments | production | yes | yes | 1.000000 | 1.000000 | +0.000000 | PASS |  |  |
| TC15 | C# | change existing comments | raw | no | no | 0.931606 | 1.000000 | +0.068394 | INFO |  |  |
| TC15 | C++ | change existing comments | production | yes | yes | 1.000000 | 1.000000 | +0.000000 | PASS |  |  |
| TC15 | C++ | change existing comments | raw | no | no | 0.921324 | 1.000000 | +0.078676 | INFO |  |  |
| TC15 | Go | change existing comments | production | yes | yes | 1.000000 | 1.000000 | +0.000000 | PASS |  |  |
| TC15 | Go | change existing comments | raw | no | no | 0.929350 | 1.000000 | +0.070650 | INFO |  |  |
| TC15 | Java | change existing comments | production | yes | yes | 1.000000 | 1.000000 | +0.000000 | PASS |  |  |
| TC15 | Java | change existing comments | raw | no | no | 0.929101 | 1.000000 | +0.070899 | INFO |  |  |
| TC15 | JavaScript | change existing comments | production | yes | yes | 1.000000 | 1.000000 | +0.000000 | PASS |  |  |
| TC15 | JavaScript | change existing comments | raw | no | no | 0.906316 | 1.000000 | +0.093684 | INFO |  |  |
| TC15 | PHP | change existing comments | production | yes | yes | 1.000000 | 1.000000 | +0.000000 | PASS |  |  |
| TC15 | PHP | change existing comments | raw | no | no | 0.917752 | 1.000000 | +0.082248 | INFO |  |  |
| TC15 | Python | change existing comments | production | yes | yes | 1.000000 | 1.000000 | +0.000000 | PASS |  |  |
| TC15 | Python | change existing comments | raw | no | no | 0.905131 | 1.000000 | +0.094869 | INFO |  |  |
| TC15 | Ruby | change existing comments | production | yes | yes | 1.000000 | 1.000000 | +0.000000 | PASS |  |  |
| TC15 | Ruby | change existing comments | raw | no | no | 0.907090 | 1.000000 | +0.092910 | INFO |  |  |
| TC16 | C | remove comments from one submission | production | yes | yes | 1.000000 | 1.000000 | +0.000000 | PASS |  |  |
| TC16 | C | remove comments from one submission | raw | no | no | 0.951885 | 1.000000 | +0.048115 | INFO |  |  |
| TC16 | C# | remove comments from one submission | production | yes | yes | 1.000000 | 1.000000 | +0.000000 | PASS |  |  |
| TC16 | C# | remove comments from one submission | raw | no | no | 0.937486 | 1.000000 | +0.062514 | INFO | **yes** |  |
| TC16 | C++ | remove comments from one submission | production | yes | yes | 1.000000 | 1.000000 | +0.000000 | PASS |  |  |
| TC16 | C++ | remove comments from one submission | raw | no | no | 0.951344 | 1.000000 | +0.048655 | INFO |  |  |
| TC16 | Go | remove comments from one submission | production | yes | yes | 1.000000 | 1.000000 | +0.000000 | PASS |  |  |
| TC16 | Go | remove comments from one submission | raw | no | no | 0.952827 | 1.000000 | +0.047173 | INFO |  |  |
| TC16 | Java | remove comments from one submission | production | yes | yes | 1.000000 | 1.000000 | +0.000000 | PASS |  |  |
| TC16 | Java | remove comments from one submission | raw | no | no | 0.957555 | 1.000000 | +0.042445 | INFO |  |  |
| TC16 | JavaScript | remove comments from one submission | production | yes | yes | 1.000000 | 1.000000 | +0.000000 | PASS |  |  |
| TC16 | JavaScript | remove comments from one submission | raw | no | no | 0.940803 | 1.000000 | +0.059197 | INFO | **yes** |  |
| TC16 | PHP | remove comments from one submission | production | yes | yes | 1.000000 | 1.000000 | +0.000000 | PASS |  |  |
| TC16 | PHP | remove comments from one submission | raw | no | no | 0.954885 | 1.000000 | +0.045115 | INFO |  |  |
| TC16 | Python | remove comments from one submission | production | yes | yes | 1.000000 | 1.000000 | +0.000000 | PASS |  |  |
| TC16 | Python | remove comments from one submission | raw | no | no | 0.951827 | 1.000000 | +0.048173 | INFO |  |  |
| TC16 | Ruby | remove comments from one submission | production | yes | yes | 1.000000 | 1.000000 | +0.000000 | PASS |  |  |
| TC16 | Ruby | remove comments from one submission | raw | no | no | 0.946998 | 1.000000 | +0.053002 | INFO |  |  |
| TC17 | C | change line endings (LF -> CRLF) | production | yes | yes | 1.000000 | 1.000000 | +0.000000 | PASS |  |  |
| TC17 | C | change line endings (LF -> CRLF) | raw | no | no | 0.974163 | 1.000000 | +0.025837 | INFO |  |  |
| TC17 | C# | change line endings (LF -> CRLF) | production | yes | yes | 1.000000 | 1.000000 | +0.000000 | PASS |  |  |
| TC17 | C# | change line endings (LF -> CRLF) | raw | no | no | 0.975631 | 1.000000 | +0.024369 | INFO |  |  |
| TC17 | C++ | change line endings (LF -> CRLF) | production | yes | yes | 1.000000 | 1.000000 | +0.000000 | PASS |  |  |
| TC17 | C++ | change line endings (LF -> CRLF) | raw | no | no | 0.987712 | 1.000000 | +0.012288 | INFO |  |  |
| TC17 | Go | change line endings (LF -> CRLF) | production | yes | yes | 1.000000 | 1.000000 | +0.000000 | PASS |  |  |
| TC17 | Go | change line endings (LF -> CRLF) | raw | no | no | 0.982610 | 1.000000 | +0.017390 | INFO |  |  |
| TC17 | Java | change line endings (LF -> CRLF) | production | yes | yes | 1.000000 | 1.000000 | +0.000000 | PASS |  |  |
| TC17 | Java | change line endings (LF -> CRLF) | raw | no | no | 0.985638 | 1.000000 | +0.014362 | INFO |  |  |
| TC17 | JavaScript | change line endings (LF -> CRLF) | production | yes | yes | 1.000000 | 1.000000 | +0.000000 | PASS |  |  |
| TC17 | JavaScript | change line endings (LF -> CRLF) | raw | no | no | 0.985233 | 1.000000 | +0.014767 | INFO |  |  |
| TC17 | PHP | change line endings (LF -> CRLF) | production | yes | yes | 1.000000 | 1.000000 | +0.000000 | PASS |  |  |
| TC17 | PHP | change line endings (LF -> CRLF) | raw | no | no | 0.994315 | 1.000000 | +0.005685 | INFO |  |  |
| TC17 | Python | change line endings (LF -> CRLF) | production | yes | yes | 1.000000 | 1.000000 | +0.000000 | PASS |  |  |
| TC17 | Python | change line endings (LF -> CRLF) | raw | no | no | 0.976631 | 1.000000 | +0.023369 | INFO |  |  |
| TC17 | Ruby | change line endings (LF -> CRLF) | production | yes | yes | 1.000000 | 1.000000 | +0.000000 | PASS |  |  |
| TC17 | Ruby | change line endings (LF -> CRLF) | raw | no | no | 0.995299 | 1.000000 | +0.004701 | INFO |  |  |
| TC18 | C | change the filename, identical source | production | yes | yes | 1.000000 | 1.000000 | +0.000000 | PASS |  |  |
| TC18 | C | change the filename, identical source | raw | no | no | 1.000000 | 1.000000 | +0.000000 | INFO |  |  |
| TC18 | C# | change the filename, identical source | production | yes | yes | 1.000000 | 1.000000 | +0.000000 | PASS |  |  |
| TC18 | C# | change the filename, identical source | raw | no | no | 1.000000 | 1.000000 | +0.000000 | INFO |  |  |
| TC18 | C++ | change the filename, identical source | production | yes | yes | 1.000000 | 1.000000 | +0.000000 | PASS |  |  |
| TC18 | C++ | change the filename, identical source | raw | no | no | 1.000000 | 1.000000 | +0.000000 | INFO |  |  |
| TC18 | Go | change the filename, identical source | production | yes | yes | 1.000000 | 1.000000 | +0.000000 | PASS |  |  |
| TC18 | Go | change the filename, identical source | raw | no | no | 1.000000 | 1.000000 | +0.000000 | INFO |  |  |
| TC18 | Java | change the filename, identical source | production | yes | yes | 1.000000 | 1.000000 | +0.000000 | PASS |  |  |
| TC18 | Java | change the filename, identical source | raw | no | no | 1.000000 | 1.000000 | +0.000000 | INFO |  |  |
| TC18 | JavaScript | change the filename, identical source | production | yes | yes | 1.000000 | 1.000000 | +0.000000 | PASS |  |  |
| TC18 | JavaScript | change the filename, identical source | raw | no | no | 1.000000 | 1.000000 | +0.000000 | INFO |  |  |
| TC18 | PHP | change the filename, identical source | production | yes | yes | 1.000000 | 1.000000 | +0.000000 | PASS |  |  |
| TC18 | PHP | change the filename, identical source | raw | no | no | 1.000000 | 1.000000 | +0.000000 | INFO |  |  |
| TC18 | Python | change the filename, identical source | production | yes | yes | 1.000000 | 1.000000 | +0.000000 | PASS |  |  |
| TC18 | Python | change the filename, identical source | raw | no | no | 1.000000 | 1.000000 | +0.000000 | INFO |  |  |
| TC18 | Ruby | change the filename, identical source | production | yes | yes | 1.000000 | 1.000000 | +0.000000 | PASS |  |  |
| TC18 | Ruby | change the filename, identical source | raw | no | no | 1.000000 | 1.000000 | +0.000000 | INFO |  |  |
