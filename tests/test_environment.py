import sqlite3
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_runtime_matches_declared_minimum() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]

    assert project["requires-python"] == ">=3.12"
    assert sys.version_info >= (3, 12)


def test_sqlite_is_available_in_the_standard_runtime() -> None:
    with sqlite3.connect(":memory:") as connection:
        result = connection.execute("SELECT 1").fetchone()

    assert result == (1,)
