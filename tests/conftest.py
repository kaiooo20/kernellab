"""Coloca src/ no caminho de importação e oferece fixtures comuns."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from models import DATA_DIR, load_processes  # noqa: E402


@pytest.fixture
def processes():
    return load_processes(DATA_DIR / "processes.json")


@pytest.fixture
def reference_string():
    return [1, 2, 3, 4, 1, 2, 5, 1, 2, 3, 4, 5, 2, 1, 5, 3, 2]
