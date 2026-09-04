"""Synthetic coverage with expected files produced by the unmodified official JS."""

import json
from pathlib import Path

import pytest

from lanhu_codegen import CodeGenerationError, generate_design_files


FIXTURE = Path(__file__).parent / "fixtures" / "official_contract"


@pytest.fixture(scope="module")
def contract_export():
    schema = json.loads((FIXTURE / "schema.json").read_text(encoding="utf-8"))
    return generate_design_files(schema)


@pytest.mark.parametrize(
    "name",
    ["index.html", "index.css", "index.rem.css", "index.response.css", "common.css"],
)
def test_exact_official_contract(contract_export, name):
    assert contract_export[name].encode("utf-8") == (FIXTURE / "formatted" / name).read_bytes()


def test_loop_binding_does_not_execute_javascript():
    schema = json.loads((FIXTURE / "schema.json").read_text(encoding="utf-8"))
    text = schema["children"][0]["children"][0]["children"][0]
    # The original eval-based lookup would execute process.exit(97). The bridge
    # must reject the path before any schema-provided expression is evaluated.
    text["data"]["value"] = "this.item.content.label;process.exit(97)"
    with pytest.raises(CodeGenerationError, match="Unsupported DDS loop binding path"):
        generate_design_files(schema)
