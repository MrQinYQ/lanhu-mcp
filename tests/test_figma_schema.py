"""Source-geometry and rejection contracts for the raw-Figma adapter.

Absolute mode retains original fractional frames; inferred DDS integration has
its own paired-export tests. Both modes share paint/resource validation.
"""

from copy import deepcopy
from functools import partial
import json
from pathlib import Path

import pytest

from lanhu_codegen import generate_design_files
from lanhu_codegen.figma_schema import UnsupportedFigmaFeature, figma_to_dds_schema

convert_absolute = partial(figma_to_dds_schema, layout="absolute")


FIXTURE = Path(__file__).parent / "fixtures" / "figma_no_permission"


def layer(layer_id, *, kind="artboard", name=None, left=0, top=0, width=100, height=80, children=None):
    return {
        "id": layer_id, "name": name or layer_id, "type": kind, "origin": "figma",
        "frame": {"left": left, "top": top, "width": width, "height": height},
        "visible": True, "opacity": 1, "style": {"opacity": 1, "fills": [], "borders": [], "shadows": [], "blurs": []},
        "layers": children or [],
    }


def document(*children):
    return {"meta": {"host": {"name": "figma"}, "device": "Web @2x"}, "assets": [],
            "artboard": layer("root", left=2000, top=-300, width=1640, height=2298, children=list(children))}


def text_layer(content="Hello", **kwargs):
    result = layer("text", kind="textLayer", **kwargs)
    result["text"] = {"value": content, "style": {
        "font": {"name": "PingFang SC", "size": 16, "fontWeight": 400,
                 "lineHeight": {"unit": "PIXELS", "value": 24}, "letterSpacing": {"unit": "percent", "value": 0}},
        "color": {"r": 1, "g": 0, "b": 0, "a": 1},
    }}
    return result


def nodes(schema):
    yield schema
    for child in schema["children"]:
        yield from nodes(child)


def test_nested_frames_are_local_and_input_is_unchanged():
    inner = text_layer(left=125, top=215)
    raw = document(layer("group", left=100, top=200, children=[inner]), layer("sibling", left=300))
    before = deepcopy(raw)
    schema = convert_absolute(raw)
    assert raw == before
    assert schema["rowDims"] == {"left": 0, "top": 0, "width": 1640, "height": 2298}
    assert schema["props"]["style"]["width"] == 1640  # Web @2x is not divided again.
    outer, sibling = schema["children"]
    assert outer["props"]["style"]["left"] == 100
    assert outer["children"][0]["props"]["style"]["left"] == 25
    assert outer["children"][0]["props"]["style"]["top"] == 15
    assert outer["children"][0]["rowDims"]["left"] == 125
    assert outer["props"]["style"]["zIndex"] < sibling["props"]["style"]["zIndex"]


def test_dds_export_is_preferred_and_its_subtree_is_not_rendered_twice():
    vector = layer("vector", kind="shapeLayer", name="Vector")
    exported = layer("icon", children=[vector])
    exported.update(hasExportDDSImage=True, ddsImage={"imageUrl": "https://example.com/dds.png"},
                    hasExportImage=True, image={"imageUrl": "https://example.com/normal.png"}, rotation=180)
    exported["style"]["shadows"] = [{"isEnabled": True}]
    converted = convert_absolute(document(exported))["children"][0]
    assert converted["type"] == "lanhuimage"
    assert converted["props"]["src"] == "https://example.com/dds.png"
    assert converted["children"] == []
    assert "transform" not in converted["props"]["style"]
    assert "boxShadow" not in converted["props"]["style"]


def test_regular_export_can_supply_complex_shape_pixels():
    vector = layer("vector", kind="shapeLayer", name="Vector")
    vector.update(hasExportImage=True, image={"svgUrl": "https://example.com/vector.svg"})
    assert convert_absolute(document(vector))["children"][0]["props"]["src"].endswith("vector.svg")


def test_missing_vector_reports_identity_and_does_not_modify_input():
    vector = layer("253:37568", kind="shapeLayer", name="形状结合")
    vector["paths"] = [{"type": "rect", "frame": vector["frame"]}]
    raw = document(vector)
    before = deepcopy(raw)
    with pytest.raises(UnsupportedFigmaFeature, match="missing vector geometry") as error:
        convert_absolute(raw)
    assert error.value.layer_id == "253:37568"
    assert error.value.layer_name == "形状结合"
    assert raw == before


def test_missing_marked_export_is_not_silently_ignored():
    bad = layer("missing-resource")
    bad["hasExportDDSImage"] = True
    with pytest.raises(UnsupportedFigmaFeature, match="without ddsImage resource"):
        convert_absolute(document(bad))


def test_invisible_unsupported_layer_has_no_visual_effect():
    vector = layer("hidden", kind="shapeLayer", name="Vector")
    vector["visible"] = False
    assert convert_absolute(document(vector))["children"] == []


def test_solid_paint_duplicate_opacity_and_path_radius():
    block = layer("block")
    block["opacity"] = block["style"]["opacity"] = 0.5
    block["style"]["fills"] = [{"type": "color", "opacity": 0.1,
                                 "color": {"r": 1, "g": 1, "b": 1, "a": 0.1}}]
    block["radius"] = {"topLeft": 0, "topRight": 0, "bottomLeft": 0, "bottomRight": 0}
    block["paths"] = [{"type": "rect", "radius": {"topLeft": 32, "topRight": 16, "bottomRight": 8, "bottomLeft": 4}}]
    style = convert_absolute(document(block))["children"][0]["props"]["style"]
    assert style["opacity"] == 0.5
    assert style["backgroundColor"] == "rgba(255, 255, 255, 0.1)"
    assert style["borderRadius"] == "32px 16px 8px 4px"


@pytest.mark.parametrize("sides,expected", [
    ({"top": 0, "right": 0, "bottom": 1, "left": 0}, {"borderBottom": "1px solid rgba(0, 0, 0, 1)"}),
    ({"top": 0, "right": 0, "bottom": 0, "left": 0},
     {f"border{side}": "2px solid rgba(0, 0, 0, 1)" for side in ("Top", "Right", "Bottom", "Left")}),
])
def test_border_width_and_per_side_widths(sides, expected):
    block = layer("block", children=[layer("child", left=10, top=12)])
    block["style"]["borders"] = [{"width": 2, "widths": sides, "lineAlignment": "inside",
                                  "style": "solid", "color": {"r": 0, "g": 0, "b": 0, "a": 1}}]
    converted = convert_absolute(document(block))["children"][0]
    style = converted["props"]["style"]
    assert {key: value for key, value in style.items() if key.startswith("border")} == expected
    # Inside borders participate in the CSS containing block. Compensate once.
    assert converted["children"][0]["props"]["style"]["left"] == (8 if "borderLeft" in expected else 10)


@pytest.mark.parametrize("key,value,feature", [
    ("fills", [{"type": "gradient"}], "fill type"),
    ("shadows", [{"isEnabled": True}], "shadows"),
    ("blurs", [{"isEnabled": True}], "blurs"),
    ("blendMode", 3, "blend mode"),
])
def test_unsupported_active_appearance_is_explicit(key, value, feature):
    block = layer("effect")
    block["style"][key] = value
    with pytest.raises(UnsupportedFigmaFeature, match=feature):
        convert_absolute(document(block))


def test_mixed_rich_text_is_not_flattened():
    text = text_layer("Hello")
    first = dict(deepcopy(text["text"]["style"]), content="He", **{"from": 0, "to": 2})
    second = dict(deepcopy(text["text"]["style"]), content="llo", **{"from": 2, "to": 5})
    second["font"]["fontWeight"] = 700
    text["text"]["styles"] = [first, second]
    with pytest.raises(UnsupportedFigmaFeature, match="mixed rich-text styles"):
        convert_absolute(document(text))


def test_text_content_is_literal_in_official_html():
    content = '<b>x</b> & {{this.item.name}}\nnext'
    schema = convert_absolute(document(text_layer(content)))
    assert schema["children"][0]["data"]["value"] == content
    files = generate_design_files(schema)
    from bs4 import BeautifulSoup
    page = BeautifulSoup(files["index.html"], "html.parser")
    assert page.span.get_text() == content
    assert not page.find("b")
    assert "{{this.item.name}}" not in files["index.html"]
    assert "white-space: pre-wrap" in files["index.css"]


def test_fractional_geometry_uses_single_logical_css_properties():
    schema = convert_absolute(document(layer("fraction", left=1.5, top=2.25, width=20.5, height=10.75)))
    style = schema["children"][0]["props"]["style"]
    assert "left" not in style and style["insetInlineStart"] == "1.5px"
    assert "top" not in style and style["insetBlockStart"] == "2.25px"
    assert "width" not in style and style["inlineSize"] == "20.5px"
    assert "height" not in style and style["blockSize"] == "10.75px"
    assert schema["children"][0]["rowDims"]["width"] == 20.5
    assert "inline-size: 20.5px" in generate_design_files(schema)["index.css"]


def test_whole_artboard_bitmap_is_not_used_as_a_structural_fallback():
    raw = document()
    raw["artboard"].update(hasExportImage=True, image={"imageUrl": "https://example.com/page.png"})
    with pytest.raises(UnsupportedFigmaFeature, match="artboard-only image export"):
        convert_absolute(raw)


def test_v5_example_preserves_text_geometry_and_real_exports():
    raw = json.loads((FIXTURE / "v5.json").read_text())
    before = deepcopy(raw)
    schema = convert_absolute(raw)
    assert raw == before
    all_nodes = list(nodes(schema))
    assert schema["props"]["style"]["width"] == 1640
    assert schema["props"]["style"]["height"] == 2298
    texts = [node for node in all_nodes if node["type"] == "lanhutext"]
    assert len(texts) == 8
    assert next(node for node in texts if node["data"]["value"] == "暂无权限")["props"]["style"]["fontSize"] == 32
    images = [node for node in all_nodes if node["type"] == "lanhuimage"]
    assert len(images) == 15
    assert all(image["props"]["src"] in json.dumps(raw) for image in images)
    assert all(not image["children"] for image in images)
    files = generate_design_files(schema)
    assert files["index.html"].count("<img") == 15
    assert "暂无权限" in files["index.html"]
    assert "design.png" not in files["index.html"]


def test_user_supplied_v4_lacks_required_export_resources():
    raw = json.loads((FIXTURE / "v4.json").read_text())
    with pytest.raises(UnsupportedFigmaFeature, match="missing vector geometry") as error:
        convert_absolute(raw)
    assert error.value.layer_id == "253:37568"
