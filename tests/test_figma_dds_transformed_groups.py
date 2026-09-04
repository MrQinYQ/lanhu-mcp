"""Bounded DDS envelopes preserve provenance rather than recover vector paths."""

from copy import deepcopy
import math
import re

import pytest

from lanhu_codegen import generate_design_files
from lanhu_codegen.figma_schema import UnsupportedFigmaFeature, figma_to_dds_schema


CORNERS = ("topLeft", "topRight", "bottomRight", "bottomLeft")
URL = "https://example.com/baked-pixels.png"


def layer(identity="unrelated-vector", *, box=(57.25, 49.5, 30.000002, 29.999998), kind="shapeLayer"):
    frame = dict(zip(("left", "top", "width", "height"), box))
    return {"id": identity, "name": identity, "type": kind, "frame": frame,
            "realFrame": deepcopy(frame), "rotation": 0,
            "transform": [[1, 0, 2057.25], [0, 1, -950.5]],
            "visible": True, "opacity": 1, "clipped": False, "isMask": False,
            "radius": dict.fromkeys(CORNERS, 0),
            "paths": [{"type": "rect", "frame": deepcopy(frame), "radius": dict.fromkeys(CORNERS, 0)}],
            "style": {"isEnabled": True, "opacity": 1, "blendMode": 0,
                      "fills": [], "borders": [], "shadows": [], "blurs": []},
            "layers": [], "hasExportDDSImage": False, "hasExportImage": False}


def color(alpha=1, rgb=(0.2, 0.4, 0.6)):
    return dict(zip(("r", "g", "b", "a"), (*rgb, alpha)))


def fill(alpha=1, rgb=(0.2, 0.4, 0.6)):
    return {"type": "color", "isEnabled": True, "opacity": alpha, "blendMode": 0,
            "color": color(alpha, rgb)}


def set_turn(node, turns, *, noise=0):
    matrix = {1: ((0, -1), (1, 0)), 2: ((-1, 0), (0, -1)), 3: ((0, 1), (-1, 0))}[turns]
    node["rotation"] = turns * 90 + noise
    for row in range(2):
        node["transform"][row][:2] = matrix[row]
    if noise:
        angle = math.radians(node["rotation"])
        node["transform"][0][:2] = (math.cos(angle), -math.sin(angle))
        node["transform"][1][:2] = (math.sin(angle), math.cos(angle))
    frame = node["frame"]
    a, b, _ = node["transform"][0]
    c, d, _ = node["transform"][1]
    points = [(frame["left"] + a*x + b*y, frame["top"] + c*x + d*y)
              for x in (0, frame["width"]) for y in (0, frame["height"])]
    xs, ys = zip(*points)
    node["realFrame"] = {"left": min(xs), "top": min(ys), "width": max(xs)-min(xs), "height": max(ys)-min(ys)}
    return node


def decorated_rect(*, side=30, radius=4.999999, rgb=(0.2, 0.4, 0.6)):
    node = set_turn(layer(box=(57.25, 49.5, side+0.000002, side-0.000002)), 2, noise=-0.000005)
    node["paths"][0]["radius"] = dict.fromkeys(CORNERS, radius)
    node["style"]["fills"] = [fill(rgb=rgb)]
    width = 0.9999998211860657
    node["style"]["borders"] = [{"isEnabled": True, "opacity": 1, "width": width,
        "widths": dict.fromkeys(("top", "right", "bottom", "left"), width),
        "style": "solid", "lineAlignment": "inside", "color": color()}]
    node["style"]["shadows"] = [{"isEnabled": True, "opacity": 0.15, "color": color(0.15),
        "x": 0, "y": 6.999998, "blur": 17.999996, "spread": 0, "inset": False}]
    return node


def projected_group():
    outer = set_turn(layer("turned-container", kind="groupLayer"), 2, noise=-0.000005)
    first = decorated_rect()
    inner = set_turn(layer("quarter-container", box=(51, 38, 14, 14), kind="groupLayer"), 1)
    square = set_turn(layer("inner-square", box=(51, 38, 14, 14)), 1)
    square["style"]["fills"] = [fill(rgb=(0.7, 0.3, 0.1))]
    image = set_turn(layer("baked-child", box=(47.25, 46.25, 6, 6.000002), kind="groupLayer"), 2, noise=-0.000005)
    image.update(hasExportDDSImage=True, ddsImage={"imageUrl": URL})
    inner["layers"] = [square, image]
    outer["layers"] = [first, inner]
    return outer


def transparent_rect(*, rgb=(0.2, 0.4, 0.6), radius=3):
    node = layer(box=(29, 47, 63, 22))
    node["paths"][0]["radius"] = dict.fromkeys(CORNERS, radius)
    node["style"]["fills"] = [fill(0, rgb)]
    return node


def zero_height_shape():
    node = layer(box=(18, 93, 27, 0))
    node.update(hasExportDDSImage=True, ddsImage={"imageUrl": URL})
    return node


def document(node):
    root = layer("page", box=(1000, -600, 400, 300), kind="artboard")
    root["layers"] = [node]
    return {"meta": {"host": {"name": "figma"}}, "artboard": root}


def walk(node):
    yield node
    for child in node.get("children", []):
        yield from walk(child)


def find(schema, identity):
    return next((item for item in walk(schema) if item["layerId"] == identity), None)


def convert(node, **options):
    raw = document(node)
    before, loads = deepcopy(raw), []
    def load(url):
        loads.append(url)
        raise AssertionError("An envelope policy must not inspect the exported pixels")
    result = figma_to_dds_schema(raw, asset_loader=load, **options)
    assert raw == before and not loads
    return result


def mutate(node, path, value):
    target = node
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = deepcopy(value)


@pytest.mark.parametrize("side,radius,rgb", [(30, 4.999999, (0.2, 0.4, 0.6)), (42, 8, (0.8, 0.2, 0.1))])
def test_half_turn_decorated_envelope_preserves_raw_anchor_and_warns(side, radius, rgb):
    node = decorated_rect(side=side, radius=radius, rgb=rgb)
    result = find(convert(node), node["id"])
    assert result["rowDims"] == {key: math.ceil(value) for key, value in node["frame"].items()}
    assert result["ddsHalfTurnRectProjection"] is True
    assert "ddsRectEnvelopeProjection" not in result
    warning, = result["conversionWarnings"]
    assert warning["code"] == "dds_half_turn_rect_projection"
    assert warning["sourceFrame"] == node["frame"] and warning["sourceRealFrame"] == node["realFrame"]
    assert "original vector contour and rotation are not restored" in warning["reason"]
    css = result["props"]["style"]
    assert css["borderRadius"] == f"{math.floor(radius)}px"
    assert css["border"].startswith("0.9999998211860657px solid ")
    assert css["boxShadow"] == "0px 6px 17px 0px rgba(51,102,153,0.150000)"
    assert "transform" not in css


def test_half_turn_projection_uses_official_css_serializer_without_transform_hacks():
    node = decorated_rect()
    schema = convert(node)
    result = find(schema, node["id"])
    css = generate_design_files(schema)["index.css"]
    rule = re.search(r"\." + re.escape(result["props"]["className"]) + r"\s*\{([^}]*)\}", css)[1]
    assert "border: 0.9999998211860657px solid" in rule
    assert "box-shadow: 0px 6px 17px 0px rgba(51, 102, 153, 0.15)" in rule
    assert "width: 31px" in rule and "height: 30px" in rule
    assert "transform" not in rule


def test_transformed_transparent_groups_keep_only_verified_leaf_envelopes_and_baked_images():
    node = projected_group()
    schema = convert(node)
    for identity in ("turned-container", "quarter-container"):
        assert find(schema, identity) is None
        warning = next(w for w in schema["conversionWarnings"] if w["layerId"] == identity)
        assert warning["code"] == "dds_projected_group_transform"
        assert "original vector contours and rotations are not restored" in warning["reason"]
    for leaf in (node["layers"][0], *node["layers"][1]["layers"]):
        result = find(schema, leaf["id"])
        assert result["rowDims"] == {key: math.ceil(value) for key, value in leaf["frame"].items()}
    assert find(schema, "baked-child")["props"]["src"] == URL


@pytest.mark.parametrize("factory", [decorated_rect, projected_group, transparent_rect])
@pytest.mark.parametrize("options", [{"layout": "absolute"}, {"border_layout": "source"}])
def test_source_preserving_modes_keep_rejecting_unknown_contours_and_unbaked_transforms(factory, options):
    with pytest.raises(UnsupportedFigmaFeature):
        convert(factory(), **options)


@pytest.mark.parametrize("path,value", [
    (("rotation",), 179.9), (("transform",), [[-2, 0, 0], [0, -2, 0]]),
    (("transform",), [[-1, 0.1, 0], [0, -1, 0]]),
    (("transform",), [[-1, 0, 0], [0, 1, 0]]), (("transform",), None),
    (("realFrame",), None), (("realFrame", "left"), 0),
    (("paths", 0, "radius", "topLeft"), 1), (("paths", 0, "radius"), dict.fromkeys(CORNERS, 0)),
    (("paths", 0, "frame", "width"), 99), (("paths", 0, "data"), "M0 0L4 4Z"),
    (("shapeType",), "polygon"), (("vectorPaths",), [{"data": "M0 0L4 4Z"}]),
    (("opacity",), 0.5), (("clipped",), True), (("isMask",), True),
    (("style", "filter"), "blur(1px)"), (("style", "blurs"), [{"isEnabled": True}]),
    (("style", "fills", 0, "opacity"), 0.5), (("style", "borders", 0, "lineAlignment"), "outside"),
    (("style", "borders", 0, "widths", "left"), 2), (("style", "shadows"), []),
    (("layers",), [layer("unexported-child", kind="textLayer")]),
])
def test_half_turn_does_not_waive_unverified_geometry_or_effects(path, value):
    node = decorated_rect()
    mutate(node, path, value)
    with pytest.raises(UnsupportedFigmaFeature):
        convert(node)


def test_general_non_square_half_turn_remains_unsupported_despite_valid_bounds():
    node = decorated_rect()
    node["frame"]["width"] = node["paths"][0]["frame"]["width"] = 47
    set_turn(node, 2)
    with pytest.raises(UnsupportedFigmaFeature):
        convert(node)


@pytest.mark.parametrize("path,value", [
    (("type",), "artboard"), (("opacity",), 0.5), (("clipped",), True), (("isMask",), True),
    (("style", "fills"), [fill()]), (("style", "shadows"), [{"isEnabled": True}]),
    (("style", "filter"), "blur(1px)"), (("realFrame",), None),
    (("transform",), [[-1, 0.1, 0], [0, -1, 0]]),
    (("transform",), [[-2, 0, 0], [0, -2, 0]]),
])
def test_projected_wrapper_requires_transparency_unit_transform_and_verified_bounds(path, value):
    node = projected_group()
    mutate(node, path, value)
    with pytest.raises(UnsupportedFigmaFeature):
        convert(node)


@pytest.mark.parametrize("kind", ["shapeLayer", "textLayer", "artboard"])
def test_projected_wrapper_cannot_hide_a_live_or_ordinary_only_descendant(kind):
    node = projected_group()
    child = layer("additional-child", box=(30, 40, 12, 8), kind=kind)
    if kind == "artboard":
        child.update(hasExportImage=True, image={"imageUrl": URL})
    node["layers"].append(child)
    with pytest.raises(UnsupportedFigmaFeature):
        convert(node)


@pytest.mark.parametrize("rgb,radius", [((0.2, 0.4, 0.6), 3), ((0, 0, 0), 5)])
def test_alpha_zero_rect_is_retained_as_warned_layout_envelope_even_with_black_rgb(rgb, radius):
    node = transparent_rect(rgb=rgb, radius=radius)
    result = find(convert(node), node["id"])
    assert result is not None and result["type"] == "lanhublock"
    assert result["rowDims"] == node["frame"]
    assert result["props"]["style"]["backgroundColor"] == "rgba(" + ", ".join(str(round(v*255)) for v in rgb) + ", 0)"
    assert result["props"]["style"]["borderRadius"] == f"{radius}px"
    assert result["ddsTransparentRectProjection"] is True
    assert result["conversionWarnings"][0]["code"] == "dds_transparent_rect_projection"


@pytest.mark.parametrize("path,value", [
    (("style", "fills"), [fill()]), (("style", "fills"), []),
    (("style", "fills", 0, "type"), "image"), (("style", "borders"), [{"width": 1}]),
    (("style", "shadows"), [{"isEnabled": False}]), (("style", "blurs"), [{"isEnabled": False}]),
    (("style", "filter"), "blur(1px)"), (("style", "blendMode"), "multiply"),
    (("rotation",), 90), (("transform",), [[-1, 0, 0], [0, 1, 0]]),
    (("realFrame",), None), (("realFrame", "width"), 64),
    (("paths", 0, "radius", "topLeft"), 1), (("paths", 0, "frame", "left"), 28),
    (("shapeType",), "ellipse"), (("vectorPaths",), [{"data": "M0 0L1 1"}]),
    (("opacity",), 0.5), (("clipped",), True), (("isMask",), True),
])
def test_transparent_envelope_policy_does_not_make_visible_unknown_geometry_succeed(path, value):
    node = transparent_rect()
    mutate(node, path, value)
    with pytest.raises(UnsupportedFigmaFeature):
        convert(node)


def test_exact_zero_height_empty_shape_export_is_omitted_without_calling_pixel_loader():
    node = zero_height_shape()
    schema = convert(node)
    assert find(schema, node["id"]) is None
    warning, = schema["conversionWarnings"]
    assert warning["code"] == "dds_zero_height_shape_omitted"
    assert warning["sourceFrame"] == node["frame"] and warning["sourceImageUrl"] == URL
    assert "does not imply that the source image is transparent" in warning["reason"]


@pytest.mark.parametrize("options", [{"layout": "absolute"}, {"border_layout": "source"}])
def test_zero_height_export_remains_a_real_image_in_source_modes(options):
    node = zero_height_shape()
    result = find(convert(node, **options), node["id"])
    assert result["type"] == "lanhuimage" and result["props"]["src"] == URL
    assert result["rowDims"]["height"] == 0


@pytest.mark.parametrize("path,value", [
    (("type",), "artboard"), (("frame", "height"), 0.001),
    (("style", "fills"), [fill()]), (("style", "shadows"), [{"isEnabled": True}]),
    (("paths", 0, "radius"), dict.fromkeys(CORNERS, 1)), (("realFrame",), None),
    (("hasExportImage",), True), (("rotation",), 90), (("clipped",), True),
    (("opacity",), 0.5), (("shapeType",), "line"),
    (("paths", 0, "data"), "M0 0L27 0"), (("style", "filter"), "blur(1px)"),
])
def test_zero_height_policy_does_not_omit_general_or_unverified_image_exports(path, value):
    node = zero_height_shape()
    mutate(node, path, value)
    result = find(convert(node), node["id"])
    assert result["type"] == "lanhuimage" and result["props"]["src"] == URL
    assert "ddsEmptyShapeProjection" not in result


def test_zero_height_missing_resource_is_still_an_error_before_projection():
    node = zero_height_shape()
    del node["ddsImage"]
    with pytest.raises(UnsupportedFigmaFeature, match="without ddsImage resource"):
        convert(node)
