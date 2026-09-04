"""Source label envelopes retain section headings within a matrix panel."""
from copy import deepcopy

import pytest

from lanhu_codegen.figma_dds_layout import infer_dds_layout
from tests.test_figma_dds_layout import by_id, node, page, painted, style, text, walk


@pytest.mark.parametrize("full_width", [True, False])
@pytest.mark.parametrize("scale", [1, 2])
def test_wide_transparent_source_label_envelope_avoids_an_extra_single_text_row(full_width, scale):
    heading = text("section-caption", 10, 20, 42, 22)
    source = page(painted("panel", 0, 0, 240, 160, children=[
        node("caption-envelope", 10, 20, 220 if full_width else 42, 22, children=[heading]),
        painted("cell-a", 10, 60, 110, 32, children=[text("a", 15, 65, 30, 22)]),
        painted("cell-b", 120, 60, 110, 32, children=[text("b", 125, 65, 30, 22)]),
    ]), width=300, height=200)
    for current in walk(source):
        current["rowDims"] = {key: value * scale for key, value in current["rowDims"].items()}
        current["props"]["style"].update(width=current["rowDims"]["width"], height=current["rowDims"]["height"])
    before = deepcopy(source)
    actual = infer_dds_layout(source)
    result = by_id(actual, "section-caption")
    parent = next(n for n in walk(actual) if any(c is result for c in n.get("children", [])))
    assert source == before and result["rowDims"] == by_id(source, "section-caption")["rowDims"]
    if full_width:
        assert parent["layerId"] == "panel"
        assert style(result)["width"] == 42 * scale
    else:
        assert parent["layerId"] != "panel" and parent["children"] == [result]
        assert style(parent)["flexDirection"] == "row"


@pytest.mark.parametrize("content_column", [False, True])
def test_decorative_leaf_beside_synthetic_form_column_does_not_make_a_matrix(content_column):
    marker = painted("side", 126, 10, 4, 56,
                     children=[text("side-content", 127, 15, 2, 16)] if content_column else [])
    source = page(painted("form", 0, 0, 170, 170, children=[
        painted("field-a", 10, 10, 110, 24),
        painted("field-b", 10, 42, 110, 24),
        marker,
        text("field-label", 10, 88, 60, 22),
        painted("field-c", 10, 118, 140, 24),
    ]), width=200, height=200)
    before = deepcopy(source)
    actual = infer_dds_layout(source)
    label = by_id(actual, "field-label")
    parent = next(n for n in walk(actual) if any(c is label for c in n.get("children", [])))
    assert source == before and label["rowDims"] == by_id(source, "field-label")["rowDims"]
    assert (parent["layerId"] != "form") is content_column
