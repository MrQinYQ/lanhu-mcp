"""DDS subpixel radii and wrapping, with source-mode preservation checks."""
from copy import deepcopy

import pytest

from lanhu_codegen import generate_design_files
from lanhu_codegen.figma_schema import figma_to_dds_schema
from tests.test_figma_regressions import document, find, layer, text_layer


@pytest.mark.parametrize("radius,expected", [(0.25, None), (0.75, None), (2.75, "2px"), (4, "4px")])
def test_dds_corner_quantization_does_not_change_source_modes(radius, expected):
    box = layer("paint", (10, 20, 24, 36), kind="artboard", paint=(1, 0, 0))
    box["paths"] = [{"type": "rect", "frame": deepcopy(box["frame"]),
                     "radius": dict.fromkeys(("topLeft", "topRight", "bottomRight", "bottomLeft"), radius)}]
    raw = document(box)
    before = deepcopy(raw)
    actual = figma_to_dds_schema(raw)
    assert find(actual, "paint")["props"]["style"].get("borderRadius") == expected
    for options in ({"border_layout": "source"}, {"layout": "absolute"}):
        source = find(figma_to_dds_schema(raw, **options), "paint")
        assert set(source["props"]["style"]["borderRadius"].split()) == {f"{radius:g}px"}
    assert raw == before


def test_whitespace_free_wrapped_text_uses_normal_wrapping_only_in_dds_mode():
    raw = document(text_layer("wrapped", "任意说明文字可以自动换行", (10, 20, 80, 40)))
    before = deepcopy(raw)
    actual = figma_to_dds_schema(raw)
    node = find(actual, "wrapped")
    assert "whiteSpace" not in node["props"]["style"]
    assert node["props"]["style"]["lineHeight"] == 20
    assert node["props"]["text"] == "任意说明文字可以自动换行"
    assert "white-space:" not in generate_design_files(actual)["index.css"]
    for options in ({"border_layout": "source"}, {"layout": "absolute"}):
        assert find(figma_to_dds_schema(raw, **options), "wrapped")["props"]["style"]["whiteSpace"] == "pre-wrap"
    assert raw == before


@pytest.mark.parametrize("content", ["alpha beta", "前后 空格", " 两端 ", "双  空格", "换\n行", "制\t表"])
def test_layout_significant_whitespace_keeps_pre_wrap(content):
    actual = figma_to_dds_schema(document(text_layer("wrapped", content, (10, 20, 80, 40))))
    assert find(actual, "wrapped")["props"]["style"]["whiteSpace"] == "pre-wrap"


def test_single_line_text_keeps_nowrap():
    actual = figma_to_dds_schema(document(text_layer("single", "单行文字", (10, 20, 80, 20))))
    assert find(actual, "single")["props"]["style"]["whiteSpace"] == "nowrap"


@pytest.mark.parametrize("size,height,expected", [(10, 19, "nowrap"), (10, 20, None), (18, 36, None)])
def test_explicit_tall_line_box_uses_font_envelope_for_dds_wrapping(size, height, expected):
    text = text_layer("tall-label", "RenamedCaption", (10, 20, 240, height))
    font = text["text"]["style"]["font"]
    font.update(size=size, lineHeight={"unit": "PIXELS", "value": height})
    raw = document(text)
    before = deepcopy(raw)
    result = find(figma_to_dds_schema(raw), "tall-label")
    assert result["props"]["style"].get("whiteSpace") == expected
    assert result["props"]["style"]["lineHeight"] == height
    assert result["props"]["text"] == "RenamedCaption"
    assert find(figma_to_dds_schema(raw, border_layout="source"), "tall-label")["props"]["style"]["whiteSpace"] == "nowrap"
    assert find(figma_to_dds_schema(raw, layout="absolute"), "tall-label")["props"]["style"]["whiteSpace"] == "pre-wrap"
    assert raw == before


def test_tall_line_box_still_preserves_significant_spaces():
    text = text_layer("tall-spaces", "alpha  beta", (10, 20, 240, 32))
    text["text"]["style"]["font"]["lineHeight"] = {"unit": "PIXELS", "value": 32}
    result = find(figma_to_dds_schema(document(text)), "tall-spaces")
    assert result["props"]["style"]["whiteSpace"] == "pre-wrap"
    assert result["props"]["text"] == "alpha&#32;&#32;beta"
