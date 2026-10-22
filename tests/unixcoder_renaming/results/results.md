# UniXcoder identifier-renaming results

Model `microsoft/unixcoder-base-nine`. 134 renaming pairs + 9 unrelated controls, each scored in 3 modes (429/429 measurements valid); 1 case(s) not applicable: TC12 C (C has no N_FUNC, N_PARAM (e.g. no nested functions)).

Modes: **raw** = source as written; **cleaned** = comments stripped + whitespace collapsed, names kept (experimental); **production** = `normalize_code` (cleaned + identifiers anonymised), what the app embeds. Drop = identical-code score (1.0) - pair score. Scores are similarity measurements, not plagiarism verdicts.

## 1. Languages most affected by renaming (mean drop over TC01-TC15)

| Language | raw | cleaned | production | production: renames fully erased |
|---|---|---|---|---|
| Go | 0.1987 | 0.2947 | 0.0002 | 14/15 |
| C# | 0.1965 | 0.3145 | 0.0011 | 12/15 |
| Ruby | 0.1914 | 0.2842 | 0.0007 | 14/15 |
| JavaScript | 0.1901 | 0.3062 | 0.0008 | 14/15 |
| C | 0.1884 | 0.3458 | 0.0006 | 13/14 |
| Python | 0.1750 | 0.3175 | 0.0007 | 14/15 |
| Java | 0.1739 | 0.2503 | 0.0011 | 12/15 |
| PHP | 0.1731 | 0.3009 | 0.0019 | 14/15 |
| C++ | 0.1710 | 0.2840 | 0.0004 | 14/15 |

## 2. Transformations by score reduction

| TC | Transformation | raw mean / max drop | cleaned mean / max | production mean / max | production: renames fully erased |
|---|---|---|---|---|---|
| TC08 | identifiers -> unrelated but valid names | 0.5040 / 0.5766 | 0.7256 / 0.7629 | 0.0000 / 0.0000 | 9/9 |
| TC06 | short identifiers -> descriptive names | 0.4471 / 0.5217 | 0.6510 / 0.7255 | 0.0014 / 0.0068 | 7/9 |
| TC11 | rename all identifiers + modify comments | 0.3200 / 0.3621 | 0.4527 / 0.4842 | -0.0000 / 0.0000 | 9/9 |
| TC07 | descriptive identifiers -> short names | 0.2766 / 0.3945 | 0.4839 / 0.5534 | 0.0014 / 0.0068 | 7/9 |
| TC10 | rename all identifiers + change formatting | 0.2674 / 0.2930 | 0.4570 / 0.4881 | 0.0094 / 0.0278 | 0/9 |
| TC15 | rename identifiers across the several functions | 0.1733 / 0.2443 | 0.3322 / 0.4043 | 0.0000 / 0.0000 | 9/9 |
| TC14 | rename identifiers in the object-oriented part | 0.1502 / 0.2573 | 0.2421 / 0.3179 | 0.0000 / 0.0000 | 9/9 |
| TC05 | rename functions and variables together | 0.1497 / 0.2007 | 0.2957 / 0.3701 | -0.0000 / 0.0000 | 9/9 |
| TC04 | rename local variables and parameters together | 0.1305 / 0.1641 | 0.2167 / 0.2649 | 0.0000 / 0.0000 | 9/9 |
| TC01 | rename local variables | 0.1060 / 0.1720 | 0.1766 / 0.2155 | 0.0000 / 0.0000 | 9/9 |
| TC02 | rename function parameters | 0.0607 / 0.0933 | 0.0715 / 0.1162 | 0.0000 / 0.0000 | 9/9 |
| TC03 | rename function names | 0.0548 / 0.1228 | 0.1387 / 0.2556 | 0.0000 / 0.0000 | 9/9 |
| TC13 | rename loop and conditional variables | 0.0454 / 0.0634 | 0.0704 / 0.0896 | 0.0000 / 0.0000 | 9/9 |
| TC09 | rename class and method names | 0.0428 / 0.0631 | 0.1027 / 0.2037 | 0.0000 / 0.0000 | 9/9 |
| TC12 | rename identifiers in the nested function | 0.0162 / 0.0264 | 0.0469 / 0.0662 | -0.0000 / 0.0000 | 8/8 |

## 3. Does identifier normalisation improve renamed-pair scores?

Comparing **production** with **cleaned** (same comment/whitespace handling, only identifier normalisation differs): smaller drop in 134 pairs, larger in 0, unchanged in 0. Mean drop: raw 0.1842, cleaned 0.2995, production 0.0008.

## 4. Does normalisation make unrelated code look more similar?

Each language's inventory program vs its unrelated averaging program.

| Language | raw | cleaned | production | production - raw | production - cleaned | >= review threshold (0.8)? |
|---|---|---|---|---|---|---|
| Python | 0.3340 | 0.1032 | 0.3703 | +0.0364 | +0.2671 | no |
| Java | 0.3086 | 0.1725 | 0.3446 | +0.0360 | +0.1721 | no |
| JavaScript | 0.3070 | 0.1561 | 0.3789 | +0.0719 | +0.2228 | no |
| C | 0.3039 | 0.1049 | 0.4500 | +0.1461 | +0.3451 | no |
| C++ | 0.3202 | 0.2199 | 0.3631 | +0.0429 | +0.1432 | no |
| C# | 0.3299 | 0.1127 | 0.3131 | -0.0168 | +0.2005 | no |
| Go | 0.2075 | 0.0978 | 0.4598 | +0.2524 | +0.3621 | no |
| PHP | 0.3160 | 0.1482 | 0.5448 | +0.2287 | +0.3966 | no |
| Ruby | 0.2789 | 0.1143 | 0.4234 | +0.1445 | +0.3091 | no |

Normalisation raised the unrelated-pair score (vs cleaned) in 9/9 languages: Python, Java, JavaScript, C, C++, C#, Go, PHP, Ruby.

## All pairs

| TC | Language | Transformation | raw | cleaned | production | production drop | renames erased by normalisation | Note |
|---|---|---|---|---|---|---|---|---|
| TC01 | C | rename local variables | 0.9096 | 0.7845 | 1.0000 | 0.0000 | yes |  |
| TC01 | C# | rename local variables | 0.9187 | 0.8405 | 1.0000 | 0.0000 | yes |  |
| TC01 | C++ | rename local variables | 0.8926 | 0.8229 | 1.0000 | 0.0000 | yes |  |
| TC01 | Go | rename local variables | 0.9034 | 0.8047 | 1.0000 | 0.0000 | yes |  |
| TC01 | Java | rename local variables | 0.9032 | 0.8531 | 1.0000 | 0.0000 | yes |  |
| TC01 | JavaScript | rename local variables | 0.8513 | 0.8239 | 1.0000 | 0.0000 | yes |  |
| TC01 | PHP | rename local variables | 0.9118 | 0.8174 | 1.0000 | 0.0000 | yes |  |
| TC01 | Python | rename local variables | 0.9276 | 0.8001 | 1.0000 | 0.0000 | yes |  |
| TC01 | Ruby | rename local variables | 0.8280 | 0.8637 | 1.0000 | 0.0000 | yes |  |
| TC02 | C | rename function parameters | 0.9398 | 0.8838 | 1.0000 | 0.0000 | yes |  |
| TC02 | C# | rename function parameters | 0.9319 | 0.9143 | 1.0000 | 0.0000 | yes |  |
| TC02 | C++ | rename function parameters | 0.9660 | 0.9528 | 1.0000 | 0.0000 | yes |  |
| TC02 | Go | rename function parameters | 0.9107 | 0.8979 | 1.0000 | 0.0000 | yes |  |
| TC02 | Java | rename function parameters | 0.9409 | 0.9363 | 1.0000 | 0.0000 | yes |  |
| TC02 | JavaScript | rename function parameters | 0.9390 | 0.9415 | 1.0000 | 0.0000 | yes |  |
| TC02 | PHP | rename function parameters | 0.9740 | 0.9401 | 1.0000 | 0.0000 | yes |  |
| TC02 | Python | rename function parameters | 0.9450 | 0.9316 | 1.0000 | 0.0000 | yes |  |
| TC02 | Ruby | rename function parameters | 0.9067 | 0.9578 | 1.0000 | 0.0000 | yes |  |
| TC03 | C | rename function names | 0.9586 | 0.8020 | 1.0000 | 0.0000 | yes |  |
| TC03 | C# | rename function names | 0.8772 | 0.7444 | 1.0000 | 0.0000 | yes |  |
| TC03 | C++ | rename function names | 0.9502 | 0.8618 | 1.0000 | 0.0000 | yes |  |
| TC03 | Go | rename function names | 0.9424 | 0.8680 | 1.0000 | 0.0000 | yes |  |
| TC03 | Java | rename function names | 0.9269 | 0.8742 | 1.0000 | 0.0000 | yes |  |
| TC03 | JavaScript | rename function names | 0.9681 | 0.8944 | 1.0000 | 0.0000 | yes |  |
| TC03 | PHP | rename function names | 0.9735 | 0.8948 | 1.0000 | 0.0000 | yes |  |
| TC03 | Python | rename function names | 0.9718 | 0.9068 | 1.0000 | 0.0000 | yes |  |
| TC03 | Ruby | rename function names | 0.9380 | 0.9051 | 1.0000 | 0.0000 | yes |  |
| TC04 | C | rename local variables and parameters together | 0.8860 | 0.7351 | 1.0000 | 0.0000 | yes |  |
| TC04 | C# | rename local variables and parameters together | 0.8705 | 0.7783 | 1.0000 | 0.0000 | yes |  |
| TC04 | C++ | rename local variables and parameters together | 0.8652 | 0.7986 | 1.0000 | 0.0000 | yes |  |
| TC04 | Go | rename local variables and parameters together | 0.8359 | 0.7590 | 1.0000 | 0.0000 | yes |  |
| TC04 | Java | rename local variables and parameters together | 0.8647 | 0.8017 | 1.0000 | 0.0000 | yes |  |
| TC04 | JavaScript | rename local variables and parameters together | 0.8458 | 0.7922 | 1.0000 | 0.0000 | yes |  |
| TC04 | PHP | rename local variables and parameters together | 0.8820 | 0.7801 | 1.0000 | 0.0000 | yes |  |
| TC04 | Python | rename local variables and parameters together | 0.8845 | 0.7667 | 1.0000 | 0.0000 | yes |  |
| TC04 | Ruby | rename local variables and parameters together | 0.8910 | 0.8380 | 1.0000 | 0.0000 | yes |  |
| TC05 | C | rename functions and variables together | 0.8444 | 0.6299 | 1.0000 | 0.0000 | yes |  |
| TC05 | C# | rename functions and variables together | 0.7993 | 0.6336 | 1.0000 | -0.0000 | yes |  |
| TC05 | C++ | rename functions and variables together | 0.8481 | 0.7115 | 1.0000 | 0.0000 | yes |  |
| TC05 | Go | rename functions and variables together | 0.8201 | 0.7006 | 1.0000 | 0.0000 | yes |  |
| TC05 | Java | rename functions and variables together | 0.8456 | 0.7490 | 1.0000 | 0.0000 | yes |  |
| TC05 | JavaScript | rename functions and variables together | 0.8517 | 0.7067 | 1.0000 | 0.0000 | yes |  |
| TC05 | PHP | rename functions and variables together | 0.8694 | 0.7196 | 1.0000 | 0.0000 | yes |  |
| TC05 | Python | rename functions and variables together | 0.8806 | 0.7117 | 1.0000 | 0.0000 | yes |  |
| TC05 | Ruby | rename functions and variables together | 0.8936 | 0.7765 | 1.0000 | 0.0000 | yes |  |
| TC06 | C | short identifiers -> descriptive names | 0.4783 | 0.2745 | 1.0000 | 0.0000 | yes |  |
| TC06 | C# | short identifiers -> descriptive names | 0.5411 | 0.3647 | 0.9939 | 0.0061 | no |  |
| TC06 | C++ | short identifiers -> descriptive names | 0.5859 | 0.3844 | 1.0000 | 0.0000 | yes |  |
| TC06 | Go | short identifiers -> descriptive names | 0.5418 | 0.4197 | 1.0000 | 0.0000 | yes |  |
| TC06 | Java | short identifiers -> descriptive names | 0.5845 | 0.4621 | 0.9932 | 0.0068 | no |  |
| TC06 | JavaScript | short identifiers -> descriptive names | 0.5798 | 0.3073 | 1.0000 | 0.0000 | yes |  |
| TC06 | PHP | short identifiers -> descriptive names | 0.5609 | 0.3605 | 1.0000 | 0.0000 | yes |  |
| TC06 | Python | short identifiers -> descriptive names | 0.5401 | 0.2918 | 1.0000 | 0.0000 | yes |  |
| TC06 | Ruby | short identifiers -> descriptive names | 0.5641 | 0.2756 | 1.0000 | 0.0000 | yes |  |
| TC07 | C | descriptive identifiers -> short names | 0.7635 | 0.5382 | 1.0000 | 0.0000 | yes |  |
| TC07 | C# | descriptive identifiers -> short names | 0.7372 | 0.5088 | 0.9939 | 0.0061 | no |  |
| TC07 | C++ | descriptive identifiers -> short names | 0.7706 | 0.5484 | 1.0000 | 0.0000 | yes |  |
| TC07 | Go | descriptive identifiers -> short names | 0.7431 | 0.5934 | 1.0000 | 0.0000 | yes |  |
| TC07 | Java | descriptive identifiers -> short names | 0.7850 | 0.6380 | 0.9932 | 0.0068 | no |  |
| TC07 | JavaScript | descriptive identifiers -> short names | 0.7098 | 0.4623 | 1.0000 | 0.0000 | yes |  |
| TC07 | PHP | descriptive identifiers -> short names | 0.7114 | 0.4552 | 1.0000 | 0.0000 | yes |  |
| TC07 | Python | descriptive identifiers -> short names | 0.6848 | 0.4542 | 1.0000 | 0.0000 | yes |  |
| TC07 | Ruby | descriptive identifiers -> short names | 0.6055 | 0.4466 | 1.0000 | 0.0000 | yes |  |
| TC08 | C | identifiers -> unrelated but valid names | 0.5055 | 0.2625 | 1.0000 | 0.0000 | yes |  |
| TC08 | C# | identifiers -> unrelated but valid names | 0.5083 | 0.2818 | 1.0000 | 0.0000 | yes |  |
| TC08 | C++ | identifiers -> unrelated but valid names | 0.5325 | 0.2951 | 1.0000 | 0.0000 | yes |  |
| TC08 | Go | identifiers -> unrelated but valid names | 0.4419 | 0.2600 | 1.0000 | 0.0000 | yes |  |
| TC08 | Java | identifiers -> unrelated but valid names | 0.5290 | 0.3534 | 1.0000 | 0.0000 | yes |  |
| TC08 | JavaScript | identifiers -> unrelated but valid names | 0.4630 | 0.2371 | 1.0000 | 0.0000 | yes |  |
| TC08 | PHP | identifiers -> unrelated but valid names | 0.4234 | 0.2489 | 1.0000 | 0.0000 | yes |  |
| TC08 | Python | identifiers -> unrelated but valid names | 0.5102 | 0.2408 | 1.0000 | 0.0000 | yes |  |
| TC08 | Ruby | identifiers -> unrelated but valid names | 0.5499 | 0.2896 | 1.0000 | 0.0000 | yes |  |
| TC09 | C | rename class and method names | 0.9381 | 0.8794 | 1.0000 | 0.0000 | yes | C has no classes: struct + functions taking it |
| TC09 | C# | rename class and method names | 0.9576 | 0.9259 | 1.0000 | 0.0000 | yes |  |
| TC09 | C++ | rename class and method names | 0.9616 | 0.9270 | 1.0000 | 0.0000 | yes |  |
| TC09 | Go | rename class and method names | 0.9606 | 0.9282 | 1.0000 | 0.0000 | yes |  |
| TC09 | Java | rename class and method names | 0.9748 | 0.9439 | 1.0000 | 0.0000 | yes |  |
| TC09 | JavaScript | rename class and method names | 0.9609 | 0.8805 | 1.0000 | 0.0000 | yes |  |
| TC09 | PHP | rename class and method names | 0.9753 | 0.9171 | 1.0000 | 0.0000 | yes |  |
| TC09 | Python | rename class and method names | 0.9492 | 0.7963 | 1.0000 | 0.0000 | yes |  |
| TC09 | Ruby | rename class and method names | 0.9369 | 0.8775 | 1.0000 | 0.0000 | yes |  |
| TC10 | C | rename all identifiers + change formatting | 0.7698 | 0.5389 | 0.9917 | 0.0083 | no |  |
| TC10 | C# | rename all identifiers + change formatting | 0.7117 | 0.5119 | 0.9958 | 0.0042 | no |  |
| TC10 | C++ | rename all identifiers + change formatting | 0.7437 | 0.5476 | 0.9940 | 0.0060 | no |  |
| TC10 | Go | rename all identifiers + change formatting | 0.7120 | 0.5494 | 0.9964 | 0.0036 | no |  |
| TC10 | Java | rename all identifiers + change formatting | 0.7481 | 0.6071 | 0.9973 | 0.0027 | no |  |
| TC10 | JavaScript | rename all identifiers + change formatting | 0.7070 | 0.5281 | 0.9879 | 0.0121 | no |  |
| TC10 | PHP | rename all identifiers + change formatting | 0.7300 | 0.5198 | 0.9722 | 0.0278 | no |  |
| TC10 | Python | rename all identifiers + change formatting | 0.7503 | 0.5310 | 0.9901 | 0.0099 | no |  |
| TC10 | Ruby | rename all identifiers + change formatting | 0.7204 | 0.5528 | 0.9897 | 0.0103 | no |  |
| TC11 | C | rename all identifiers + modify comments | 0.7165 | 0.5352 | 1.0000 | 0.0000 | yes |  |
| TC11 | C# | rename all identifiers + modify comments | 0.6379 | 0.5158 | 1.0000 | -0.0000 | yes |  |
| TC11 | C++ | rename all identifiers + modify comments | 0.6808 | 0.5569 | 1.0000 | 0.0000 | yes |  |
| TC11 | Go | rename all identifiers + modify comments | 0.6640 | 0.5479 | 1.0000 | 0.0000 | yes |  |
| TC11 | Java | rename all identifiers + modify comments | 0.6577 | 0.6164 | 1.0000 | 0.0000 | yes |  |
| TC11 | JavaScript | rename all identifiers + modify comments | 0.6658 | 0.5375 | 1.0000 | 0.0000 | yes |  |
| TC11 | PHP | rename all identifiers + modify comments | 0.7256 | 0.5327 | 1.0000 | 0.0000 | yes |  |
| TC11 | Python | rename all identifiers + modify comments | 0.6657 | 0.5270 | 1.0000 | 0.0000 | yes |  |
| TC11 | Ruby | rename all identifiers + modify comments | 0.7063 | 0.5561 | 1.0000 | 0.0000 | yes |  |
| TC12 | C# | rename identifiers in the nested function | 0.9736 | 0.9406 | 1.0000 | -0.0000 | yes |  |
| TC12 | C++ | rename identifiers in the nested function | 0.9831 | 0.9524 | 1.0000 | 0.0000 | yes |  |
| TC12 | Go | rename identifiers in the nested function | 0.9832 | 0.9338 | 1.0000 | 0.0000 | yes |  |
| TC12 | Java | rename identifiers in the nested function | 0.9792 | 0.9449 | 1.0000 | 0.0000 | yes |  |
| TC12 | JavaScript | rename identifiers in the nested function | 0.9855 | 0.9710 | 1.0000 | 0.0000 | yes |  |
| TC12 | PHP | rename identifiers in the nested function | 0.9812 | 0.9460 | 1.0000 | 0.0000 | yes |  |
| TC12 | Python | rename identifiers in the nested function | 0.9925 | 0.9701 | 1.0000 | 0.0000 | yes |  |
| TC12 | Ruby | rename identifiers in the nested function | 0.9920 | 0.9663 | 1.0000 | 0.0000 | yes |  |
| TC13 | C | rename loop and conditional variables | 0.9366 | 0.9276 | 1.0000 | 0.0000 | yes |  |
| TC13 | C# | rename loop and conditional variables | 0.9499 | 0.9328 | 1.0000 | 0.0000 | yes |  |
| TC13 | C++ | rename loop and conditional variables | 0.9521 | 0.9168 | 1.0000 | 0.0000 | yes |  |
| TC13 | Go | rename loop and conditional variables | 0.9469 | 0.9104 | 1.0000 | 0.0000 | yes |  |
| TC13 | Java | rename loop and conditional variables | 0.9525 | 0.9397 | 1.0000 | 0.0000 | yes |  |
| TC13 | JavaScript | rename loop and conditional variables | 0.9577 | 0.9225 | 1.0000 | 0.0000 | yes |  |
| TC13 | PHP | rename loop and conditional variables | 0.9654 | 0.9396 | 1.0000 | 0.0000 | yes |  |
| TC13 | Python | rename loop and conditional variables | 0.9552 | 0.9228 | 1.0000 | 0.0000 | yes |  |
| TC13 | Ruby | rename loop and conditional variables | 0.9754 | 0.9541 | 1.0000 | 0.0000 | yes |  |
| TC14 | C | rename identifiers in the object-oriented part | 0.8778 | 0.7389 | 1.0000 | 0.0000 | yes | C has no classes: struct + functions taking it |
| TC14 | C# | rename identifiers in the object-oriented part | 0.8815 | 0.7942 | 1.0000 | 0.0000 | yes |  |
| TC14 | C++ | rename identifiers in the object-oriented part | 0.8841 | 0.8151 | 1.0000 | 0.0000 | yes |  |
| TC14 | Go | rename identifiers in the object-oriented part | 0.8249 | 0.7681 | 1.0000 | 0.0000 | yes |  |
| TC14 | Java | rename identifiers in the object-oriented part | 0.8893 | 0.8414 | 1.0000 | 0.0000 | yes |  |
| TC14 | JavaScript | rename identifiers in the object-oriented part | 0.8221 | 0.7140 | 1.0000 | 0.0000 | yes |  |
| TC14 | PHP | rename identifiers in the object-oriented part | 0.8787 | 0.7288 | 1.0000 | 0.0000 | yes |  |
| TC14 | Python | rename identifiers in the object-oriented part | 0.8475 | 0.6821 | 1.0000 | 0.0000 | yes |  |
| TC14 | Ruby | rename identifiers in the object-oriented part | 0.7427 | 0.7390 | 1.0000 | 0.0000 | yes |  |
| TC15 | C | rename identifiers across the several functions | 0.8378 | 0.6278 | 1.0000 | 0.0000 | yes |  |
| TC15 | C# | rename identifiers across the several functions | 0.7557 | 0.5957 | 1.0000 | 0.0000 | yes |  |
| TC15 | C++ | rename identifiers across the several functions | 0.8187 | 0.6486 | 1.0000 | 0.0000 | yes |  |
| TC15 | Go | rename identifiers across the several functions | 0.7881 | 0.6379 | 1.0000 | 0.0000 | yes |  |
| TC15 | Java | rename identifiers across the several functions | 0.8095 | 0.6848 | 1.0000 | 0.0000 | yes |  |
| TC15 | JavaScript | rename identifiers across the several functions | 0.8416 | 0.6876 | 1.0000 | 0.0000 | yes |  |
| TC15 | PHP | rename identifiers across the several functions | 0.8410 | 0.6855 | 1.0000 | 0.0000 | yes |  |
| TC15 | Python | rename identifiers across the several functions | 0.8702 | 0.7039 | 1.0000 | 0.0000 | yes |  |
| TC15 | Ruby | rename identifiers across the several functions | 0.8780 | 0.7379 | 1.0000 | 0.0000 | yes |  |
| UNRELATED | C | unrelated program (control) | 0.3039 | 0.1049 | 0.4500 | 0.5500 | no | inventory program vs averaging program |
| UNRELATED | C# | unrelated program (control) | 0.3299 | 0.1127 | 0.3131 | 0.6869 | no | inventory program vs averaging program |
| UNRELATED | C++ | unrelated program (control) | 0.3202 | 0.2199 | 0.3631 | 0.6369 | no | inventory program vs averaging program |
| UNRELATED | Go | unrelated program (control) | 0.2075 | 0.0978 | 0.4598 | 0.5402 | no | inventory program vs averaging program |
| UNRELATED | Java | unrelated program (control) | 0.3086 | 0.1725 | 0.3446 | 0.6554 | no | inventory program vs averaging program |
| UNRELATED | JavaScript | unrelated program (control) | 0.3070 | 0.1561 | 0.3789 | 0.6211 | no | inventory program vs averaging program |
| UNRELATED | PHP | unrelated program (control) | 0.3160 | 0.1482 | 0.5448 | 0.4552 | no | inventory program vs averaging program |
| UNRELATED | Python | unrelated program (control) | 0.3340 | 0.1032 | 0.3703 | 0.6297 | no | inventory program vs averaging program |
| UNRELATED | Ruby | unrelated program (control) | 0.2789 | 0.1143 | 0.4234 | 0.5766 | no | inventory program vs averaging program |
| TC12 | C | rename identifiers in the nested function | N/A | N/A | N/A | N/A | N/A | C has no N_FUNC, N_PARAM (e.g. no nested functions) |
