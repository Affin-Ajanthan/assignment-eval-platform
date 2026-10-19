"""
Language-mismatch check: does the video or report talk about a different
programming language from the one the submitted code is written in?

The meaning-based cross-modal check (semantic_consistency.py) compares
*topics*, so the same project written in another language -- e.g. a C#
walkthrough video handed in with a Go solution -- still scores as
consistent. This check closes that gap with something simple and
explainable: count the programming languages each text names and compare
them with the languages of the submitted source files.

A text is flagged only when it names some other language at least
``MIN_MENTIONS`` times and never names a language that is actually in the
code -- so a report that compares "unlike Python, Go ..." is not flagged.
Patterns are deliberately conservative: words that are also ordinary
English ("go", "swift", "rust") only count in unambiguous forms such as
"golang" or "Go programming language"; a missed mention means no flag,
never a wrong one.

THIS IS A REVIEW SIGNAL ONLY. It never changes marks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# A text needs at least this many mentions of other languages to be
# flagged, so one passing remark ("I first learned Java") is not enough.
MIN_MENTIONS = 2

DISPLAY_NAMES = {
    "python": "Python",
    "java": "Java",
    "javascript": "JavaScript/TypeScript",
    "c": "C",
    "cpp": "C++",
    "csharp": "C#",
    "go": "Go",
    "ruby": "Ruby",
    "php": "PHP",
    "kotlin": "Kotlin",
    "rust": "Rust",
}

_EXTENSIONS = {
    ".py": "python", ".ipynb": "python",
    ".java": "java",
    ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript", ".jsx": "javascript",
    ".ts": "javascript", ".tsx": "javascript",
    ".c": "c", ".h": "c",
    ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".hpp": "cpp", ".hh": "cpp", ".hxx": "cpp",
    ".cs": "csharp",
    ".go": "go",
    ".rb": "ruby",
    ".php": "php",
    ".kt": "kotlin", ".kts": "kotlin",
    ".rs": "rust",
}

# Matched against lower-cased text. Whisper writes C# as "C-Sharp" or
# "C sharp", and .NET as ".net" -- both forms are covered.
_PATTERNS = {
    "python": [r"\bpython\b", r"\bdjango\b", r"\bjupyter\b"],
    "java": [r"\bjava\b(?![\s-]*script)", r"\bjdk\b", r"\bspring boot\b"],
    "javascript": [r"\bjava[\s-]?script\b", r"\btypescript\b", r"\bnode\.?js\b", r"\breact(?:\.js|js)\b"],
    "c": [r"\bc (?:programming )?language\b", r"\bansi c\b", r"\bc programming\b"],
    "cpp": [r"(?<!\w)c\s*\+\+", r"\bc[\s-]?plus[\s-]?plus\b", r"\bcpp\b"],
    "csharp": [r"(?<![\w+#])c\s?#", r"\bc[\s-]?sharp\b", r"\bcsharp\b", r"(?<![\w.])\.net\b", r"\bdotnet\b"],
    "go": [r"\bgolang\b", r"\bgo (?:programming )?language\b", r"\bgo lang\b", r"\bgoroutines?\b"],
    "ruby": [r"\bruby\b"],
    "php": [r"\bphp\b", r"\blaravel\b"],
    "kotlin": [r"\bkotlin\b"],
    "rust": [r"\brust (?:programming )?language\b", r"\brustlang\b"],
}
_COMPILED = {lang: [re.compile(p) for p in pats] for lang, pats in _PATTERNS.items()}

# Languages that legitimately describe each other's code: a C++ project
# is often called "C/C++", and .h headers are shared by both.
_COMPATIBLE = {"c": {"c", "cpp"}, "cpp": {"c", "cpp"}}


@dataclass
class LanguageMismatch:
    source: str  # "video transcript" | "report"
    mentioned: dict[str, int]  # other languages named, with counts
    code_languages: list[str]

    @property
    def named(self) -> str:
        """The other languages the text names, most-mentioned first."""
        return ", ".join(DISPLAY_NAMES[l] for l, _ in sorted(self.mentioned.items(), key=lambda kv: -kv[1]))

    @property
    def code(self) -> str:
        return ", ".join(DISPLAY_NAMES[l] for l in self.code_languages)

    @property
    def flag(self) -> str:
        named = ", ".join(f"{DISPLAY_NAMES[l]} ({n} mention{'s' if n != 1 else ''})"
                          for l, n in sorted(self.mentioned.items(), key=lambda kv: -kv[1]))
        return (f"language mismatch: the {self.source} talks about {named} but the submitted code is {self.code} "
                f"-- check that the {self.source} belongs to this submission")


def code_languages(code_dir: Path | None) -> list[str]:
    """Languages of the submitted source files, most files first."""
    if not code_dir:
        return []
    counts: dict[str, int] = {}
    for path in Path(code_dir).rglob("*"):
        lang = _EXTENSIONS.get(path.suffix.lower()) if path.is_file() else None
        if lang:
            counts[lang] = counts.get(lang, 0) + 1
    return sorted(counts, key=lambda l: (-counts[l], l))


def mentioned_languages(text: str | None) -> dict[str, int]:
    """How many times each programming language is named in the text."""
    if not text:
        return {}
    low = text.lower()
    counts = {lang: sum(len(p.findall(low)) for p in pats) for lang, pats in _COMPILED.items()}
    return {lang: n for lang, n in counts.items() if n}


def _matches_code(lang: str, code_langs: list[str]) -> bool:
    return any(lang in _COMPATIBLE.get(c, {c}) for c in code_langs)


def check_text(text: str | None, code_langs: list[str], source: str) -> LanguageMismatch | None:
    if not code_langs:
        return None
    mentioned = mentioned_languages(text)
    if any(_matches_code(l, code_langs) for l in mentioned):
        return None  # the text names the code's own language: no mismatch
    if sum(mentioned.values()) < MIN_MENTIONS:
        return None
    return LanguageMismatch(source=source, mentioned=mentioned, code_languages=code_langs)


def language_mismatches(code_dir: Path | None, *, transcript: str | None,
                        report_text: str | None) -> list[LanguageMismatch]:
    langs = code_languages(code_dir)
    found = (check_text(transcript, langs, "video transcript"), check_text(report_text, langs, "report"))
    return [m for m in found if m]
