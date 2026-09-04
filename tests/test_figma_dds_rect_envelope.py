"""Bounded DDS envelope projection; never a claim to recover vector paths."""

from copy import deepcopy
import math

import pytest

from lanhu_codegen.figma_schema import UnsupportedFigmaFeature, figma_to_dds_schema


def layer(identity, box, kind="artboard"):
    return {
        "id": identity, "name": identity, "type": kind, "origin": "figma",
        "visible": True, "opacity": 1, "clipped": False, "isMask": False,
        "rotation": 0, "transform": [[1, 0, box[0]], [0, 1, box[1]]],
        "frame": dict(zip(("left", "top", "width", "height"), box)),
        "realFrame": dict(zip(("left", "top", "width", "height"), box)),
        "style": {"isEnabled": True, "opacity": 1, "blendMode": 0,
                  "fills": [], "borders": [], "shadows": [], "blurs": []},
        "layers": [], "hasExportDDSImage": False, "hasExportImage": False,
    }


def envelope(*, size=12, direction=1, radius=0, color=(0.2, 0.4, 0.8)):
    result = layer("shape-without-contour", (40.25, 30.5, size, size), "shapeLayer")
    result["rotation"] = 90 * direction
    result["transform"] = [[0, -direction, 940.25], [direction, 0, -69.5]]
    result["realFrame"]["left" if direction == 1 else "top"] -= size
    result["radius"] = dict.fromkeys(("topLeft", "topRight", "bottomRight", "bottomLeft"), radius)
    result["paths"] = [{"type": "rect", "frame": deepcopy(result["frame"]), "radius": deepcopy(result["radius"])}]
    result["style"]["fills"] = [{"type": "color", "isEnabled": True, "opacity": 1, "blendMode": 0,
                                  "color": dict(zip(("r", "g", "b", "a"), (*color, 1)))}]
    return result


def document(shape):
    root = layer("page", (0, 0, 200, 160))
    root["layers"] = [shape]
    return {"meta": {"host": {"name": "figma"}}, "artboard": root}


def find(root, identity):
    if root["layerId"] == identity:
        return root
    for child in root["children"]:
        found = find(child, identity)
        if found is not None:
            return found
    return None


@pytest.mark.parametrize("size,radius,color,direction", [
    (12, 0, (0.2, 0.4, 0.8), 1), (18, 2, (0.8, 0.1, 0.3), -1),
    (7.5, 1.5, (0.1, 0.9, 0.4), 1),
])
@pytest.mark.parametrize("name", ["an arbitrary renamed layer", "Rectangle 123", "矩形 3"])
def test_explicit_dds_projection_is_color_size_and_name_independent_and_warned(size, radius, color, direction, name):
    shape = envelope(size=size, radius=radius, color=color, direction=direction)
    shape["name"] = name
    source = document(shape)
    before = deepcopy(source)
    result = figma_to_dds_schema(source)
    projected = find(result, shape["id"])
    assert source == before
    assert projected["type"] == "lanhublock" and projected["children"] == []
    assert projected["ddsRectEnvelopeProjection"] is True
    assert projected["rowDims"] == {key: math.ceil(value) for key, value in shape["frame"].items()}
    warning, = projected["conversionWarnings"]
    assert warning["code"] == "dds_rect_envelope_projection"
    assert warning["layerId"] == shape["id"]
    assert "original vector contour and rotation are not restored" in warning["reason"]
    assert warning["sourceFrame"] == shape["frame"]
    assert warning["sourceRealFrame"] == shape["realFrame"]
    assert warning["sourceRotation"] == 90 * direction
    style = projected["props"]["style"]
    rgb = ", ".join(str(round(channel * 255)) for channel in color)
    assert style["backgroundColor"] == f"rgba({rgb}, 1)"
    assert "transform" not in style and "clipPath" not in style


def test_native_float_noise_at_a_quarter_turn_is_accepted_only_with_corroborating_bounds():
    shape = envelope()
    shape["rotation"] = 90.0000025
    shape["transform"][0][0] = -4.3711388e-8
    shape["transform"][1][1] = -4.3711388e-8
    shape["realFrame"]["left"] -= 0.0000002
    shape["realFrame"]["top"] -= 0.0000002
    shape["realFrame"]["width"] += 0.0000002
    shape["realFrame"]["height"] += 0.0000002
    assert find(figma_to_dds_schema(document(shape)), shape["id"])["ddsRectEnvelopeProjection"] is True


@pytest.mark.parametrize("options", [
    {"layout": "absolute"}, {"border_layout": "source"},
    {"layout": "absolute", "border_layout": "source"},
])
def test_source_and_absolute_modes_still_reject_the_missing_contour(options):
    with pytest.raises(UnsupportedFigmaFeature, match="missing vector geometry"):
        figma_to_dds_schema(document(envelope()), **options)


@pytest.mark.parametrize("path,value", [
    (("rotation",), 0), (("rotation",), 180), (("rotation",), 89), (("rotation",), 90.001),
    (("transform",), [[0, 1, 0], [1, 0, 0]]),  # reflection, not a quarter turn
    (("transform",), [[0, -2, 0], [2, 0, 0]]),  # scale
    (("transform",), [[0.1, -1, 0], [1, 0, 0]]),  # shear
    (("transform",), None), (("realFrame",), None),
    (("realFrame", "left"), 40.25),  # normalized bounds do not corroborate a corner anchor
    (("paths", 0, "frame", "left"), 30),
    (("paths", 0, "type"), "path"), (("paths", 0, "data"), "M0 0 L12 12 Z"),
    (("paths", 0, "radius"), None), (("paths", 0, "radius", "topLeft"), 2),
    (("radius", "topLeft"), 1), (("shapeType",), "ellipse"),
    (("vectorPaths",), [{"data": "M0 0L12 12"}]),
    (("style", "fills"), []), (("style", "fills", 0, "type"), "gradient"),
    (("style", "fills", 0, "color", "a"), 0.5),
    (("style", "fills", 0, "opacity"), 0.5), (("opacity",), 0.5),
    (("style", "blendMode"), "multiply"), (("style", "fills", 0, "blendMode"), "screen"),
    (("style", "borders"), [{"isEnabled": True, "width": 1}]),
    (("style", "shadows"), [{"isEnabled": True, "opacity": 1}]),
    (("style", "blurs"), [{"isEnabled": True, "opacity": 1}]),
    (("style", "filter"), "blur(1px)"), (("clipped",), True), (("isMask",), True),
    (("layers",), [layer("child", (0, 0, 2, 2))]),
])
def test_projection_does_not_admit_unverified_geometry_or_additional_paint(path, value):
    shape = envelope()
    target = shape
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = deepcopy(value)
    with pytest.raises(UnsupportedFigmaFeature):
        figma_to_dds_schema(document(shape))


def test_non_square_quarter_turn_remains_unsupported_even_with_matching_path_and_real_bounds():
    shape = envelope()
    shape["frame"]["height"] = 8
    shape["paths"][0]["frame"] = deepcopy(shape["frame"])
    shape["realFrame"] = {"left": 32.25, "top": 30.5, "width": 8, "height": 12}
    with pytest.raises(UnsupportedFigmaFeature):
        figma_to_dds_schema(document(shape))


def test_rect_payload_requires_numeric_dimensions_even_when_boolean_equals_square_size():
    shape = envelope(size=1)
    shape["paths"][0]["frame"]["width"] = True
    with pytest.raises(UnsupportedFigmaFeature):
        figma_to_dds_schema(document(shape))


def test_oversized_symmetric_radius_and_multiple_envelopes_remain_unsupported():
    shape = envelope(radius=7)
    with pytest.raises(UnsupportedFigmaFeature):
        figma_to_dds_schema(document(shape))
    shape = envelope()
    shape["paths"].append(deepcopy(shape["paths"][0]))
    with pytest.raises(UnsupportedFigmaFeature):
        figma_to_dds_schema(document(shape))


def test_real_export_still_takes_precedence_and_never_gets_projection_marker():
    shape = envelope()
    shape["hasExportDDSImage"] = True
    shape["ddsImage"] = {"imageUrl": "https://assets.example/real-shape.png"}
    result = find(figma_to_dds_schema(document(shape)), shape["id"])
    assert result["type"] == "lanhuimage"
    assert "ddsRectEnvelopeProjection" not in result
    assert not result.get("conversionWarnings")
