import shutil
from collections.abc import Callable, Generator
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from gert.server.gert_server import create_gert_server
from gert.server.router import ServerState


# THIS IS THE CRITICAL FIX:
@pytest.fixture(autouse=True)
def clear_server_state() -> Generator[None]:
    """
    An autouse fixture that automatically clears the ServerState singleton
    after every single test. This prevents state from one test from leaking
    into another, which is the cause of the hanging.
    """
    # Let the test run
    yield
    # After the test is finished, ALWAYS clear the in-memory state.
    ServerState.get().clear()


@pytest.fixture
def copy_example(tmp_path: Path) -> Callable[[str], Path]:
    """Fixture to copy the simple example into a temporary directory."""

    def copy_example_fn(example: str) -> Path:
        example_src = Path(__file__).parent.parent / "examples" / example
        dest = tmp_path / example
        shutil.copytree(
            example_src,
            dest,
            ignore=shutil.ignore_patterns(
                "permanent_storage",
                "workdirs",
                "__pycache__",
            ),
        )
        return dest

    return copy_example_fn


@pytest.fixture
def simple_example_dir(copy_example: Callable[[str], Path]) -> Path:
    """Fixture to copy the simple example into a temporary directory."""
    return copy_example("simple")


@pytest.fixture
def client() -> Generator[TestClient]:
    """Provides a fresh, isolated TestClient for each test.

    Yields:
        TestClient: An initialized FastAPI test client.
    """
    app = create_gert_server()
    with TestClient(app) as c:
        yield c
