"""Independent fixtures for the second design's newly supported paint cases."""

from copy import deepcopy
import math
import re

import pytest

from lanhu_codegen import generate_design_files
from lanhu_codegen.figma_schema import UnsupportedFigmaFeature, figma_to_dds_schema


def rgba(red=0, green=0, blue=0, alpha=1):
    return {"r": red, "g": green, "b": blue, "a": alpha}


def layer(identity, box=(0, 0, 100, 100), *, children=(), kind="artboard"):
    return {
        "id": identity, "name": identity, "type": kind, "visible": True, "opacity": 1,
        "frame": dict(zip(("left", "top", "width", "height"), box)),
        "realFrame": dict(zip(("left", "top", "width", "height"), box)),
        "rotation": 0, "clipped": False, "isMask": False,
        "transform": [[1, 0, box[0]], [0, 1, box[1]]],
        "style": {"isEnabled": True, "opacity": 1, "blendMode": 0,
                  "fills": [], "borders": [], "shadows": [], "blurs": []},
        "layers": list(children),
    }


def document(*children):
    root = layer("root", (0, 0, 300, 240), children=children)
    root["origin"] = "figma"
    return {"meta": {"host": {"name": "figma"}}, "artboard": root}


def shadow(**overrides):
    # Native exports duplicate the shadow alpha into color.a and opacity.
    result = {"isEnabled": True, "x": 0, "y": 4, "blur": 10, "spread": 0,
              "inset": False, "opacity": 0.10000000149011612,
              "blendMode": 0, "color": rgba(alpha=0.1)}
    result.update(overrides)
    return result


def text_layer(identity="label", *, height=22, content="Search", vertical="center"):
    result = layer(identity, (10, 10, 100, height), kind="textLayer")
    font = {"postScriptName": "Arial", "name": "Arial", "type": "Regular", "size": 14,
            "fontWeight": 400, "align": "left", "verticalAlignment": vertical,
            "lineHeight": {"unit": "PIXELS", "value": 22},
            "letterSpacing": {"unit": "percent", "value": 0},
            "lineSpacing": 0, "bold": False, "italic": False}
    length = len(content.encode("utf-16-le")) // 2
    segment = {"from": 0, "to": length, "length": length, "content": content,
               "font": font, "color": rgba()}
    result["text"] = {"value": content, "frame": deepcopy(result["frame"]),
                      "style": deepcopy(segment), "styles": [segment]}
    return result


def dds_image(identity="raster", box=(80, 60, 16, 12)):
    result = layer(identity, box)
    result["hasExportDDSImage"] = True
    result["ddsImage"] = {"imageUrl": f"https://example.test/{identity}.png"}
    return result


def mirrored_wrapper():
    child = dds_image("raster", (90, 58, 16, 16))
    child["transform"] = [[-1, 0, 90], [0, 1, 58]]
    child["rotation"] = 180
    child["realFrame"]["left"] = 74
    # The native export retains these paths under an already rasterized node.
    # They must not need independent SVG/vector support to flatten its parent.
    child["layers"] = [layer("baked-vector", (80, 60, 4, 4), kind="shapeLayer")]
    parent = layer("mirror-wrapper", (100, 50, 40, 32), children=[child])
    parent["rotation"] = 180
    parent["transform"] = [[-1, 0, 100], [0, 1, 50]]
    parent["realFrame"]["left"] = 60
    parent["paths"] = [{"type": "rect", "frame": deepcopy(parent["frame"]),
                        "radius": dict.fromkeys(("topLeft", "topRight", "bottomLeft", "bottomRight"), 8)}]
    return parent


def all_nodes(node):
    yield node
    for child in node["children"]:
        yield from all_nodes(child)


def find(root, identity):
    return next(node for node in all_nodes(root) if node["layerId"] == identity)


def css_rule(files, node):
    selector = re.escape(node["props"]["className"])
    match = re.search(r"\." + selector + r"\s*\{([^}]*)\}", files["index.css"])
    assert match
    return {key.strip(): value.strip() for key, value in
            (part.split(":", 1) for part in match[1].split(";") if part.strip())}


def parsed_shadows(value):
    number = r"(-?\d+(?:\.\d+)?)(?:px)?"
    pattern = r"(inset\s+)?" + r"\s+".join([number] * 4) + r"\s+rgba\(([^)]+)\)"
    return [{"inset": bool(match[1]), "geometry": [float(match[i]) for i in range(2, 6)],
             "rgba": [float(channel) for channel in match[6].split(",")]}
            for match in re.finditer(pattern, value)]


def test_native_outer_shadow_preserves_offset_blur_spread_and_single_alpha():
    card = layer("card", (10, 20, 100, 80))
    card["style"]["shadows"] = [shadow()]
    raw = document(card)
    before = deepcopy(raw)
    schema = figma_to_dds_schema(raw)
    assert raw == before
    files = generate_design_files(schema)
    assert parsed_shadows(css_rule(files, find(schema, "card"))["box-shadow"]) == [
        {"inset": False, "geometry": [0, 4, 10, 0], "rgba": [0, 0, 0, 0.1]},
    ]


def test_multiple_shadows_keep_inset_negative_spread_and_fractional_offsets():
    card = layer("card", (10, 20, 100, 80))
    card["style"]["shadows"] = [shadow(), shadow(x=-2.5, y=3.25, blur=4.5, spread=-1.5,
                                               inset=True, color=rgba(0.2, 0.4, 0.6, 0.5), opacity=0.5)]
    schema = figma_to_dds_schema(document(card))
    files = generate_design_files(schema)
    assert parsed_shadows(css_rule(files, find(schema, "card"))["box-shadow"]) == [
        {"inset": False, "geometry": [0, 4, 10, 0], "rgba": [0, 0, 0, 0.1]},
        {"inset": True, "geometry": [-2.5, 3.25, 4.5, -1.5], "rgba": [51, 102, 153, 0.5]},
    ]


@pytest.mark.parametrize("change,reason", [
    ({"blur": -1}, "shadows.blur"),
    ({"inset": "yes"}, "shadows.inset"),
    ({"blendMode": 1}, "blend mode"),
])
def test_unsupported_or_invalid_shadow_is_not_silently_dropped(change, reason):
    card = layer("card")
    card["style"]["shadows"] = [shadow(**change)]
    with pytest.raises(UnsupportedFigmaFeature, match=re.escape(reason)):
        figma_to_dds_schema(document(card))


def test_text_shadow_still_requires_an_exported_image():
    text = text_layer(vertical="top")
    text["style"]["shadows"] = [shadow()]
    with pytest.raises(UnsupportedFigmaFeature, match="text shadows"):
        figma_to_dds_schema(document(text))


def test_centered_single_line_with_equal_height_has_no_extra_vertical_offset():
    raw = document(text_layer())
    schema = figma_to_dds_schema(raw)
    text = find(schema, "label")
    assert text["rowDims"] == {"left": 10, "top": 10, "width": 100, "height": 22}
    files = generate_design_files(schema)
    rule = css_rule(files, text)
    assert rule["height"] == rule["line-height"] == "22px"
    assert rule["white-space"] == "nowrap"
    assert "transform" not in rule


@pytest.mark.parametrize("height,content", [(44, "Search"), (22, "Search\nAgain")])
def test_centered_taller_or_multiline_text_is_still_rejected(height, content):
    with pytest.raises(UnsupportedFigmaFeature, match="vertical text alignment"):
        figma_to_dds_schema(document(text_layer(height=height, content=content)))


def test_transparent_mirror_wrapper_with_baked_descendants_flattens_safely():
    raw = document(mirrored_wrapper())
    before = deepcopy(raw)
    schema = figma_to_dds_schema(raw)
    assert raw == before
    assert [node["layerId"] for node in all_nodes(schema)] == ["root", "raster"]
    image = find(schema, "raster")
    assert image["rowDims"] == {"left": 74, "top": 58, "width": 16, "height": 16}
    assert image["props"]["src"] == "https://example.test/raster.png"
    rule = css_rule(generate_design_files(schema), image)
    assert "transform" not in rule  # A second CSS mirror would undo the baked one.


@pytest.mark.parametrize("feature", ["paint", "text", "clip", "opacity", "shadow"])
def test_effectful_or_live_text_mirror_wrapper_is_not_ignored(feature):
    parent = mirrored_wrapper()
    if feature == "paint":
        parent["style"]["fills"] = [{"type": "color", "isEnabled": True,
                                       "opacity": 1, "color": rgba(1, 0, 0)}]
    elif feature == "text":
        text = text_layer(vertical="top")
        text["transform"] = [[-1, 0, 85], [0, 1, 60]]
        text["rotation"] = 180
        parent["layers"].append(text)
    elif feature == "clip":
        parent["clipped"] = True
    elif feature == "opacity":
        parent["opacity"] = 0.5
    else:
        parent["style"]["shadows"] = [shadow()]
    with pytest.raises(UnsupportedFigmaFeature, match="rotation|transformed geometry"):
        figma_to_dds_schema(document(parent))


@pytest.mark.parametrize("flip_x,flip_y", [(True, False), (False, True), (True, True)])
def test_exact_axis_reflection_corrects_only_corroborated_corner_anchor(flip_x, flip_y):
    image = dds_image()
    image["transform"] = [[-1 if flip_x else 1, 0, 80], [0, -1 if flip_y else 1, 60]]
    image["rotation"] = 180
    image["realFrame"].update(left=64 if flip_x else 80, top=48 if flip_y else 60)
    schema = figma_to_dds_schema(document(image))
    assert find(schema, "raster")["rowDims"] == image["realFrame"]


@pytest.mark.parametrize("has_real_frame", [False, True])
def test_reflection_does_not_double_correct_an_already_normalized_box(has_real_frame):
    image = dds_image(box=(64, 60, 16, 12))
    image["transform"] = [[-1, 0, 80], [0, 1, 60]]
    image["rotation"] = 180
    if not has_real_frame:
        image.pop("realFrame")
    schema = figma_to_dds_schema(document(image))
    assert find(schema, "raster")["rowDims"] == image["frame"]


@pytest.mark.parametrize("near_axis", [True, False])
def test_near_axis_and_general_rotation_keep_original_export_frame(near_axis):
    image = dds_image()
    if near_axis:
        image["transform"] = [[-1, -8.742277657347586e-8, 80], [8.742277657347586e-8, -1, 60]]
        image["rotation"] = 179.99999502168694
        image["realFrame"] = {"left": 63.99999895, "top": 48, "width": 16.00000105, "height": 12.0000014}
    else:
        cosine, sine = math.cos(math.pi / 6), math.sin(math.pi / 6)
        image["transform"] = [[cosine, -sine, 80], [sine, cosine, 60]]
        image["rotation"] = 30
        image["realFrame"] = {"left": 74, "top": 60, "width": 16 * cosine + 12 * sine,
                              "height": 16 * sine + 12 * cosine}
    schema = figma_to_dds_schema(document(image))
    assert find(schema, "raster")["rowDims"] == image["frame"]
