"""A raster body still occupies a canvas row below repeated title panels."""
from copy import deepcopy

import pytest

from lanhu_codegen.figma_dds_layout import infer_dds_layout
from tests.test_figma_dds_layout import by_id, image, page, painted, style, text, walk


@pytest.mark.parametrize("header", ["equal-columns", "single", "unequal-columns"])
@pytest.mark.parametrize("scale", [1, 2])
def test_single_raster_body_row_requires_equal_text_panel_columns(header, scale):
    headings = [painted("heading-a", 0, 0, 100, 20,
                        children=[text("caption-a", 10, 2, 70, 14)])]
    if header != "single":
        headings.append(painted("heading-b", 120, 0, 100 if header == "equal-columns" else 90, 20,
                                children=[text("caption-b", 130, 2, 70, 14)]))
    source = page(*headings, image("raster-body", 15, 50, 70, 90), width=240, height=180)
    for n in walk(source):
        n["rowDims"] = {key: value * scale for key, value in n["rowDims"].items()}
        n["props"]["style"].update(width=n["rowDims"]["width"], height=n["rowDims"]["height"])
    before = deepcopy(source)
    actual = infer_dds_layout(source)
    assert source == before
    body = by_id(actual, "raster-body")
    assert body["rowDims"] == by_id(source, "raster-body")["rowDims"]
    assert body["props"]["src"] == by_id(source, "raster-body")["props"]["src"]
    parent = next(n for n in walk(actual) if any(c is body for c in n.get("children", [])))
    if header == "equal-columns":
        assert parent is not actual and parent["children"] == [body]
        assert parent["rowDims"] == body["rowDims"]
        assert style(parent)["flexDirection"] == "row"
        assert "position" not in style(body)
    else:
        assert parent is actual
