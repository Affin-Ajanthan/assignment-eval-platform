"""Reading numeric settings from environment variables (.env), with a default
when one is unset or not a number. Imports nothing from the app, so any module
-- the evaluators included -- can use it without import cycles."""

from __future__ import annotations

import os


def env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default
