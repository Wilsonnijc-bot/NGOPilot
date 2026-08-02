import sys
from pathlib import Path

import pytest

# make `app` importable without installing the package
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.engine import build_baseline  # noqa: E402
from app.mockdata import example_changes, generate_dataset  # noqa: E402


@pytest.fixture(scope="session")
def dataset():
    return generate_dataset()


@pytest.fixture(scope="session")
def baseline(dataset):
    return build_baseline(dataset)


@pytest.fixture(scope="session")
def events(dataset):
    return example_changes(dataset)
