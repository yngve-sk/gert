"""Tests for RealizationWorkdirManager directory operations."""

import tempfile
import uuid
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from gert.experiment_runner.realization_workdir_manager import RealizationWorkdirManager


class TestRealizationWorkdirManager:
    """Test suite for RealizationWorkdirManager directory operations."""

    def test_manager_initialization_with_cleanup_disabled(self, tmp_path: Path) -> None:
        """Manager initializes correctly with cleanup disabled by default."""
        manager = RealizationWorkdirManager(base_workdir=tmp_path)

        assert manager._base_workdir == tmp_path
        assert manager._enable_cleanup is False

    def test_manager_initialization_with_cleanup_enabled(self, tmp_path: Path) -> None:
        """Manager initializes correctly when cleanup is explicitly enabled."""
        manager = RealizationWorkdirManager(base_workdir=tmp_path, enable_cleanup=True)

        assert manager._base_workdir == tmp_path
        assert manager._enable_cleanup is True

    def test_create_workdir_creates_nested_directory_structure(
        self,
        tmp_path: Path,
    ) -> None:
        """Creating workdir establishes the correct nested folder hierarchy."""
        manager = RealizationWorkdirManager(base_workdir=tmp_path)

        workdir = manager.create_workdir(
            experiment_name="exp-123",
            execution_id="ens-abc",
            iteration=0,
            realization=5,
        )

        expected_path = tmp_path / "exp-123" / "ens-abc" / "iter-0" / "realization-5"
        assert workdir == expected_path
        assert workdir.exists()
        assert workdir.is_dir()

    def test_create_workdir_handles_multiple_iterations_in_same_realization(
        self,
        tmp_path: Path,
    ) -> None:
        """Multiple iterations can coexist within the same realization."""
        manager = RealizationWorkdirManager(base_workdir=tmp_path)

        workdir_iter0 = manager.create_workdir("exp-1", "exec-1", 0, 1)
        workdir_iter1 = manager.create_workdir("exp-1", "exec-1", 1, 1)
        workdir_iter2 = manager.create_workdir("exp-1", "exec-1", 2, 1)

        assert workdir_iter0.exists()
        assert workdir_iter1.exists()
        assert workdir_iter2.exists()
        assert workdir_iter0.parent.name == "iter-0"
        assert workdir_iter0.parent.parent.name == "exec-1"
        assert workdir_iter1.parent.name == "iter-1"
        assert workdir_iter2.parent.name == "iter-2"

    def test_create_workdir_handles_multiple_realizations_in_same_experiment(
        self,
        tmp_path: Path,
    ) -> None:
        """Multiple realizations can coexist within the same experiment."""
        manager = RealizationWorkdirManager(base_workdir=tmp_path)

        workdir_1 = manager.create_workdir("exp-multi", "exec-1", 0, 1)
        workdir_2 = manager.create_workdir("exp-multi", "exec-1", 0, 2)
        workdir_3 = manager.create_workdir("exp-multi", "exec-1", 0, 3)

        assert workdir_1.exists()
        assert workdir_2.exists()
        assert workdir_3.exists()
        assert workdir_1.name == "realization-1"
        assert workdir_2.name == "realization-2"
        assert workdir_3.name == "realization-3"

    def test_get_workdir_returns_correct_path_without_creation(
        self,
        tmp_path: Path,
    ) -> None:
        """get_workdir returns the expected path without creating directories."""
        manager = RealizationWorkdirManager(base_workdir=tmp_path)

        workdir = manager.get_workdir("exp-test", "exec-1", 2, 7)

        expected_path = tmp_path / "exp-test" / "exec-1" / "iter-2" / "realization-7"
        assert workdir == expected_path
        assert not workdir.exists()  # Should not create the directory

    def test_cleanup_workdir_removes_directory_when_cleanup_enabled(
        self,
        tmp_path: Path,
    ) -> None:
        """Cleanup removes workdir when enable_cleanup is True."""
        manager = RealizationWorkdirManager(base_workdir=tmp_path, enable_cleanup=True)

        # Create workdir first
        workdir = manager.create_workdir("exp-cleanup", "exec-1", 0, 1)
        assert workdir.exists()

        # Cleanup should remove it
        manager.cleanup_workdir("exp-cleanup", "exec-1", 0, 1)
        assert not workdir.exists()

    def test_cleanup_workdir_preserves_directory_when_cleanup_disabled(
        self,
        tmp_path: Path,
    ) -> None:
        """Cleanup preserves workdir when enable_cleanup is False."""
        manager = RealizationWorkdirManager(base_workdir=tmp_path, enable_cleanup=False)

        # Create workdir first
        workdir = manager.create_workdir("exp-preserve", "exec-1", 0, 1)
        assert workdir.exists()

        # Cleanup should NOT remove it
        manager.cleanup_workdir("exp-preserve", "exec-1", 0, 1)
        assert workdir.exists()

    def test_cleanup_workdir_handles_nonexistent_directory_gracefully(
        self,
        tmp_path: Path,
    ) -> None:
        """Cleanup handles attempts to clean nonexistent directories without error."""
        manager = RealizationWorkdirManager(base_workdir=tmp_path, enable_cleanup=True)

        # Should not raise exception
        manager.cleanup_workdir("nonexistent-exp", "exec-1", 0, 1)

    def test_create_workdir_rejects_negative_realization_number(
        self,
        tmp_path: Path,
    ) -> None:
        """Creating workdir with negative realization number raises ValueError."""
        manager = RealizationWorkdirManager(base_workdir=tmp_path)

        with pytest.raises(
            ValueError,
            match=r"Realization number must be >= 0, got: -5",
        ):
            manager.create_workdir("exp-fail", "exec-1", 0, -5)

    def test_create_workdir_accepts_zero_values(self, tmp_path: Path) -> None:
        """Zero values for realization are valid."""
        manager = RealizationWorkdirManager(base_workdir=tmp_path)

        workdir = manager.create_workdir("exp-zero", "exec-1", 0, 0)

        assert workdir.exists()
        assert "realization-0" in str(workdir)
        assert "exec-1" in str(workdir)

    @given(
        execution_id=st.text(min_size=1, max_size=10, alphabet="abcdef0123456789"),
        realization=st.integers(min_value=0, max_value=1000),
    )
    def test_create_workdir_handles_various_valid_inputs(
        self,
        execution_id: str,
        realization: int,
    ) -> None:
        """Directory creation works correctly across wide range of valid inputs."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            base_workdir = Path(tmp_dir)
            # Generate a realistic experiment ID using UUID4
            experiment_name = str(uuid.uuid4())
            manager = RealizationWorkdirManager(base_workdir=base_workdir)

            workdir = manager.create_workdir(
                experiment_name,
                execution_id,
                0,
                realization,
            )

            assert workdir.exists()
            assert workdir.is_dir()
            assert experiment_name in str(workdir)
            assert f"realization-{realization}" in str(workdir)
            assert execution_id in str(workdir)

    def test_create_workdir_overwrites_existing_directory(self, tmp_path: Path) -> None:
        """Creating workdir twice overwrites existing directory."""
        manager = RealizationWorkdirManager(base_workdir=tmp_path)

        # Create initial workdir and add a test file
        workdir = manager.create_workdir("exp-overwrite", "exec-1", 0, 1)
        test_file = workdir / "test.txt"
        test_file.write_text("original content")

        # Overwrite should recreate the directory
        workdir_2 = manager.create_workdir("exp-overwrite", "exec-1", 0, 1)

        assert workdir == workdir_2  # Same path
        assert workdir.exists()
        # Original test file should be gone (directory was recreated)
        assert not test_file.exists()

    def test_cleanup_partial_hierarchy_preserves_parent_directories(
        self,
        tmp_path: Path,
    ) -> None:
        """Cleanup removes specific iteration directory, preserving parent structure."""
        manager = RealizationWorkdirManager(base_workdir=tmp_path, enable_cleanup=True)

        # Create multiple iterations in same realization
        workdir_iter0 = manager.create_workdir("exp-partial", "exec-1", 0, 1)
        workdir_iter1 = manager.create_workdir("exp-partial", "exec-1", 1, 1)

        # Cleanup only one iteration
        manager.cleanup_workdir("exp-partial", "exec-1", 0, 1)

        assert not workdir_iter0.exists()
        assert workdir_iter1.exists()
        assert (tmp_path / "exp-partial" / "exec-1").exists()  # Parent preserved
