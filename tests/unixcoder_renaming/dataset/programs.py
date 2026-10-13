"""
Identifier-renaming dataset for the UniXcoder evaluation.

One inventory program per language, written as a ``string.Template`` whose
identifiers are named slots (``${CLASS}``, ``${P_QTY}`` ...). A renamed variant
is the SAME template filled with different names, so the program logic,
layout and comments are identical by construction; only identifiers change.
(PHP uses ``$$`` for a literal ``$``.)

The program: an inventory class (field + add/remove methods), a function
that totals stock (loop + condition) and one that lists low-stock items using
a nested function. C has no classes or nested functions: it uses a struct
with functions taking it, and has no NESTED slots.
"""

from __future__ import annotations

from string import Template

# --------------------------------------------------------------------------
# Identifier roles and naming schemes (snake_case words; cased per language)
# --------------------------------------------------------------------------

KIND = {  # role -> class | method | func | var
    "CLASS": "class", "FIELD": "var", "M_ADD": "method", "M_REMOVE": "method",
    "P_NAME": "var", "P_QTY": "var", "L_CURRENT": "var",
    "F_TOTAL": "func", "F_LOW": "func", "P_INV": "var", "P_LIMIT": "var",
    "L_TOTAL": "var", "L_RESULT": "var",
    "LOOP_KEY": "var", "LOOP_COUNT": "var", "LOOP_PRODUCT": "var", "LOOP_AMOUNT": "var",
    "N_FUNC": "func", "N_PARAM": "var",
}

SCHEMES = {
    # the original names (moderately descriptive)
    "base": {
        "CLASS": "inventory", "FIELD": "stock_map", "M_ADD": "add_item", "M_REMOVE": "remove_item",
        "P_NAME": "item_name", "P_QTY": "quantity", "L_CURRENT": "current",
        "F_TOTAL": "total_stock", "F_LOW": "low_stock", "P_INV": "store", "P_LIMIT": "limit",
        "L_TOTAL": "total", "L_RESULT": "result",
        "LOOP_KEY": "key", "LOOP_COUNT": "count", "LOOP_PRODUCT": "product", "LOOP_AMOUNT": "amount",
        "N_FUNC": "is_low", "N_PARAM": "level",
    },
    # plausible synonyms a student might choose
    "alt": {
        "CLASS": "stock_book", "FIELD": "counts", "M_ADD": "put_item", "M_REMOVE": "take_item",
        "P_NAME": "label", "P_QTY": "qty", "L_CURRENT": "existing",
        "F_TOTAL": "sum_stock", "F_LOW": "scarce_items", "P_INV": "shop", "P_LIMIT": "threshold",
        "L_TOTAL": "running_sum", "L_RESULT": "flagged",
        "LOOP_KEY": "sku", "LOOP_COUNT": "units", "LOOP_PRODUCT": "article", "LOOP_AMOUNT": "units_left",
        "N_FUNC": "below_limit", "N_PARAM": "value",
    },
    "short": {
        "CLASS": "inv", "FIELD": "m", "M_ADD": "add", "M_REMOVE": "rem",
        "P_NAME": "n", "P_QTY": "q", "L_CURRENT": "cur",
        "F_TOTAL": "tot", "F_LOW": "low", "P_INV": "st", "P_LIMIT": "lim",
        "L_TOTAL": "t", "L_RESULT": "r",
        "LOOP_KEY": "k", "LOOP_COUNT": "c", "LOOP_PRODUCT": "p", "LOOP_AMOUNT": "a",
        "N_FUNC": "f", "N_PARAM": "v",
    },
    "descriptive": {
        "CLASS": "product_inventory_ledger", "FIELD": "quantities_by_product_name",
        "M_ADD": "add_quantity_for_product", "M_REMOVE": "remove_quantity_for_product",
        "P_NAME": "product_name_to_update", "P_QTY": "quantity_to_change",
        "L_CURRENT": "quantity_currently_in_stock",
        "F_TOTAL": "compute_total_units_in_stock", "F_LOW": "find_products_below_limit",
        "P_INV": "inventory_to_inspect", "P_LIMIT": "minimum_acceptable_quantity",
        "L_TOTAL": "running_total_of_units", "L_RESULT": "names_of_low_products",
        "LOOP_KEY": "product_key_in_loop", "LOOP_COUNT": "unit_count_for_product",
        "LOOP_PRODUCT": "product_name_in_loop", "LOOP_AMOUNT": "units_available_now",
        "N_FUNC": "is_quantity_below_limit", "N_PARAM": "quantity_to_check",
    },
    # valid but semantically unrelated words
    "unrelated": {
        "CLASS": "galaxy", "FIELD": "banana_jar", "M_ADD": "paint_fence", "M_REMOVE": "juggle_cats",
        "P_NAME": "river_song", "P_QTY": "tango", "L_CURRENT": "moonbeam",
        "F_TOTAL": "whistle", "F_LOW": "carousel", "P_INV": "harbor", "P_LIMIT": "pebble",
        "L_TOTAL": "lantern", "L_RESULT": "compass",
        "LOOP_KEY": "orbit", "LOOP_COUNT": "velvet", "LOOP_PRODUCT": "glacier", "LOOP_AMOUNT": "meadow",
        "N_FUNC": "sneeze_loudly", "N_PARAM": "comet",
    },
}

COMMENTS = {
    "base": {"c1": "Inventory tracking for a small shop.", "c2": "increase the stock for this item"},
    "changed": {"c1": "Keeps track of how many units each product has.", "c2": "add units to the stored amount"},
}

STYLE = {  # language -> casing per kind
    "Python": {"class": "pascal", "method": "snake", "func": "snake", "var": "snake"},
    "Ruby": {"class": "pascal", "method": "snake", "func": "snake", "var": "snake"},
    "C": {"class": "pascal", "method": "snake", "func": "snake", "var": "snake"},
    "Java": {"class": "pascal", "method": "camel", "func": "camel", "var": "camel"},
    "JavaScript": {"class": "pascal", "method": "camel", "func": "camel", "var": "camel"},
    "C++": {"class": "pascal", "method": "camel", "func": "camel", "var": "camel"},
    "C#": {"class": "pascal", "method": "pascal", "func": "pascal", "var": "camel"},
    "Go": {"class": "pascal", "method": "pascal", "func": "pascal", "var": "camel"},
    "PHP": {"class": "pascal", "method": "camel", "func": "camel", "var": "camel"},
}
# Go's nested function is a local variable, so it stays unexported (camel).
STYLE_OVERRIDES = {("Go", "N_FUNC"): "camel", ("C#", "N_FUNC"): "pascal"}


def _case(words: str, style: str) -> str:
    parts = words.split("_")
    if style == "snake":
        return words
    if style == "camel":
        return parts[0] + "".join(p.capitalize() for p in parts[1:])
    return "".join(p.capitalize() for p in parts)


def names_for(lang: str, mapping: dict[str, str]) -> dict[str, str]:
    return {role: _case(words, STYLE_OVERRIDES.get((lang, role), STYLE[lang][KIND[role]]))
            for role, words in mapping.items()}


# --------------------------------------------------------------------------
# Programs
# --------------------------------------------------------------------------

TEMPLATES = {
    "Python": ("inventory.py", """\
# ${c1}
class ${CLASS}:
    def __init__(self):
        self.${FIELD} = {}

    def ${M_ADD}(self, ${P_NAME}, ${P_QTY}):
        # ${c2}
        ${L_CURRENT} = self.${FIELD}.get(${P_NAME}, 0)
        self.${FIELD}[${P_NAME}] = ${L_CURRENT} + ${P_QTY}

    def ${M_REMOVE}(self, ${P_NAME}, ${P_QTY}):
        ${L_CURRENT} = self.${FIELD}.get(${P_NAME}, 0)
        if ${P_QTY} > ${L_CURRENT}:
            return False
        self.${FIELD}[${P_NAME}] = ${L_CURRENT} - ${P_QTY}
        return True


def ${F_TOTAL}(${P_INV}):
    ${L_TOTAL} = 0
    for ${LOOP_KEY} in ${P_INV}.${FIELD}:
        ${LOOP_COUNT} = ${P_INV}.${FIELD}[${LOOP_KEY}]
        if ${LOOP_COUNT} > 0:
            ${L_TOTAL} = ${L_TOTAL} + ${LOOP_COUNT}
    return ${L_TOTAL}


def ${F_LOW}(${P_INV}, ${P_LIMIT}):
    def ${N_FUNC}(${N_PARAM}):
        return ${N_PARAM} < ${P_LIMIT}

    ${L_RESULT} = []
    for ${LOOP_PRODUCT}, ${LOOP_AMOUNT} in ${P_INV}.${FIELD}.items():
        if ${N_FUNC}(${LOOP_AMOUNT}):
            ${L_RESULT}.append(${LOOP_PRODUCT})
    return ${L_RESULT}
"""),
    "Java": ("Inventory.java", """\
import java.util.*;
import java.util.function.IntPredicate;

// ${c1}
public class ${CLASS} {
    private final Map<String, Integer> ${FIELD} = new HashMap<>();

    public void ${M_ADD}(String ${P_NAME}, int ${P_QTY}) {
        // ${c2}
        int ${L_CURRENT} = ${FIELD}.getOrDefault(${P_NAME}, 0);
        ${FIELD}.put(${P_NAME}, ${L_CURRENT} + ${P_QTY});
    }

    public boolean ${M_REMOVE}(String ${P_NAME}, int ${P_QTY}) {
        int ${L_CURRENT} = ${FIELD}.getOrDefault(${P_NAME}, 0);
        if (${P_QTY} > ${L_CURRENT}) {
            return false;
        }
        ${FIELD}.put(${P_NAME}, ${L_CURRENT} - ${P_QTY});
        return true;
    }

    public static int ${F_TOTAL}(${CLASS} ${P_INV}) {
        int ${L_TOTAL} = 0;
        for (String ${LOOP_KEY} : ${P_INV}.${FIELD}.keySet()) {
            int ${LOOP_COUNT} = ${P_INV}.${FIELD}.get(${LOOP_KEY});
            if (${LOOP_COUNT} > 0) {
                ${L_TOTAL} = ${L_TOTAL} + ${LOOP_COUNT};
            }
        }
        return ${L_TOTAL};
    }

    public static List<String> ${F_LOW}(${CLASS} ${P_INV}, int ${P_LIMIT}) {
        IntPredicate ${N_FUNC} = ${N_PARAM} -> ${N_PARAM} < ${P_LIMIT};
        List<String> ${L_RESULT} = new ArrayList<>();
        for (Map.Entry<String, Integer> ${LOOP_PRODUCT} : ${P_INV}.${FIELD}.entrySet()) {
            int ${LOOP_AMOUNT} = ${LOOP_PRODUCT}.getValue();
            if (${N_FUNC}.test(${LOOP_AMOUNT})) {
                ${L_RESULT}.add(${LOOP_PRODUCT}.getKey());
            }
        }
        return ${L_RESULT};
    }
}
"""),
    "JavaScript": ("inventory.js", """\
// ${c1}
class ${CLASS} {
    constructor() {
        this.${FIELD} = new Map();
    }

    ${M_ADD}(${P_NAME}, ${P_QTY}) {
        // ${c2}
        const ${L_CURRENT} = this.${FIELD}.get(${P_NAME}) || 0;
        this.${FIELD}.set(${P_NAME}, ${L_CURRENT} + ${P_QTY});
    }

    ${M_REMOVE}(${P_NAME}, ${P_QTY}) {
        const ${L_CURRENT} = this.${FIELD}.get(${P_NAME}) || 0;
        if (${P_QTY} > ${L_CURRENT}) {
            return false;
        }
        this.${FIELD}.set(${P_NAME}, ${L_CURRENT} - ${P_QTY});
        return true;
    }
}

function ${F_TOTAL}(${P_INV}) {
    let ${L_TOTAL} = 0;
    for (const ${LOOP_KEY} of ${P_INV}.${FIELD}.keys()) {
        const ${LOOP_COUNT} = ${P_INV}.${FIELD}.get(${LOOP_KEY});
        if (${LOOP_COUNT} > 0) {
            ${L_TOTAL} = ${L_TOTAL} + ${LOOP_COUNT};
        }
    }
    return ${L_TOTAL};
}

function ${F_LOW}(${P_INV}, ${P_LIMIT}) {
    function ${N_FUNC}(${N_PARAM}) {
        return ${N_PARAM} < ${P_LIMIT};
    }
    const ${L_RESULT} = [];
    for (const [${LOOP_PRODUCT}, ${LOOP_AMOUNT}] of ${P_INV}.${FIELD}) {
        if (${N_FUNC}(${LOOP_AMOUNT})) {
            ${L_RESULT}.push(${LOOP_PRODUCT});
        }
    }
    return ${L_RESULT};
}
"""),
    "C": ("inventory.c", """\
#define MAX_ITEMS 64

// ${c1}
struct ${CLASS} {
    int ${FIELD}[MAX_ITEMS];
};

void ${M_ADD}(struct ${CLASS} *self, int ${P_NAME}, int ${P_QTY}) {
    // ${c2}
    int ${L_CURRENT} = self->${FIELD}[${P_NAME}];
    self->${FIELD}[${P_NAME}] = ${L_CURRENT} + ${P_QTY};
}

int ${M_REMOVE}(struct ${CLASS} *self, int ${P_NAME}, int ${P_QTY}) {
    int ${L_CURRENT} = self->${FIELD}[${P_NAME}];
    if (${P_QTY} > ${L_CURRENT}) {
        return 0;
    }
    self->${FIELD}[${P_NAME}] = ${L_CURRENT} - ${P_QTY};
    return 1;
}

int ${F_TOTAL}(const struct ${CLASS} *${P_INV}) {
    int ${L_TOTAL} = 0;
    for (int ${LOOP_KEY} = 0; ${LOOP_KEY} < MAX_ITEMS; ${LOOP_KEY}++) {
        int ${LOOP_COUNT} = ${P_INV}->${FIELD}[${LOOP_KEY}];
        if (${LOOP_COUNT} > 0) {
            ${L_TOTAL} = ${L_TOTAL} + ${LOOP_COUNT};
        }
    }
    return ${L_TOTAL};
}

int ${F_LOW}(const struct ${CLASS} *${P_INV}, int ${P_LIMIT}, int *${L_RESULT}) {
    int found = 0;
    for (int ${LOOP_PRODUCT} = 0; ${LOOP_PRODUCT} < MAX_ITEMS; ${LOOP_PRODUCT}++) {
        int ${LOOP_AMOUNT} = ${P_INV}->${FIELD}[${LOOP_PRODUCT}];
        if (${LOOP_AMOUNT} < ${P_LIMIT}) {
            ${L_RESULT}[found] = ${LOOP_PRODUCT};
            found = found + 1;
        }
    }
    return found;
}
"""),
    "C++": ("inventory.cpp", """\
#include <map>
#include <string>
#include <vector>

// ${c1}
class ${CLASS} {
public:
    std::map<std::string, int> ${FIELD};

    void ${M_ADD}(const std::string &${P_NAME}, int ${P_QTY}) {
        // ${c2}
        int ${L_CURRENT} = ${FIELD}[${P_NAME}];
        ${FIELD}[${P_NAME}] = ${L_CURRENT} + ${P_QTY};
    }

    bool ${M_REMOVE}(const std::string &${P_NAME}, int ${P_QTY}) {
        int ${L_CURRENT} = ${FIELD}[${P_NAME}];
        if (${P_QTY} > ${L_CURRENT}) {
            return false;
        }
        ${FIELD}[${P_NAME}] = ${L_CURRENT} - ${P_QTY};
        return true;
    }
};

int ${F_TOTAL}(const ${CLASS} &${P_INV}) {
    int ${L_TOTAL} = 0;
    for (const auto &${LOOP_KEY} : ${P_INV}.${FIELD}) {
        int ${LOOP_COUNT} = ${LOOP_KEY}.second;
        if (${LOOP_COUNT} > 0) {
            ${L_TOTAL} = ${L_TOTAL} + ${LOOP_COUNT};
        }
    }
    return ${L_TOTAL};
}

std::vector<std::string> ${F_LOW}(const ${CLASS} &${P_INV}, int ${P_LIMIT}) {
    auto ${N_FUNC} = [${P_LIMIT}](int ${N_PARAM}) { return ${N_PARAM} < ${P_LIMIT}; };
    std::vector<std::string> ${L_RESULT};
    for (const auto &${LOOP_PRODUCT} : ${P_INV}.${FIELD}) {
        int ${LOOP_AMOUNT} = ${LOOP_PRODUCT}.second;
        if (${N_FUNC}(${LOOP_AMOUNT})) {
            ${L_RESULT}.push_back(${LOOP_PRODUCT}.first);
        }
    }
    return ${L_RESULT};
}
"""),
    "C#": ("Inventory.cs", """\
using System.Collections.Generic;

// ${c1}
public class ${CLASS}
{
    public Dictionary<string, int> ${FIELD} = new Dictionary<string, int>();

    public void ${M_ADD}(string ${P_NAME}, int ${P_QTY})
    {
        // ${c2}
        ${FIELD}.TryGetValue(${P_NAME}, out int ${L_CURRENT});
        ${FIELD}[${P_NAME}] = ${L_CURRENT} + ${P_QTY};
    }

    public bool ${M_REMOVE}(string ${P_NAME}, int ${P_QTY})
    {
        ${FIELD}.TryGetValue(${P_NAME}, out int ${L_CURRENT});
        if (${P_QTY} > ${L_CURRENT})
        {
            return false;
        }
        ${FIELD}[${P_NAME}] = ${L_CURRENT} - ${P_QTY};
        return true;
    }

    public static int ${F_TOTAL}(${CLASS} ${P_INV})
    {
        int ${L_TOTAL} = 0;
        foreach (var ${LOOP_KEY} in ${P_INV}.${FIELD}.Keys)
        {
            int ${LOOP_COUNT} = ${P_INV}.${FIELD}[${LOOP_KEY}];
            if (${LOOP_COUNT} > 0)
            {
                ${L_TOTAL} = ${L_TOTAL} + ${LOOP_COUNT};
            }
        }
        return ${L_TOTAL};
    }

    public static List<string> ${F_LOW}(${CLASS} ${P_INV}, int ${P_LIMIT})
    {
        bool ${N_FUNC}(int ${N_PARAM}) => ${N_PARAM} < ${P_LIMIT};
        var ${L_RESULT} = new List<string>();
        foreach (var ${LOOP_PRODUCT} in ${P_INV}.${FIELD})
        {
            int ${LOOP_AMOUNT} = ${LOOP_PRODUCT}.Value;
            if (${N_FUNC}(${LOOP_AMOUNT}))
            {
                ${L_RESULT}.Add(${LOOP_PRODUCT}.Key);
            }
        }
        return ${L_RESULT};
    }
}
"""),
    "Go": ("inventory.go", """\
package inventory

// ${c1}
type ${CLASS} struct {
	${FIELD} map[string]int
}

func (s *${CLASS}) ${M_ADD}(${P_NAME} string, ${P_QTY} int) {
	// ${c2}
	${L_CURRENT} := s.${FIELD}[${P_NAME}]
	s.${FIELD}[${P_NAME}] = ${L_CURRENT} + ${P_QTY}
}

func (s *${CLASS}) ${M_REMOVE}(${P_NAME} string, ${P_QTY} int) bool {
	${L_CURRENT} := s.${FIELD}[${P_NAME}]
	if ${P_QTY} > ${L_CURRENT} {
		return false
	}
	s.${FIELD}[${P_NAME}] = ${L_CURRENT} - ${P_QTY}
	return true
}

func ${F_TOTAL}(${P_INV} *${CLASS}) int {
	${L_TOTAL} := 0
	for ${LOOP_KEY}, ${LOOP_COUNT} := range ${P_INV}.${FIELD} {
		_ = ${LOOP_KEY}
		if ${LOOP_COUNT} > 0 {
			${L_TOTAL} = ${L_TOTAL} + ${LOOP_COUNT}
		}
	}
	return ${L_TOTAL}
}

func ${F_LOW}(${P_INV} *${CLASS}, ${P_LIMIT} int) []string {
	${N_FUNC} := func(${N_PARAM} int) bool { return ${N_PARAM} < ${P_LIMIT} }
	${L_RESULT} := []string{}
	for ${LOOP_PRODUCT}, ${LOOP_AMOUNT} := range ${P_INV}.${FIELD} {
		if ${N_FUNC}(${LOOP_AMOUNT}) {
			${L_RESULT} = append(${L_RESULT}, ${LOOP_PRODUCT})
		}
	}
	return ${L_RESULT}
}
"""),
    "PHP": ("inventory.php", """\
<?php
// ${c1}
class ${CLASS} {
    public array $$${FIELD} = [];

    public function ${M_ADD}(string $$${P_NAME}, int $$${P_QTY}): void {
        // ${c2}
        $$${L_CURRENT} = $$this->${FIELD}[$$${P_NAME}] ?? 0;
        $$this->${FIELD}[$$${P_NAME}] = $$${L_CURRENT} + $$${P_QTY};
    }

    public function ${M_REMOVE}(string $$${P_NAME}, int $$${P_QTY}): bool {
        $$${L_CURRENT} = $$this->${FIELD}[$$${P_NAME}] ?? 0;
        if ($$${P_QTY} > $$${L_CURRENT}) {
            return false;
        }
        $$this->${FIELD}[$$${P_NAME}] = $$${L_CURRENT} - $$${P_QTY};
        return true;
    }
}

function ${F_TOTAL}(${CLASS} $$${P_INV}): int {
    $$${L_TOTAL} = 0;
    foreach ($$${P_INV}->${FIELD} as $$${LOOP_KEY} => $$${LOOP_COUNT}) {
        if ($$${LOOP_COUNT} > 0) {
            $$${L_TOTAL} = $$${L_TOTAL} + $$${LOOP_COUNT};
        }
    }
    return $$${L_TOTAL};
}

function ${F_LOW}(${CLASS} $$${P_INV}, int $$${P_LIMIT}): array {
    $$${N_FUNC} = function (int $$${N_PARAM}) use ($$${P_LIMIT}): bool {
        return $$${N_PARAM} < $$${P_LIMIT};
    };
    $$${L_RESULT} = [];
    foreach ($$${P_INV}->${FIELD} as $$${LOOP_PRODUCT} => $$${LOOP_AMOUNT}) {
        if ($$${N_FUNC}($$${LOOP_AMOUNT})) {
            $$${L_RESULT}[] = $$${LOOP_PRODUCT};
        }
    }
    return $$${L_RESULT};
}
"""),
    "Ruby": ("inventory.rb", """\
# ${c1}
class ${CLASS}
  attr_reader :${FIELD}

  def initialize
    @${FIELD} = Hash.new(0)
  end

  def ${M_ADD}(${P_NAME}, ${P_QTY})
    # ${c2}
    ${L_CURRENT} = @${FIELD}[${P_NAME}]
    @${FIELD}[${P_NAME}] = ${L_CURRENT} + ${P_QTY}
  end

  def ${M_REMOVE}(${P_NAME}, ${P_QTY})
    ${L_CURRENT} = @${FIELD}[${P_NAME}]
    return false if ${P_QTY} > ${L_CURRENT}
    @${FIELD}[${P_NAME}] = ${L_CURRENT} - ${P_QTY}
    true
  end
end

def ${F_TOTAL}(${P_INV})
  ${L_TOTAL} = 0
  ${P_INV}.${FIELD}.each do |${LOOP_KEY}, ${LOOP_COUNT}|
    if ${LOOP_COUNT} > 0
      ${L_TOTAL} = ${L_TOTAL} + ${LOOP_COUNT}
    end
  end
  ${L_TOTAL}
end

def ${F_LOW}(${P_INV}, ${P_LIMIT})
  ${N_FUNC} = ->(${N_PARAM}) { ${N_PARAM} < ${P_LIMIT} }
  ${L_RESULT} = []
  ${P_INV}.${FIELD}.each do |${LOOP_PRODUCT}, ${LOOP_AMOUNT}|
    ${L_RESULT} << ${LOOP_PRODUCT} if ${N_FUNC}.call(${LOOP_AMOUNT})
  end
  ${L_RESULT}
end
"""),
}


def roles_in(lang: str) -> set[str]:
    _, text = TEMPLATES[lang]
    return {r for r in KIND if "${" + r + "}" in text}


def render(lang: str, renamed: dict[str, str] | None = None, comments: str = "base") -> str:
    """The language's program with the base names, except roles in `renamed`
    (role -> snake_case words) which get those names instead."""
    mapping = dict(SCHEMES["base"])
    mapping.update(renamed or {})
    names = names_for(lang, mapping)
    return Template(TEMPLATES[lang][1]).substitute(**names, **COMMENTS[comments])
