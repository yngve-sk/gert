"""Tests for JobSubmitter local execution functionality."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Mapping
from datetime import timedelta
from pathlib import Path

import psij
import pytest
from hypothesis import given
from hypothesis import strategies as st

from gert.experiment_runner.job_submitter import JobSubmitter


class TestJobSubmitter:
    """Test suite for JobSubmitter local execution functionality."""

    async def _wait_for_condition(
        self,
        condition: Callable[[], bool],
        timeout_seconds: float = 2.0,
        interval: float = 0.01,
    ) -> bool:
        """Wait for a condition to become true with a timeout."""
        start_time = time.time()
        while time.time() - start_time < timeout_seconds:
            if condition():
                return True
            await asyncio.sleep(interval)
        return False

    def test_job_submitter_stores_queue_config(self) -> None:
        """JobSubmitter stores the queue configuration for later use."""
        queue_config: Mapping[str, str | int] = {"cores": 8, "memory": "4GB"}
        submitter = JobSubmitter(queue_config=queue_config)

        assert submitter._queue_config == queue_config

    async def test_submit_executes_single_command_and_produces_output(
        self,
        tmp_path: Path,
    ) -> None:
        """JobSubmitter executes a simple command and produces expected output."""
        submitter = JobSubmitter(queue_config={"cores": 1})
        output_file = tmp_path / "test_output.txt"

        job_id = submitter.submit(
            execution_steps=[
                {"name": "echo", "command": f"echo 'Hello from job' > {output_file}"},
            ],
        )

        # Wait for job completion (local executor should be fast)
        assert await self._wait_for_condition(output_file.exists)

        assert isinstance(job_id, str)
        assert output_file.exists()
        assert output_file.read_text().strip() == "Hello from job"

    async def test_submit_executes_chained_commands_in_sequence(
        self,
        tmp_path: Path,
    ) -> None:
        """JobSubmitter chains multiple commands with && and executes them in order."""
        submitter = JobSubmitter(queue_config={})
        output_file = tmp_path / "chain_output.txt"

        job_id = submitter.submit(
            execution_steps=[
                {"name": "step1", "command": f"echo 'Step 1' > {output_file}"},
                {"name": "step2", "command": f"echo 'Step 2' >> {output_file}"},
                {"name": "step3", "command": f"echo 'Step 3' >> {output_file}"},
            ],
        )

        def all_steps_done() -> bool:
            if not output_file.exists():
                return False
            content = output_file.read_text().strip().split("\n")
            return len(content) == 3

        # Wait for all commands to finish writing
        assert await self._wait_for_condition(all_steps_done)

        assert isinstance(job_id, str)

        content = output_file.read_text().strip().split("\n")
        assert content == ["Step 1", "Step 2", "Step 3"]

    async def test_submit_with_different_executor_types(self, tmp_path: Path) -> None:
        """JobSubmitter works with different executor types (local vs others)."""
        # Test local executor (should always work)
        local_submitter = JobSubmitter(queue_config={}, executor_type="local")
        output_file = tmp_path / "local_test.txt"

        job_id = local_submitter.submit(
            execution_steps=[
                {"name": "local", "command": f"echo 'Local execution' > {output_file}"},
            ],
        )

        assert await self._wait_for_condition(output_file.exists)

        assert isinstance(job_id, str)
        assert output_file.exists()
        assert "Local execution" in output_file.read_text()

    def test_submit_handles_command_failure_gracefully(self, tmp_path: Path) -> None:
        """JobSubmitter returns job ID even if command will fail."""
        submitter = JobSubmitter(queue_config={})

        # This command will fail, but submit should still return a job ID
        job_id = submitter.submit(
            execution_steps=[
                {"name": "fail", "command": "false"},
            ],  # Command that always exits with error code 1
        )

        assert isinstance(job_id, str)
        # Job submission succeeds even if the command itself will fail


class TestMemoryStringParsing:
    """Test memory string parsing functionality."""

    @given(st.floats(min_value=0.1, max_value=1000.0))
    def test_parse_memory_string_handles_gb_units(self, value: float) -> None:
        """Memory strings with GB suffix are converted to bytes correctly."""
        submitter = JobSubmitter(queue_config={})

        result = submitter._parse_memory_string(f"{value}GB")
        expected = int(value * 1024 * 1024 * 1024)

        assert result == expected

    @given(st.floats(min_value=0.1, max_value=1000000.0))
    def test_parse_memory_string_handles_mb_units(self, value: float) -> None:
        """Memory strings with MB suffix are converted to bytes correctly."""
        submitter = JobSubmitter(queue_config={})

        result = submitter._parse_memory_string(f"{value}MB")
        expected = int(value * 1024 * 1024)

        assert result == expected

    @given(st.floats(min_value=0.1, max_value=1000000000.0))
    def test_parse_memory_string_handles_kb_units(self, value: float) -> None:
        """Memory strings with KB suffix are converted to bytes correctly."""
        submitter = JobSubmitter(queue_config={})

        result = submitter._parse_memory_string(f"{value}KB")
        expected = int(value * 1024)

        assert result == expected

    def test_parse_memory_string_handles_explicit_bytes(self) -> None:
        """Memory strings with B suffix are handled correctly."""
        submitter = JobSubmitter(queue_config={})

        assert submitter._parse_memory_string("512B") == 512
        assert submitter._parse_memory_string("1024B") == 1024

    def test_parse_memory_string_handles_bare_numbers(self) -> None:
        """Memory strings without suffix are treated as bytes."""
        submitter = JobSubmitter(queue_config={})

        assert submitter._parse_memory_string("1024") == 1024
        assert submitter._parse_memory_string("512") == 512

    def test_parse_memory_string_case_insensitive(self) -> None:
        """Memory parsing is case insensitive."""
        submitter = JobSubmitter(queue_config={})

        assert submitter._parse_memory_string("1gb") == 1024 * 1024 * 1024
        assert submitter._parse_memory_string("512mb") == 512 * 1024 * 1024
        assert submitter._parse_memory_string("1KB") == 1024

    def test_parse_memory_string_strips_whitespace(self) -> None:
        """Memory parsing handles whitespace correctly."""
        submitter = JobSubmitter(queue_config={})

        assert submitter._parse_memory_string(" 1GB ") == 1024 * 1024 * 1024
        assert submitter._parse_memory_string("\t512MB\n") == 512 * 1024 * 1024


class TestTimeStringParsing:
    """Test time string parsing functionality."""

    def test_parse_time_string_handles_hh_mm_ss_format(self) -> None:
        """Time strings in HH:MM:SS format are parsed correctly."""
        submitter = JobSubmitter(queue_config={})

        assert submitter._parse_time_string("01:30:45") == timedelta(
            hours=1,
            minutes=30,
            seconds=45,
        )
        assert submitter._parse_time_string("00:15:00") == timedelta(minutes=15)
        assert submitter._parse_time_string("02:00:00") == timedelta(hours=2)

    def test_parse_time_string_handles_minute_suffix(self) -> None:
        """Time strings with 'm' suffix are parsed as minutes."""
        submitter = JobSubmitter(queue_config={})

        assert submitter._parse_time_string("30m") == timedelta(minutes=30)
        assert submitter._parse_time_string("90m") == timedelta(minutes=90)

    def test_parse_time_string_handles_hour_suffix(self) -> None:
        """Time strings with 'h' suffix are parsed as hours."""
        submitter = JobSubmitter(queue_config={})

        assert submitter._parse_time_string("2h") == timedelta(hours=2)
        assert submitter._parse_time_string("0.5h") == timedelta(minutes=30)

    def test_parse_time_string_handles_second_suffix(self) -> None:
        """Time strings with 's' suffix are parsed as seconds."""
        submitter = JobSubmitter(queue_config={})

        assert submitter._parse_time_string("120s") == timedelta(seconds=120)
        assert submitter._parse_time_string("3600s") == timedelta(hours=1)

    @given(st.integers(min_value=1, max_value=3600))
    def test_parse_time_string_handles_bare_numbers_as_seconds(
        self,
        seconds: int,
    ) -> None:
        """Bare numbers are treated as seconds."""
        submitter = JobSubmitter(queue_config={})

        result = submitter._parse_time_string(str(seconds))
        expected = timedelta(seconds=seconds)

        assert result == expected

    def test_parse_time_string_with_invalid_format_raises_error(self) -> None:
        """Invalid time format raises ValueError with descriptive message."""
        submitter = JobSubmitter(queue_config={})

        with pytest.raises(ValueError, match=r"Invalid time format: 'invalid_time'"):
            submitter._parse_time_string("invalid_time")

    def test_parse_time_string_with_malformed_hms_raises_error(self) -> None:
        """Malformed HH:MM:SS format raises ValueError."""
        submitter = JobSubmitter(queue_config={})

        with pytest.raises(ValueError, match=r"Invalid time format"):
            submitter._parse_time_string("25:70:90")

    def test_parse_time_string_validates_hms_ranges(self) -> None:
        """HH:MM:SS format validates reasonable time ranges."""
        submitter = JobSubmitter(queue_config={})

        # Valid ranges should work
        submitter._parse_time_string("23:59:59")
        submitter._parse_time_string("00:00:00")

        # Invalid ranges should raise errors
        with pytest.raises(ValueError, match=r"Invalid time format"):
            submitter._parse_time_string("24:00:00")  # Hour too high

        with pytest.raises(ValueError, match=r"Invalid time format"):
            submitter._parse_time_string("12:60:30")  # Minutes too high

        with pytest.raises(ValueError, match=r"Invalid time format"):
            submitter._parse_time_string("12:30:60")  # Seconds too high


class TestQueueConfigTranslation:
    """Test translation from GERT queue_config to psij JobSpec."""

    def test_translate_minimal_config(self) -> None:
        """Minimal queue config translates to basic JobSpec."""
        submitter = JobSubmitter(queue_config={})

        spec = submitter._translate_to_psij_spec(
            execution_steps=[{"name": "test", "command": "echo test"}],
        )

        expected_spec = psij.JobSpec(
            executable="/bin/bash",
            arguments=["-c", "set -e\n(echo test)"],
            resources=psij.ResourceSpecV1(),
            attributes=psij.JobAttributes(),
            name=None,
        )

        assert spec == expected_spec

    def test_translate_uses_stored_queue_config(self) -> None:
        """Translation uses the queue config provided at initialization."""
        queue_config: Mapping[str, str | int] = {"cores": 16, "memory": "8GB"}
        submitter = JobSubmitter(queue_config=queue_config)

        spec = submitter._translate_to_psij_spec(
            execution_steps=[{"name": "test", "command": "test"}],
        )

        expected_resources = psij.ResourceSpecV1()
        expected_resources.process_count = 16
        expected_resources.memory = 8 * 1024 * 1024 * 1024

        expected_spec = psij.JobSpec(
            executable="/bin/bash",
            arguments=["-c", "set -e\n(test)"],
            resources=expected_resources,
            attributes=psij.JobAttributes(),
            name=None,
        )

        assert spec == expected_spec

    def test_translate_single_execution_step(self) -> None:
        """Single execution step creates simple script body."""
        submitter = JobSubmitter(queue_config={})

        spec = submitter._translate_to_psij_spec(
            execution_steps=[{"name": "single", "command": "single_command"}],
        )

        expected_spec = psij.JobSpec(
            executable="/bin/bash",
            arguments=["-c", "set -e\n(single_command)"],
            resources=psij.ResourceSpecV1(),
            attributes=psij.JobAttributes(),
            name=None,
        )

        assert spec == expected_spec

    def test_translate_multiple_execution_steps_chains_with_and(self) -> None:
        """Multiple execution steps are chained with newlines."""
        submitter = JobSubmitter(queue_config={})

        spec = submitter._translate_to_psij_spec(
            execution_steps=[
                {"name": "cmd1", "command": "cmd1"},
                {"name": "cmd2", "command": "cmd2"},
                {"name": "cmd3", "command": "cmd3"},
            ],
        )

        expected_spec = psij.JobSpec(
            executable="/bin/bash",
            arguments=["-c", "set -e\n(cmd1)\n(cmd2)\n(cmd3)"],
            resources=psij.ResourceSpecV1(),
            attributes=psij.JobAttributes(),
            name=None,
        )

        assert spec == expected_spec

    def test_translate_full_queue_config_maps_all_fields(self) -> None:
        """Full queue config properly maps all fields to JobSpec."""
        queue_config: Mapping[str, str | int] = {
            "cores": 8,
            "memory": "4GB",
            "wall_time": "02:30:00",
            "queue_name": "gpu",
            "project": "my_project",
            "job_name": "test_job",
        }
        submitter = JobSubmitter(queue_config=queue_config)

        spec = submitter._translate_to_psij_spec(
            execution_steps=[{"name": "test", "command": "test"}],
        )

        expected_resources = psij.ResourceSpecV1()
        expected_resources.process_count = 8
        expected_resources.memory = 4 * 1024 * 1024 * 1024

        expected_attributes = psij.JobAttributes()
        expected_attributes.duration = timedelta(hours=2, minutes=30)
        expected_attributes.queue_name = "gpu"
        expected_attributes.account = "my_project"

        expected_spec = psij.JobSpec(
            executable="/bin/bash",
            arguments=["-c", "set -e\n(test)"],
            resources=expected_resources,
            attributes=expected_attributes,
            name="test_job",
        )

        assert spec == expected_spec

    def test_translate_with_monitoring(self) -> None:
        """Monitoring URLs and redirection are correctly added to steps."""
        submitter = JobSubmitter(queue_config={})

        spec = submitter._translate_to_psij_spec(
            execution_steps=[{"name": "step1", "command": "cmd1"}],
            monitoring_url="http://api",
            experiment_id="exp1",
            execution_id="run1",
            iteration=0,
            realization_id=5,
        )

        expected_command = (
            "set -e\n"
            "gert_curl_retry() {\n"
            "  local url=$1\n"
            "  local max_retries=5\n"
            "  local delay=1\n"
            "  for i in $(seq 1 $max_retries); do\n"
            '    if curl -s -f -X POST "$url" >/dev/null; then\n'
            "      return 0\n"
            "    fi\n"
            "    sleep $delay\n"
            "    delay=$((delay * 2))\n"
            "  done\n"
            "  return 0\n"
            "}\n"
            "gert_curl_retry 'http://api/experiments/exp1/executions/run1/ensembles/0/realizations/5/status?status=RUNNING&step_name=step1'\n"
            "{ (cmd1) > step1.stdout 2> step1.stderr ; } || { gert_curl_retry 'http://api/experiments/exp1/executions/run1/ensembles/0/realizations/5/status?status=FAILED&step_name=step1'; exit 1; }\n"
            "gert_curl_retry 'http://api/experiments/exp1/executions/run1/ensembles/0/realizations/5/status?status=COMPLETED&step_name=step1'"
        )

        assert spec.arguments == ["-c", expected_command]
