import pytest
from pydantic import ValidationError

from gert.experiments import Template


def test_template_validation_valid_source() -> None:
    """Tests that a Template with just a source is valid."""
    template = Template(target="output.txt", source="input.txt")
    assert template.model_dump(mode="json", exclude_unset=True) == {
        "target": "output.txt",
        "source": "input.txt",
    }


def test_template_validation_valid_content() -> None:
    """Tests that a Template with just content is valid."""
    template = Template(target="output.txt", content="Hello {{ world }}")
    assert template.model_dump(mode="json", exclude_unset=True) == {
        "target": "output.txt",
        "content": "Hello {{ world }}",
    }


def test_template_validation_fails_with_both_source_and_content() -> None:
    """Tests that providing both source and content raises a validation error."""
    with pytest.raises(ValidationError) as exc_info:
        Template(
            target="output.txt",
            source="input.txt",
            content="Hello {{ world }}",
        )
    assert "Template must provide exactly one of 'source' or 'content'." in str(
        exc_info.value,
    )


def test_template_validation_fails_with_neither_source_nor_content() -> None:
    """Tests that providing neither source nor content raises a validation error."""
    with pytest.raises(ValidationError) as exc_info:
        Template(target="output.txt")
    assert "Template must provide exactly one of 'source' or 'content'." in str(
        exc_info.value,
    )
