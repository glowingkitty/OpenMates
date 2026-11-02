"""Minimum-Python source DTO import/field contract; no SDK/native dependencies."""

import ast
from pathlib import Path
import runpy
from typing import TypedDict


# contract-test: supporting surface=sdks.pip assertions=sdk.surface.semantic-parity
def test_project_source_required_and_optional_key_contract():
    # Import the actual module using only the stdlib so CI can execute this on
    # Python3.10 before installing the rest of the SDK or a native extension.
    types = runpy.run_path(
        str(Path(__file__).parents[1] / "openmates/project_sources.py")
    )
    required = frozenset(
        {
            "source_id",
            "source_type",
            "display_name",
            "metadata",
            "capabilities",
            "status",
            "created_at",
            "updated_at",
        }
    )
    create = types["SessionProjectSourceCreate"]
    result = types["SessionProjectSource"]
    patch = types["SessionProjectSourceCapabilitiesPatch"]
    assert create.__required_keys__ == required
    assert create.__optional_keys__ == frozenset({"last_indexed_at"})
    assert result.__required_keys__ == required | {"last_indexed_at"}
    assert result.__optional_keys__ == frozenset()
    assert patch.__required_keys__ == frozenset({"capabilities", "updated_at"})
    assert patch.__optional_keys__ == frozenset()


# contract-test: supporting surface=sdks.pip assertions=sdk.surface.semantic-parity
def test_actual_ai_model_defaults_optional_key_contract():
    # Execute the actual definition, including its postponed annotations, with
    # stdlib-only dependencies. This is not a duplicate fixture type definition.
    source = Path(__file__).parents[1] / "openmates/sdk.py"
    tree = ast.parse(source.read_text())
    definition = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "AiModelDefaults"
    )
    future = next(
        node
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module == "__future__"
    )
    namespace = {"__name__": "minimum_sdk_types", "TypedDict": TypedDict}
    exec(
        compile(
            ast.Module(body=[future, definition], type_ignores=[]),
            str(source),
            "exec",
            dont_inherit=True,
        ),
        namespace,
    )
    defaults = namespace["AiModelDefaults"]
    assert defaults.__required_keys__ == frozenset()
    assert defaults.__optional_keys__ == frozenset(
        {
            "default_ai_model_simple",
            "default_ai_model_complex",
            "default_ai_model_most_demanding",
        }
    )


if __name__ == "__main__":
    test_project_source_required_and_optional_key_contract()
    test_actual_ai_model_defaults_optional_key_contract()
