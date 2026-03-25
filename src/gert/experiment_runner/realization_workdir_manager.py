"""Manager for creating and managing execution workdirs."""

import shutil
from pathlib import Path


class RealizationWorkdirManager:
    """Manages temporary scratch directories for experiment realizations.

    Creates isolated execution environments and optionally handles cleanup
    after successful completion. This manager is purely focused on directory
    lifecycle - parameter injection is handled by higher-level orchestrators.
    """

    def __init__(self, base_workdir: Path, *, enable_cleanup: bool = False) -> None:
        """Initialize the workdir manager.

        Args:
            base_workdir: Base directory for creating experiment workdirs.
            enable_cleanup: Whether to enable garbage collection of completed workdirs.
        """
        self._base_workdir = base_workdir
        self._enable_cleanup = enable_cleanup

    def create_workdir(
        self,
        experiment_id: str,
        ensemble_id: str,
        realization: int,
    ) -> Path:
        """Create a scratch directory for a realization.

        Creates a temporary directory structure like:
        {base_workdir}/{experiment_id}/{ensemble_id}/realization-{realization}/

        Args:
            experiment_id: Unique experiment identifier.
            ensemble_id: Unique ensemble identifier.
            realization: The realization number (0-based, must be >= 0).

        Returns:
            Path to the created workdir directory.

        Raises:
            ValueError: If realization numbers are negative.
        """
        if realization < 0:
            msg = f"Realization number must be >= 0, got: {realization}"
            raise ValueError(msg)

        workdir = self._build_workdir_path(experiment_id, ensemble_id, realization)

        # Remove existing directory if it exists to ensure clean state
        if workdir.exists():
            shutil.rmtree(workdir)

        # Create the directory structure
        workdir.mkdir(parents=True, exist_ok=False)

        return workdir

    def cleanup_workdir(
        self,
        experiment_id: str,
        ensemble_id: str,
        realization: int,
    ) -> None:
        """Clean up a scratch directory after successful completion.

        Only performs cleanup if enable_cleanup was set to True during initialization.

        Args:
            experiment_id: Unique experiment identifier.
            ensemble_id: Unique ensemble identifier.
            realization: The realization number (0-based).
        """
        if not self._enable_cleanup:
            return

        workdir = self._build_workdir_path(experiment_id, ensemble_id, realization)

        if workdir.exists():
            shutil.rmtree(workdir)

    def get_workdir(
        self,
        experiment_id: str,
        ensemble_id: str,
        realization: int,
    ) -> Path:
        """Get the workdir path for a specific realization.

        Args:
            experiment_id: Unique experiment identifier.
            ensemble_id: Unique ensemble identifier.
            realization: The realization number (0-based).

        Returns:
            Path to the workdir directory (may not exist).
        """
        return self._build_workdir_path(experiment_id, ensemble_id, realization)

    def _build_workdir_path(
        self,
        experiment_id: str,
        ensemble_id: str,
        realization: int,
    ) -> Path:
        """Build the standardized workdir path.

        Args:
            experiment_id: Unique experiment identifier.
            ensemble_id: Unique ensemble identifier.
            realization: The realization number.

        Returns:
            Path to the workdir directory.
        """
        return (
            self._base_workdir
            / experiment_id
            / str(ensemble_id)
            / f"realization-{realization}"
        )
