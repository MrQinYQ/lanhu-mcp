"""DDS single tall-line whitespace must not change ordinary multiline text."""

from copy import deepcopy

import pytest

from lanhu_codegen import generate_design_files
from lanhu_codegen.figma_schema import figma_to_dds_schema
from tests.test_figma_regressions import ParsedHTML, css_rule, document, find, text_layer


def raw_text(content, *, size=12, height=24, line_height=24):
    node = text_layer("arbitrary-caption", content, (17, 23, 250, height))
    node["text"]["style"]["font"].update(size=size, lineHeight={"unit": "PIXELS", "value": line_height})
    return document(node)


@pytest.mark.parametrize("content,size,height", [
    ("Example 标签", 12, 24), ("完全不同的 文案", 18, 36), ("alpha beta gamma", 10, 30),
])
def test_one_explicit_tall_line_box_retains_dds_nbsp_without_white_space(content, size, height):
    raw = raw_text(content, size=size, height=height, line_height=height)
    before = deepcopy(raw)
    schema = figma_to_dds_schema(raw)
    node = find(schema, "arbitrary-caption")
    assert node["props"]["text"] == content.replace(" ", "&nbsp;")
    assert node["data"]["value"] == node["props"]["text"]
    assert "whiteSpace" not in node["props"]["style"]
    assert node["props"]["style"]["lineHeight"] == height
    files = generate_design_files(schema)
    decoded = ParsedHTML(files["index.html"]).by_class(node["props"]["className"])["text"]
    assert decoded == content.replace(" ", "\u00a0")
    assert "white-space" not in css_rule(files, node)
    assert raw == before


@pytest.mark.parametrize("content", ["alpha  beta", " 前后", "前后 ", " 前后 ",
                                      "alpha\tbeta", "alpha\nbeta", "alpha\r\nbeta", "alpha\u2003beta"])
def test_tall_line_box_preserves_repeated_edge_and_control_whitespace(content):
    schema = figma_to_dds_schema(raw_text(content))
    node = find(schema, "arbitrary-caption")
    assert node["props"]["style"]["whiteSpace"] == "pre-wrap"
    assert "&nbsp;" not in node["props"]["text"]
    files = generate_design_files(schema)
    decoded = ParsedHTML(files["index.html"]).by_class(node["props"]["className"])["text"]
    assert decoded == content.replace("\r\n", "\n")
    assert css_rule(files, node)["white-space"].strip() == "pre-wrap"


@pytest.mark.parametrize("height,line_height", [(48, 24), (36, 24), (24, 25)])
def test_tall_font_envelope_alone_is_not_evidence_of_a_single_line(height, line_height):
    schema = figma_to_dds_schema(raw_text("alpha beta", height=height, line_height=line_height))
    node = find(schema, "arbitrary-caption")
    assert node["props"]["style"]["whiteSpace"] == "pre-wrap"
    assert node["props"]["text"] == "alpha&#32;beta"


def test_normal_height_single_line_still_has_nowrap():
    node = find(figma_to_dds_schema(raw_text("alpha beta", height=20, line_height=20)), "arbitrary-caption")
    assert node["props"]["style"]["whiteSpace"] == "nowrap"
    assert node["props"]["text"] == "alpha&nbsp;beta"


@pytest.mark.parametrize("options,expected_space,expected_text", [
    ({"layout": "absolute"}, "pre-wrap", "alpha&#32;beta"),
    ({"border_layout": "source"}, "nowrap", "alpha&nbsp;beta"),
])
def test_source_modes_retain_their_previous_whitespace_contract(options, expected_space, expected_text):
    raw = raw_text("alpha beta")
    before = deepcopy(raw)
    node = find(figma_to_dds_schema(raw, **options), "arbitrary-caption")
    assert node["props"]["style"]["whiteSpace"] == expected_space
    assert node["props"]["text"] == expected_text
    assert raw == before
