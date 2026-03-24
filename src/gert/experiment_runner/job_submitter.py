"""Job submission adapter for psij-python integration."""

from collections.abc import Callable, Mapping
from datetime import timedelta
from pathlib import Path

import psij


class JobSubmitter:
    """Single implementation that adapts GERT queue_config to psij-python."""

    def __init__(
        self,
        queue_config: Mapping[str, str | int],
        executor_type: str = "local",
    ) -> None:
        """Initialize with queue config and psij executor type.

        Args:
            queue_config: GERT's generic queue configuration.
            executor_type: The psij executor type (local, slurm, lsf, etc.).
        """
        self._queue_config = queue_config
        self._executor = psij.JobExecutor.get_instance(executor_type)

    def submit(
        self,
        execution_steps: list[str],
        directory: Path | None = None,
        status_callback: Callable[[psij.Job, psij.JobStatus], None] | None = None,
    ) -> str:
        """Submit a job using the configured queue settings.

        Args:
            execution_steps: List of shell commands to execute sequentially.
            directory: The directory to execute the job in.
            status_callback: Optional callback for job status changes.

        Returns:
            The job ID from the backend scheduler.
        """
        job_spec = self._translate_to_psij_spec(execution_steps, directory=directory)
        job = psij.Job(job_spec)
        if status_callback:
            job.set_job_status_callback(status_callback)
        self._executor.submit(job)
        return str(job.id)

    def _translate_to_psij_spec(
        self,
        execution_steps: list[str],
        directory: Path | None = None,
    ) -> psij.JobSpec:
        """Translate GERT queue config into psij JobSpec.

        Args:
            execution_steps: List of shell commands to execute sequentially.
            directory: The directory to execute the job in.

        Returns:
            A psij JobSpec ready for submission.
        """
        # Create the executable from the execution steps
        # For multiple steps, we'll chain them with &&
        command = " && ".join(execution_steps)

        # Create resource specification from queue_config
        resources = psij.ResourceSpecV1()

        # Map common resource parameters
        if "cores" in self._queue_config:
            resources.process_count = int(self._queue_config["cores"])

        if "memory" in self._queue_config:
            memory_str = str(self._queue_config["memory"])
            # Convert memory strings like "4GB", "512MB" to bytes
            resources.memory = self._parse_memory_string(memory_str)

        # Create job attributes for scheduler-specific settings
        attributes = psij.JobAttributes()

        if "wall_time" in self._queue_config:
            wall_time_str = str(self._queue_config["wall_time"])
            # Convert time strings like "02:00:00", "30m" to timedelta
            attributes.duration = self._parse_time_string(wall_time_str)

        if "queue_name" in self._queue_config:
            attributes.queue_name = str(self._queue_config["queue_name"])

        if "project" in self._queue_config:
            attributes.account = str(self._queue_config["project"])

        job_name = None
        if "job_name" in self._queue_config:
            job_name = str(self._queue_config["job_name"])

        # Create and return the JobSpec
        return psij.JobSpec(
            executable="/bin/bash",
            arguments=["-c", command],
            resources=resources,
            attributes=attributes,
            name=job_name,
            directory=directory,
        )

    def _parse_memory_string(self, memory_str: str) -> int:
        """Parse memory strings like '4GB', '512MB' into bytes.

        Args:
            memory_str: Memory specification string.

        Returns:
            Memory in bytes.
        """
        memory_str = memory_str.upper().strip()

        if memory_str.endswith("GB"):
            return int(float(memory_str[:-2]) * 1024 * 1024 * 1024)
        if memory_str.endswith("MB"):
            return int(float(memory_str[:-2]) * 1024 * 1024)
        if memory_str.endswith("KB"):
            return int(float(memory_str[:-2]) * 1024)
        if memory_str.endswith("B"):
            return int(memory_str[:-1])
        # Assume bytes if no suffix
        return int(memory_str)

    def _parse_time_string(self, time_str: str) -> timedelta:
        """Parse time strings like '02:00:00', '30m', '1h' into timedelta.

        Args:
            time_str: Time specification string.

        Returns:
            Time duration as timedelta.

        Raises:
            ValueError: If the time format is invalid.
        """
        time_str = time_str.strip().lower()

        # Handle HH:MM:SS format
        if ":" in time_str:
            parts = time_str.split(":")
            if len(parts) == 3:
                try:
                    hours, minutes, seconds = map(int, parts)
                    # Validate reasonable ranges for HH:MM:SS format
                    if not (
                        0 <= hours <= 23 and 0 <= minutes <= 59 and 0 <= seconds <= 59
                    ):
                        msg = f"Invalid time format: '{time_str}'"
                        raise ValueError(msg)
                    return timedelta(hours=hours, minutes=minutes, seconds=seconds)
                except ValueError as e:
                    msg = f"Invalid time format: '{time_str}'"
                    raise ValueError(msg) from e

        # Handle suffixed formats
        if time_str.endswith("h"):
            return timedelta(hours=float(time_str[:-1]))
        if time_str.endswith("m"):
            return timedelta(minutes=float(time_str[:-1]))
        if time_str.endswith("s"):
            return timedelta(seconds=float(time_str[:-1]))

        # Handle bare numbers as seconds
        try:
            return timedelta(seconds=float(time_str))
        except ValueError as e:
            msg = f"Invalid time format: '{time_str}'"
            raise ValueError(msg) from e
