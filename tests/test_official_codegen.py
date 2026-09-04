"""The expected files were copied from Lanhu's UI, not produced by our code."""

import copy
import json
from pathlib import Path

import pytest

from lanhu_codegen import CodeGenerationError, convert_lanhu_to_html, generate_design_files, inline_design_files


FIXTURE = Path(__file__).parent / "fixtures" / "official_no_permission"


@pytest.fixture(scope="module")
def official_export():
    schema = json.loads((FIXTURE / "schema.json").read_text())
    before = copy.deepcopy(schema)
    files = generate_design_files(schema)
    assert schema == before
    return files


@pytest.mark.parametrize("name", ["index.html", "index.css", "common.css"])
def test_exact_official_export(official_export, name):
    # No whitespace, color, class-name or URL normalization is permitted.
    assert official_export[name].encode("utf-8") == (FIXTURE / name).read_bytes()


def test_public_converter_returns_official_html():
    schema = json.loads((FIXTURE / "schema.json").read_text())
    assert convert_lanhu_to_html(schema).encode("utf-8") == (FIXTURE / "index.html").read_bytes()


def test_inline_preview_preserves_official_body_and_styles(official_export):
    preview = inline_design_files(official_export)
    assert preview.split("<body>", 1)[1] == official_export["index.html"].split("<body>", 1)[1]
    assert preview.index(official_export["common.css"]) < preview.index(official_export["index.css"])
    assert 'href="./common.css"' not in preview
    assert 'href="./index.css"' not in preview
    assert official_export["index.rem.css"]
    assert official_export["index.response.css"]


def test_missing_node_is_actionable(monkeypatch):
    monkeypatch.delenv("LANHU_NODE_BINARY", raising=False)
    monkeypatch.setattr("lanhu_codegen.shutil.which", lambda _: None)
    with pytest.raises(CodeGenerationError, match="Node.js is required"):
        generate_design_files({"type": "lanhupage"})


@pytest.mark.parametrize("schema", [None, [], {}, "not a schema"])
def test_invalid_input_rejected(schema):
    with pytest.raises(CodeGenerationError, match="non-empty object"):
        generate_design_files(schema)


def test_raw_figma_json_is_not_silently_treated_as_dds():
    with pytest.raises(CodeGenerationError, match="not a DDS schema"):
        generate_design_files({"meta": {}, "artboard": {"layers": []}})
