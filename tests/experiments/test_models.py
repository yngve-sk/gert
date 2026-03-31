import operator
from pathlib import Path

import polars as pl
import pytest
from pydantic import ValidationError

from gert.experiments import Template
from gert.experiments.models import (
    FileReference,
    ParameterDataset,
    ParameterMatrix,
)


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


class TestParameterMatrix:
    def test_parameter_matrix_to_df(self, tmp_path: Path) -> None:
        # 1. Create a scalar dataset
        scalar_df = pl.DataFrame(
            {
                "realization": [0, 1, 2],
                "PORO": [0.1, 0.2, 0.3],
            },
        )
        scalar_path = tmp_path / "scalar.parquet"
        scalar_df.write_parquet(scalar_path)

        # 2. Create a field/surface dataset
        field_df = pl.DataFrame(
            {
                "realization": [0, 0, 1, 1, 2, 2],
                "i": [0, 1, 0, 1, 0, 1],
                "PERM": [10.0, 15.0, 20.0, 25.0, 30.0, 35.0],
            },
        )
        field_path = tmp_path / "field.parquet"
        field_df.write_parquet(field_path)

        # 3. Create a ParameterMatrix with inline values and the datasets
        pm = ParameterMatrix(
            values={
                "MULTFLT": {0: 1.0, 1: 1.1},  # 2 is missing, should become null
            },
            datasets=[
                ParameterDataset(
                    reference=FileReference(path=str(scalar_path)),
                    parameters=["PORO"],
                ),
                ParameterDataset(
                    reference=FileReference(path=str(field_path)),
                    parameters=["PERM"],
                    index_columns=["i"],
                ),
            ],
        )
        df = pm.to_df(base_working_directory=tmp_path)

        # Validate the results
        assert len(df) == 3
        assert set(df.columns) == {
            "realization",
            "MULTFLT",
            "PORO",
            "PERM",
        }

        # Validate specific rows
        # realization 0
        r0 = df.filter(pl.col("realization") == 0).to_dicts()[0]
        assert r0["MULTFLT"] == 1.0
        assert r0["PORO"] == 0.1
        # List of values for PERM
        assert list(r0["PERM"]) == [10.0, 15.0]

        # realization 1
        r1 = df.filter(pl.col("realization") == 1).to_dicts()[0]
        assert r1["MULTFLT"] == 1.1
        assert r1["PORO"] == 0.2
        assert list(r1["PERM"]) == [20.0, 25.0]

        # realization 2
        r2 = df.filter(pl.col("realization") == 2).to_dicts()[0]
        assert r2["MULTFLT"] is None  # Since it wasn't in the inline values
        assert r2["PORO"] == 0.3
        assert list(r2["PERM"]) == [30.0, 35.0]

    def test_parameter_matrix_with_dataframe_field(self) -> None:
        df = pl.DataFrame(
            {
                "realization": [0, 1],
                "FOO": [1.0, 2.0],
            },
        )
        pm = ParameterMatrix(dataframe=df)

        # Because it uses the existing DataFrame directly, to_df should return it exactly
        res_df = pm.to_df()
        assert res_df.equals(df)

        reals = pm.get_realizations()
        assert reals == {0, 1}

    def test_parameter_matrix_to_df_simple(self) -> None:
        """Test conversion from ParameterMatrix to wide DataFrame."""
        pm = ParameterMatrix(
            values={
                "MULTFLT": {0: 1.0, 1: 2.0},
                "PORO": {0: 0.1, 1: 0.2, 2: 0.3},
            },
        )
        df = pm.to_df()

        expected_dicts = [
            {"realization": 0, "MULTFLT": 1.0, "PORO": 0.1},
            {"realization": 1, "MULTFLT": 2.0, "PORO": 0.2},
            {"realization": 2, "MULTFLT": None, "PORO": 0.3},
        ]

        df = df.select(["realization", "MULTFLT", "PORO"])

        # We don't guarantee row order
        actual_dicts = sorted(df.to_dicts(), key=operator.itemgetter("realization"))
        assert actual_dicts == expected_dicts
