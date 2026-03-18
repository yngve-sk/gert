from typing import Any
from unittest.mock import MagicMock

import pytest
from _pytest.monkeypatch import MonkeyPatch

from gert.plugins import (
    ForwardModelPlugin,
    GertRuntimePlugins,
    LifecycleHookPlugin,
    gert_plugin,
)


# Define concrete plugin classes for testing purposes. These must implement
# ALL abstract methods from their base classes to be instantiated correctly.
class _TestForwardModelPlugin(ForwardModelPlugin):
    def __init__(self, name: str) -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def get_consumed_parameters(self, arguments: dict[str, str]) -> list[str]:
        return ["param1", "param2"]

    def get_expected_responses(
        self,
        arguments: dict[str, Any],
        **kwargs: object,
    ) -> list[str]:
        return ["FOPR", "FWPR"]

    def build_command(self, arguments: dict[str, Any], **kwargs: object) -> str:
        return f"run_simulation --input {arguments.get('input_file', 'default.txt')}"


class _TestLifecycleHookPlugin(LifecycleHookPlugin):
    def __init__(self, name: str) -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def execute(self, arguments: dict[str, Any], **kwargs: object) -> None:
        # Simple test implementation - would normally do actual work
        print(f"Executing hook {self.name} with arguments: {arguments}")


# Advanced test plugins for edge cases
class _ParameterlessForwardModelPlugin(ForwardModelPlugin):
    """A plugin that consumes no parameters."""

    @property
    def name(self) -> str:
        return "parameterless_step"

    def get_consumed_parameters(self, arguments: dict[str, str]) -> list[str]:
        return []

    def get_expected_responses(
        self,
        arguments: dict[str, Any],
        **kwargs: object,
    ) -> list[str]:
        return ["STATIC_OUTPUT"]

    def build_command(self, arguments: dict[str, Any], **kwargs: object) -> str:
        return "echo 'static output'"


class _DynamicResponsePlugin(ForwardModelPlugin):
    """A plugin with responses that depend on arguments."""

    @property
    def name(self) -> str:
        return "dynamic_response"

    def get_consumed_parameters(self, arguments: dict[str, str]) -> list[str]:
        return ["wells", "timesteps"]

    def get_expected_responses(
        self,
        arguments: dict[str, Any],
        **kwargs: object,
    ) -> list[str]:
        # Response keys depend on configuration
        wells = arguments.get("wells")
        if isinstance(wells, list):
            return [f"{well}_RATE" for well in wells]
        return ["DEFAULT_RATE"]

    def build_command(self, arguments: dict[str, Any], **kwargs: object) -> str:
        return f"simulator --wells {','.join(arguments.get('wells', []))}"


class _ContextAwareHookPlugin(LifecycleHookPlugin):
    """A hook that uses kwargs for runtime context."""

    @property
    def name(self) -> str:
        return "context_aware_hook"

    def execute(self, arguments: dict[str, Any], **kwargs: object) -> None:
        # Access runtime context through kwargs
        experiment_id = kwargs.get("experiment_id", "unknown")
        iteration = kwargs.get("iteration", -1)
        print(f"Hook executing for experiment {experiment_id}, iteration {iteration}")


def test_gert_runtime_plugins_flattens_hook_results(monkeypatch: MonkeyPatch) -> None:
    """
    Tests that GertRuntimePlugins correctly calls the plugin manager's hooks
    and flattens the nested lists that are returned from concrete plugin instances.
    """
    # 1. Create a mock PluginManager.
    mock_pm = MagicMock()

    # 2. Define the raw, nested data we expect `pluggy` to return, using
    #    instances of our concrete implementation classes.
    mock_fm_steps_nested = [
        [_TestForwardModelPlugin(name="step1")],
        [
            _TestForwardModelPlugin(name="step2a"),
            _TestForwardModelPlugin(name="step2b"),
        ],
    ]
    mock_lc_hooks_nested = [
        [_TestLifecycleHookPlugin(name="hook1")],
        [_TestLifecycleHookPlugin(name="hook2")],
    ]

    # 3. Configure the mock hooks to return the nested list of plugin instances.
    mock_pm.hook.gert_forward_model_steps.return_value = mock_fm_steps_nested
    mock_pm.hook.gert_lifecycle_hooks.return_value = mock_lc_hooks_nested

    # 4. Patch `get_plugin_manager` within the correct module path.
    monkeypatch.setattr("gert.plugins.plugins.get_plugin_manager", lambda: mock_pm)

    # 5. Instantiate the class, which will use the mock plugin manager.
    runtime_plugins = GertRuntimePlugins()

    # 6. Assert that the final attributes have been correctly flattened.
    assert [p.name for p in runtime_plugins.forward_model_steps] == [
        "step1",
        "step2a",
        "step2b",
    ]

    assert [h.name for h in runtime_plugins.lifecycle_hooks] == ["hook1", "hook2"]

    # 7. Verify that the hook methods were called.
    mock_pm.hook.gert_forward_model_steps.assert_called_once()
    mock_pm.hook.gert_lifecycle_hooks.assert_called_once()


def test_forward_model_plugin_concrete_implementation() -> None:
    """Test that our concrete ForwardModelPlugin implementation works correctly."""
    plugin = _TestForwardModelPlugin(name="test_simulator")

    # Test all abstract method implementations
    assert plugin.name == "test_simulator"

    consumed_params = plugin.get_consumed_parameters({"config": "test.yml"})
    assert consumed_params == ["param1", "param2"]

    expected_responses = plugin.get_expected_responses({"output_keys": ["FOPR"]})
    assert expected_responses == ["FOPR", "FWPR"]

    command = plugin.build_command({"input_file": "simulation.dat"})
    assert command == "run_simulation --input simulation.dat"

    # Test with default arguments
    command_default = plugin.build_command({})
    assert command_default == "run_simulation --input default.txt"


def test_lifecycle_hook_plugin_concrete_implementation() -> None:
    """Test that our concrete LifecycleHookPlugin implementation works correctly."""
    hook = _TestLifecycleHookPlugin(name="pre_simulation_setup")

    # Test abstract method implementations
    assert hook.name == "pre_simulation_setup"

    # Test execute method - if it doesn't raise, the test passes
    hook.execute({"setup_dir": "./tmp/test", "config_file": "setup.yml"})


def test_empty_plugin_manager_returns_empty_lists(monkeypatch: MonkeyPatch) -> None:
    """Test that when no plugins are installed, empty lists are returned."""
    # Create a mock plugin manager that returns empty results
    mock_pm = MagicMock()
    mock_pm.hook.gert_forward_model_steps.return_value = []
    mock_pm.hook.gert_lifecycle_hooks.return_value = []

    monkeypatch.setattr("gert.plugins.plugins.get_plugin_manager", lambda: mock_pm)

    runtime_plugins = GertRuntimePlugins()

    assert runtime_plugins.forward_model_steps == []
    assert runtime_plugins.lifecycle_hooks == []


def test_plugin_manager_handles_none_return_values(monkeypatch: MonkeyPatch) -> None:
    """Test that the plugin manager gracefully handles None return values."""
    mock_pm = MagicMock()
    mock_pm.hook.gert_forward_model_steps.return_value = None
    mock_pm.hook.gert_lifecycle_hooks.return_value = None

    monkeypatch.setattr("gert.plugins.plugins.get_plugin_manager", lambda: mock_pm)

    runtime_plugins = GertRuntimePlugins()

    # Should handle None gracefully and return empty lists
    assert runtime_plugins.forward_model_steps == []
    assert runtime_plugins.lifecycle_hooks == []


def test_parameterless_forward_model_plugin() -> None:
    """Test a forward model plugin that consumes no parameters."""
    plugin = _ParameterlessForwardModelPlugin()

    assert plugin.name == "parameterless_step"
    assert plugin.get_consumed_parameters({}) == []
    assert plugin.get_expected_responses({}) == ["STATIC_OUTPUT"]
    assert plugin.build_command({}) == "echo 'static output'"


def test_dynamic_response_plugin() -> None:
    """Test a plugin where responses depend on arguments."""
    plugin = _DynamicResponsePlugin()

    # Test with wells specified
    args_with_wells = {"wells": ["PROD1", "PROD2", "INJ1"]}
    responses = plugin.get_expected_responses(args_with_wells)
    assert responses == ["PROD1_RATE", "PROD2_RATE", "INJ1_RATE"]

    # Test with empty wells
    args_empty_wells: dict[str, list[str]] = {"wells": []}
    responses_empty = plugin.get_expected_responses(args_empty_wells)
    assert responses_empty == []

    # Test with no wells argument
    responses_default = plugin.get_expected_responses({})
    assert responses_default == ["DEFAULT_RATE"]


def test_context_aware_hook_plugin() -> None:
    """Test a hook that uses runtime context from kwargs."""
    hook = _ContextAwareHookPlugin()

    assert hook.name == "context_aware_hook"

    # Test with runtime context - if it doesn't raise, the test passes
    hook.execute(
        {"config": "test.yml"},
        experiment_id="exp_001",
        iteration=5,
    )


def test_plugin_with_complex_arguments() -> None:
    """Test plugins handling complex argument structures."""
    plugin = _TestForwardModelPlugin(name="complex_args")

    # Test with nested arguments
    complex_args = {
        "input_file": "simulation.dat",
        "config": {
            "solver": "newton",
            "timesteps": [1, 5, 10, 20],
        },
    }

    # Should handle complex arguments gracefully
    command = plugin.build_command(complex_args)
    assert "simulation.dat" in command


def test_plugin_marker_exists() -> None:
    """Test that the gert_plugin marker is available for plugin developers."""
    # The marker should exist and be callable
    assert callable(gert_plugin)

    # Test that it can be used as a decorator
    @gert_plugin
    def dummy_hook_impl() -> list[ForwardModelPlugin]:
        return [_TestForwardModelPlugin(name="marked_plugin")]

    # The decorator should return the function unchanged
    assert callable(dummy_hook_impl)
    result = dummy_hook_impl()
    assert [r.name for r in result] == ["marked_plugin"]


def test_multiple_nested_plugin_levels(monkeypatch: MonkeyPatch) -> None:
    """Test deeply nested plugin results are properly flattened."""
    mock_pm = MagicMock()

    # Create deeply nested structure (plugin discovery could return this)
    deeply_nested = [
        [  # First plugin package
            [_TestForwardModelPlugin(name="pkg1_step1")],
            [_TestForwardModelPlugin(name="pkg1_step2")],
        ],
        [  # Second plugin package
            [_TestForwardModelPlugin(name="pkg2_step1")],
        ],
        [],  # Empty package
    ]

    # Flatten once (what pluggy might return)
    mock_pm.hook.gert_forward_model_steps.return_value = [
        item for sublist in deeply_nested for item in sublist
    ]
    mock_pm.hook.gert_lifecycle_hooks.return_value = []

    monkeypatch.setattr("gert.plugins.plugins.get_plugin_manager", lambda: mock_pm)

    runtime_plugins = GertRuntimePlugins()

    # Should flatten correctly
    names = [p.name for p in runtime_plugins.forward_model_steps]
    assert names == ["pkg1_step1", "pkg1_step2", "pkg2_step1"]


def test_mixed_empty_and_populated_plugin_results(monkeypatch: MonkeyPatch) -> None:
    """Test handling of mixed empty and populated plugin results."""
    mock_pm = MagicMock()

    # Mix of empty and populated results
    mock_fm_mixed = [
        [],  # Empty result from one plugin
        [_TestForwardModelPlugin(name="active_step1")],
        [],  # Another empty result
        [
            _TestForwardModelPlugin(name="active_step2"),
            _TestForwardModelPlugin(name="active_step3"),
        ],
        [],  # Final empty result
    ]

    mock_pm.hook.gert_forward_model_steps.return_value = mock_fm_mixed
    mock_pm.hook.gert_lifecycle_hooks.return_value = [
        [],  # Empty hook result
        [_TestLifecycleHookPlugin(name="active_hook")],
    ]

    monkeypatch.setattr("gert.plugins.plugins.get_plugin_manager", lambda: mock_pm)

    runtime_plugins = GertRuntimePlugins()

    # Should only include non-empty results
    assert [p.name for p in runtime_plugins.forward_model_steps] == [
        "active_step1",
        "active_step2",
        "active_step3",
    ]

    assert [h.name for h in runtime_plugins.lifecycle_hooks] == ["active_hook"]


def test_plugin_error_handling_in_methods() -> None:
    """Test that plugin methods can handle errors gracefully."""

    class _ErrorPronePlugin(ForwardModelPlugin):
        @property
        def name(self) -> str:
            return "error_prone"

        def get_consumed_parameters(self, arguments: dict[str, str]) -> list[str]:
            # Could raise if arguments are malformed
            if "error" in arguments:
                msg = "Simulated error"
                raise ValueError(msg)
            return ["param1"]

        def get_expected_responses(
            self,
            arguments: dict[str, Any],
            **kwargs: object,
        ) -> list[str]:
            return ["response1"]

        def build_command(self, arguments: dict[str, Any], **kwargs: object) -> str:
            return "echo test"

    plugin = _ErrorPronePlugin()

    # Normal operation should work
    assert plugin.get_consumed_parameters({}) == ["param1"]

    # Error case should raise
    with pytest.raises(ValueError, match="Simulated error"):
        plugin.get_consumed_parameters({"error": "trigger"})
