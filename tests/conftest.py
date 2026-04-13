import shutil
from collections.abc import Callable
from pathlib import Path

import pytest


@pytest.fixture
def copy_example(tmp_path: Path) -> Callable[[str], Path]:
    """Fixture to copy the simple example into a temporary directory."""

    def copy_example_fn(example: str) -> Path:
        example_src = Path(__file__).parent.parent / "examples" / example
        dest = tmp_path / example
        shutil.copytree(example_src, dest)
        return dest

    return copy_example_fn


@pytest.fixture
def simple_example_dir(copy_example: Callable[[str], Path]) -> Path:
    """Fixture to copy the simple example into a temporary directory."""
    return copy_example("simple")
