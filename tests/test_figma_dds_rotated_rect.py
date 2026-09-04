"""DDS's narrow raw-envelope projection is not rotation/contour recovery."""

from copy import deepcopy
import math
import re

import pytest

from lanhu_codegen import generate_design_files
from lanhu_codegen.figma_schema import UnsupportedFigmaFeature, figma_to_dds_schema


def layer(identity, box, kind="artboard"):
    frame = dict(zip(("left", "top", "width", "height"), box))
    return {
        "id": identity, "name": identity, "type": kind, "origin": "figma",
        "visible": True, "opacity": 1, "clipped": False, "isMask": False,
        "rotation": 0, "transform": [[1, 0, box[0]], [0, 1, box[1]]],
        "frame": frame, "realFrame": deepcopy(frame),
        "style": {"isEnabled": True, "opacity": 1, "blendMode": 0,
                  "fills": [], "borders": [], "shadows": [], "blurs": []},
        "layers": [], "hasExportDDSImage": False, "hasExportImage": False,
    }


def transformed_bounds(node):
    frame = node["frame"]
    a, b, _ = node["transform"][0]
    c, d, _ = node["transform"][1]
    points = [(frame["left"] + a * x + b * y, frame["top"] + c * x + d * y)
              for x in (0, frame["width"]) for y in (0, frame["height"])]
    xs, ys = zip(*points)
    return {"left": min(xs), "top": min(ys), "width": max(xs) - min(xs), "height": max(ys) - min(ys)}


def hairline(*, width=1, height=84, direction=-1, rotation=90, color=(0.2, 0.4, 0.8)):
    node = layer("raw-strip", (23.25, 17.5, width, height), "shapeLayer")
    node["rotation"] = rotation
    # Native rotation and matrix signs need not agree. Translation is in the
    # source document, while frame/realFrame are in the artboard's coordinates.
    node["transform"] = [[0, -direction, 823.25], [direction, 0, -182.5]]
    node["realFrame"] = transformed_bounds(node)
    node["radius"] = dict.fromkeys(("topLeft", "topRight", "bottomRight", "bottomLeft"), 0)
    node["paths"] = [{"type": "rect", "frame": deepcopy(node["frame"]), "radius": deepcopy(node["radius"])}]
    node["style"]["fills"] = [{"type": "color", "isEnabled": True, "opacity": 1, "blendMode": 0,
                                "color": dict(zip(("r", "g", "b", "a"), (*color, 1)))}]
    return node


def document(node):
    root = layer("page", (0, 0, 320, 240))
    root["layers"] = [node]
    return {"meta": {"host": {"name": "figma"}}, "artboard": root}


def find(root, identity):
    if root["layerId"] == identity:
        return root
    for child in root["children"]:
        found = find(child, identity)
        if found is not None:
            return found
    return None


@pytest.mark.parametrize("width,height,direction,rotation,color", [
    (1, 84, -1, 90, (0.2, 0.4, 0.8)),
    (0.5, 51.25, 1, 90, (0.8, 0.2, 0.1)),
    (39.5, 1, -1, -90, (0.1, 0.7, 0.3)),
    (62, 0.75, 1, 270, (0.6, 0.3, 0.9)),
])
@pytest.mark.parametrize("name", ["arbitrary renamed vector", "Rectangle 97", "矩形 4"])
def test_dds_hairline_uses_raw_envelope_and_warns_independently_of_layer_name(width, height, direction, rotation, color, name):
    node = hairline(width=width, height=height, direction=direction, rotation=rotation, color=color)
    node["name"] = name
    source = document(node)
    before = deepcopy(source)
    converted = find(figma_to_dds_schema(source), node["id"])
    assert source == before
    assert converted["type"] == "lanhublock" and not converted["children"]
    assert converted["rowDims"] == {key: math.ceil(value) for key, value in node["frame"].items()}
    assert converted["ddsRotatedHairlineProjection"] is True
    assert "ddsRectEnvelopeProjection" not in converted  # no square containment rewrite
    warning, = converted["conversionWarnings"]
    assert warning["code"] == "dds_rotated_hairline_projection"
    assert warning["sourceFrame"] == node["frame"] and warning["sourceRealFrame"] == node["realFrame"]
    assert warning["sourceRotation"] == rotation
    assert "original vector contour and rotation are not restored" in warning["reason"]
    rgb = ", ".join(str(round(channel * 255)) for channel in color)
    assert converted["props"]["style"]["backgroundColor"] == f"rgba({rgb}, 1)"
    assert "transform" not in converted["props"]["style"]


def test_official_renderer_receives_the_vertical_raw_strip_not_the_rotated_horizontal_bounds():
    node = hairline(width=1, height=84)
    schema = figma_to_dds_schema(document(node))
    converted = find(schema, node["id"])
    files = generate_design_files(schema)
    selector = re.escape(converted["props"]["className"])
    rule = re.search(r"\." + selector + r"\s*\{([^}]*)\}", files["index.css"])
    assert rule is not None
    declarations = {key.strip(): value.strip() for key, value in
                    (part.split(":", 1) for part in rule[1].split(";") if part.strip())}
    assert declarations["width"] == "1px" and declarations["height"] == "84px"
    assert "transform" not in declarations and "clip-path" not in declarations
    assert "background-color" in declarations


def test_native_quarter_turn_noise_is_verified_using_all_four_transformed_corners():
    node = hairline(height=328)
    node["rotation"] = 90.0000025
    node["transform"][0][0] = node["transform"][1][1] = -4.3711388e-8
    node["realFrame"] = transformed_bounds(node)
    # Noise scales with length and exceeds the old square's fixed correction.
    assert abs(node["realFrame"]["height"] - 1) > 1e-5
    assert find(figma_to_dds_schema(document(node)), node["id"])["ddsRotatedHairlineProjection"] is True


@pytest.mark.parametrize("options", [{"layout": "absolute"}, {"border_layout": "source"},
                                      {"layout": "absolute", "border_layout": "source"}])
@pytest.mark.parametrize("name", ["arbitrary shape", "Rectangle 97"])
def test_source_and_absolute_modes_never_silently_drop_rotation(options, name):
    node = hairline()
    node["name"] = name
    with pytest.raises(UnsupportedFigmaFeature):
        figma_to_dds_schema(document(node), **options)


@pytest.mark.parametrize("width,height", [(1.01, 84), (12, 8), (0, 24), (24, 0), (0.5, 0.75)])
def test_rule_does_not_expand_to_general_non_square_rectangles_or_degenerate_boxes(width, height):
    with pytest.raises(UnsupportedFigmaFeature):
        figma_to_dds_schema(document(hairline(width=width, height=height)))


@pytest.mark.parametrize("path,value", [
    (("rotation",), 89), (("rotation",), 90.001), (("rotation",), 0), (("rotation",), 180),
    (("transform",), [[0, 1, 0], [1, 0, 0]]),  # reflected axes
    (("transform",), [[0, 2, 0], [-2, 0, 0]]),  # scaled axes
    (("transform",), [[0.1, 1, 0], [-1, 0, 0]]),
    (("transform",), None), (("transform", 0, 0), True),
    (("realFrame",), None), (("realFrame", "width"), 1), (("realFrame", "left"), 25),
    (("paths", 0, "frame", "width"), True), (("paths", 0, "frame", "left"), 18),
    (("paths", 0, "type"), "path"), (("paths", 0, "data"), "M0 0L1 84Z"),
    (("paths", 0, "radius", "topLeft"), 0.2), (("radius", "topLeft"), 0.2),
    (("shapeType",), "ellipse"), (("shapeType",), "polygon"),
    (("vectorPaths",), [{"data": "M0 0L1 84Z"}]),
    (("style", "fills"), []), (("style", "fills", 0, "type"), "gradient"),
    (("style", "fills", 0, "color", "a"), 0.5), (("style", "fills", 0, "opacity"), 0.5),
    (("opacity",), 0.5), (("style", "blendMode"), "multiply"),
    (("style", "fills", 0, "blendMode"), "screen"),
    (("style", "borders"), [{"isEnabled": True, "width": 1}]),
    (("style", "shadows"), [{"isEnabled": True, "opacity": 1}]),
    (("style", "blurs"), [{"isEnabled": True, "opacity": 1}]),
    (("style", "filter"), "blur(1px)"), (("clipped",), True), (("isMask",), True),
    (("layers",), [layer("child", (0, 0, 2, 2))]),
])
def test_unverified_geometry_and_additional_paint_remain_explicit_errors(path, value):
    node = hairline()
    target = node
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = deepcopy(value)
    with pytest.raises(UnsupportedFigmaFeature):
        figma_to_dds_schema(document(node))


def test_even_symmetric_rounded_strips_and_multiple_envelopes_remain_unsupported():
    node = hairline()
    node["radius"] = node["paths"][0]["radius"] = dict.fromkeys(node["radius"], 0.25)
    with pytest.raises(UnsupportedFigmaFeature):
        figma_to_dds_schema(document(node))
    node = hairline()
    node["paths"].append(deepcopy(node["paths"][0]))
    with pytest.raises(UnsupportedFigmaFeature):
        figma_to_dds_schema(document(node))


def test_a_real_export_still_precedes_compatibility_projection():
    node = hairline()
    node["hasExportDDSImage"] = True
    node["ddsImage"] = {"imageUrl": "https://assets.example/real-strip.png"}
    converted = find(figma_to_dds_schema(document(node)), node["id"])
    assert converted["type"] == "lanhuimage"
    assert "ddsRotatedHairlineProjection" not in converted
    assert not converted.get("conversionWarnings")


def swapped_wrapper(*, reflected=True, nested=False):
    wrapper = layer("transparent-wrapper", (80, 120, 54, 6))
    wrapper["rotation"] = 270.0000025
    wrapper["transform"] = [[4.3711388e-8, -1, 880],
                            [-1 if reflected else 1, -4.3711388e-8, -80]]
    wrapper["realFrame"] = transformed_bounds(wrapper)
    raster = layer("baked-image", (74, 95.25, 0.25, 6))
    raster["hasExportDDSImage"] = True
    raster["ddsImage"] = {"imageUrl": "https://assets.example/baked-arrow.png"}
    # This resource has already been transformed by the native exporter.
    raster["rotation"] = wrapper["rotation"]
    raster["transform"] = deepcopy(wrapper["transform"])
    raster["realFrame"] = transformed_bounds(raster)
    if nested:
        inner = deepcopy(wrapper)
        inner["id"] = inner["name"] = "inner-wrapper"
        inner["layers"] = [raster]
        wrapper["layers"] = [inner]
    else:
        wrapper["layers"] = [raster]
    return wrapper


@pytest.mark.parametrize("reflected", [False, True])
@pytest.mark.parametrize("nested", [False, True])
def test_verified_transparent_swapped_axes_do_not_reapply_baked_image_transform(reflected, nested):
    wrapper = swapped_wrapper(reflected=reflected, nested=nested)
    source = document(wrapper)
    before = deepcopy(source)
    schema = figma_to_dds_schema(source)
    assert source == before
    image = find(schema, "baked-image")
    assert image["type"] == "lanhuimage"
    assert image["rowDims"] == {"left": 74, "top": 96, "width": 1, "height": 6}
    assert image["props"]["src"] == "https://assets.example/baked-arrow.png"
    assert find(schema, "transparent-wrapper") is None
    assert find(schema, "inner-wrapper") is None
    assert not image.get("ddsRotatedHairlineProjection")
    files = generate_design_files(schema)
    assert "transform:" not in files["index.css"]
    assert 'src="https://assets.example/baked-arrow.png"' in files["index.html"]


@pytest.mark.parametrize("options", [{"layout": "absolute"}, {"border_layout": "source"},
                                      {"layout": "absolute", "border_layout": "source"}])
def test_new_swapped_wrapper_support_is_confined_to_dds_inference(options):
    with pytest.raises(UnsupportedFigmaFeature, match="rotation without an exported image"):
        figma_to_dds_schema(document(swapped_wrapper()), **options)


@pytest.mark.parametrize("feature", ["text", "vector", "ordinary-image", "empty-wrapper"])
def test_every_visible_terminal_in_swapped_wrapper_must_be_an_explicit_dds_export(feature):
    wrapper = swapped_wrapper()
    extra = layer("unbaked", (75, 90, 5, 8))
    if feature == "text":
        extra["type"] = "textLayer"
        extra["text"] = {"value": "live text"}
    elif feature == "vector":
        extra = hairline()
    elif feature == "ordinary-image":
        extra["hasExportImage"] = True
        extra["image"] = {"imageUrl": "https://assets.example/ordinary.png"}
    wrapper["layers"].append(extra)
    with pytest.raises(UnsupportedFigmaFeature, match="rotation without an exported image"):
        figma_to_dds_schema(document(wrapper))


@pytest.mark.parametrize("nested", [False, True])
@pytest.mark.parametrize("feature", ["fill", "border", "shadow", "blur", "clip", "opacity", "mask", "blend", "unknown-filter"])
def test_any_unbaked_wrapper_paint_or_scope_prevents_transform_elision(feature, nested):
    wrapper = swapped_wrapper(nested=nested)
    target = wrapper["layers"][0] if nested else wrapper
    if feature in {"fill", "border", "shadow", "blur"}:
        target["style"][{"fill": "fills", "border": "borders", "shadow": "shadows", "blur": "blurs"}[feature]] = [
            {"isEnabled": True, "opacity": 1, "type": "color", "width": 1,
             "color": {"r": 1, "g": 0, "b": 0, "a": 1}}]
    elif feature == "clip":
        target["clipped"] = True
    elif feature == "opacity":
        target["opacity"] = 0.5
    elif feature == "mask":
        target["isMask"] = True
    elif feature == "blend":
        target["style"]["blendMode"] = "multiply"
    else:
        target["style"]["filter"] = "blur(2px)"
    with pytest.raises(UnsupportedFigmaFeature):
        figma_to_dds_schema(document(wrapper))


@pytest.mark.parametrize("feature", ["scale", "shear", "general-rotation", "near-quarter", "missing-real", "wrong-real", "bool-matrix"])
def test_wrapper_requires_unit_swapped_axes_and_independent_aabb_corroboration(feature):
    wrapper = swapped_wrapper()
    if feature == "scale":
        wrapper["transform"] = [[0, -2, 880], [-2, 0, -80]]
    elif feature == "shear":
        wrapper["transform"][0][0] = 0.1
    elif feature == "general-rotation":
        wrapper["rotation"] = 30
        wrapper["transform"] = [[math.cos(math.pi / 6), -0.5, 880], [0.5, math.cos(math.pi / 6), -80]]
    elif feature == "near-quarter":
        wrapper["rotation"] = 269.999
    elif feature == "missing-real":
        wrapper.pop("realFrame")
    elif feature == "wrong-real":
        wrapper["realFrame"] = deepcopy(wrapper["frame"])
    else:
        wrapper["transform"][0][0] = True
    # Even a consistent AABB cannot make scale/shear/general rotation eligible.
    if feature in {"scale", "shear", "general-rotation"}:
        wrapper["realFrame"] = transformed_bounds(wrapper)
    with pytest.raises(UnsupportedFigmaFeature):
        figma_to_dds_schema(document(wrapper))
