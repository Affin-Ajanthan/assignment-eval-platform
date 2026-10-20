"""The programming languages students can submit code in, and the file
extensions each one covers. An instructor may restrict an assignment to some
of them (``Assignment.code_languages``); no restriction accepts them all.

Must match CODE_LANGUAGES in frontend/src/lib/codeLanguages.ts.
"""

from __future__ import annotations

from typing import Literal

# id -> (display name, extensions). A ".h" header belongs to both C and C++.
CODE_LANGUAGES: dict[str, tuple[str, tuple[str, ...]]] = {
    "python": ("Python", (".py", ".ipynb")),
    "java": ("Java", (".java",)),
    "javascript": ("JavaScript", (".js",)),
    "c": ("C", (".c", ".h")),
    "cpp": ("C++", (".cpp", ".cc", ".cxx", ".h", ".hpp", ".hh", ".hxx")),
    "csharp": ("C#", (".cs",)),
    "go": ("Go", (".go",)),
    "ruby": ("Ruby", (".rb",)),
    "php": ("PHP", (".php",)),
}

CodeLanguage = Literal["python", "java", "javascript", "c", "cpp", "csharp", "go", "ruby", "php"]


def normalise_languages(languages: list[str] | None) -> list[str] | None:
    """Canonical order, duplicates removed; an empty choice means "any language" (None)."""
    chosen = [lang for lang in CODE_LANGUAGES if lang in set(languages or [])]
    return chosen or None


def allowed_extensions(languages: list[str] | None) -> set[str] | None:
    """Extensions the chosen languages cover; None when any language is accepted."""
    if not languages:
        return None
    return {ext for lang in languages for ext in CODE_LANGUAGES[lang][1]}


def describe(languages: list[str]) -> str:
    """'Go (.go)' or 'C (.c, .h) or C++ (.cpp, ...)' for messages."""
    parts = [f"{CODE_LANGUAGES[l][0]} ({', '.join(CODE_LANGUAGES[l][1])})" for l in languages]
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " or " + parts[-1]


def language_of(extension: str) -> str:
    """Display name for a file extension, e.g. '.py' -> 'Python', '.h' -> 'C/C++'."""
    names = [name for name, exts in CODE_LANGUAGES.values() if extension in exts]
    return "/".join(names) if names else extension
