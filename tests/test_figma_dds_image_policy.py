"""Bound the lossy DDS compatibility projections for exported image layers.

These decisions reproduce observed DDS structure. In particular an empty raw
paint list does not establish that the exported bitmap has transparent pixels.
Source and absolute modes must retain the resource instead.
"""

from copy import deepcopy

import pytest

from lanhu_codegen.figma_schema import UnsupportedFigmaFeature, figma_to_dds_schema


URL = "https://example.com/original.png"


def exported(*, width=24, height=42, shape=False):
    frame = {"left": 27, "top": 39, "width": width, "height": height}
    corners = dict.fromkeys(("topLeft", "topRight", "bottomLeft", "bottomRight"), 5)
    return {"id": "arbitrary-source", "name": "unrelated-name", "type": "shapeLayer" if shape else "artboard",
            "frame": frame, "realFrame": deepcopy(frame), "visible": True, "opacity": 1,
            "clipped": False, "isMask": False, "rotation": 0,
            "transform": [[1, 0, 127], [0, 1, -261]],
            "radius": dict.fromkeys(corners, 0),
            "paths": [{"type": "rect", "frame": deepcopy(frame), "radius": corners}],
            "style": {"isEnabled": True, "opacity": 1, "blendMode": 0,
                      "fills": [], "borders": [], "shadows": [], "blurs": []},
            "layers": [], "hasExportDDSImage": True, "ddsImage": {"imageUrl": URL},
            "hasExportImage": False}


def document(node):
    return {"meta": {"host": {"name": "figma"}}, "assets": [], "artboard": {
        "id": "root", "name": "page", "type": "artboard", "origin": "figma",
        "frame": {"left": 100, "top": -300, "width": 400, "height": 300},
        "visible": True, "opacity": 1, "style": {"opacity": 1, "fills": [],
                                                  "borders": [], "shadows": [], "blurs": []},
        "layers": [node]}}


def walk(node):
    yield node
    for child in node.get("children", []):
        yield from walk(child)


def convert(node, **kwargs):
    raw = document(node)
    before, loads = deepcopy(raw), []

    def load(url):
        loads.append(url)
        raise AssertionError("These compatibility decisions must not inspect image pixels")

    result = figma_to_dds_schema(raw, asset_loader=load, **kwargs)
    assert raw == before and loads == []
    return result


def by_source(schema):
    return next(node for node in walk(schema) if node.get("layerId") == "arbitrary-source")


def test_exact_zero_width_dds_export_is_omitted_with_resource_diagnostic():
    source = exported(width=0, height=11)
    schema = convert(source)
    assert not any(node.get("layerId") == source["id"] for node in walk(schema))
    warning = next(w for w in schema["conversionWarnings"] if w["code"] == "dds_zero_width_image_omitted")
    assert warning["layerId"] == source["id"]
    assert warning["sourceFrame"] == source["frame"]
    assert warning["sourceImageUrl"] == URL


@pytest.mark.parametrize("options", [{"layout": "absolute"}, {"border_layout": "source"}])
def test_zero_width_resource_remains_in_source_preserving_modes(options):
    node = by_source(convert(exported(width=0, height=11), **options))
    assert node["type"] == "lanhuimage" and node["props"]["src"] == URL
    assert node["rowDims"]["width"] == 0


@pytest.mark.parametrize("width,height,expected_width", [(0.001, 6, 1), (8, 0, 8)])
def test_zero_width_rule_does_not_generalize_to_positive_fraction_or_zero_height(width, height, expected_width):
    node = by_source(convert(exported(width=width, height=height)))
    assert node["type"] == "lanhuimage" and node["props"]["src"] == URL
    assert node["rowDims"]["width"] == expected_width


def test_zero_width_marked_resource_is_validated_before_omission():
    source = exported(width=0)
    del source["ddsImage"]
    with pytest.raises(UnsupportedFigmaFeature, match="without ddsImage resource"):
        convert(source)


def test_ordinary_slice_fallback_does_not_report_omissions_from_abandoned_structure():
    source = exported(width=80, height=80)
    source.update(hasExportDDSImage=False, hasExportImage=True, image={"imageUrl": URL})
    zero = exported(width=0)
    zero["id"] = "zero-child"
    vector = exported(shape=True)
    vector.update(id="unsupported-child", hasExportDDSImage=False, hasExportImage=False)
    source["layers"] = [zero, vector]
    schema = convert(source)
    node = by_source(schema)
    assert node["type"] == "lanhuimage" and node["props"]["src"] == URL
    assert not any(w.get("code") == "dds_zero_width_image_omitted"
                   for item in walk(schema) for w in item.get("conversionWarnings", []))


@pytest.mark.parametrize("shape", [False, True])
def test_designer_slice_marker_prevents_lossy_image_compatibility_projection(shape):
    source = exported(shape=shape, width=24 if shape else 0)
    source.update(hasExportImage=True, image={"imageUrl": "https://example.com/designer.png"})
    node = by_source(convert(source))
    assert node["type"] == "lanhuimage" and node["props"]["src"] == URL


@pytest.mark.parametrize("radius", [3, 7])
def test_empty_exported_shape_uses_declared_rect_and_reports_discarded_bitmap(radius):
    source = exported(shape=True)
    source["paths"][0]["radius"] = dict.fromkeys(source["radius"], radius)
    node = by_source(convert(source))
    assert node["type"] == "lanhublock" and node["ddsEmptyShapeProjection"] is True
    assert "src" not in node["props"] and node["data"]["value"] == ""
    assert not ({"backgroundColor", "background", "border"} & node["props"]["style"].keys())
    assert node["rowDims"] == source["frame"]
    warning = next(w for w in node["conversionWarnings"] if w["code"] == "dds_empty_shape_projection")
    assert warning["sourceImageUrl"] == URL and warning["sourceFrame"] == source["frame"]
    assert "omits the exported image's pixels" in warning["reason"]


@pytest.mark.parametrize("options", [{"layout": "absolute"}, {"border_layout": "source"}])
def test_empty_exported_shape_keeps_bitmap_in_source_preserving_modes(options):
    node = by_source(convert(exported(shape=True), **options))
    assert node["type"] == "lanhuimage" and node["props"]["src"] == URL
    assert not node.get("ddsEmptyShapeProjection")


@pytest.mark.parametrize("paint", ["fills", "borders", "shadows", "blurs"])
def test_any_raw_paint_record_keeps_exported_shape_pixels(paint):
    source = exported(shape=True)
    # Even disabled/incomplete paint declarations are outside the observed
    # strict-empty predicate. The DDS bitmap already represents these records.
    source["style"][paint] = [{"isEnabled": False}]
    node = by_source(convert(source))
    assert node["type"] == "lanhuimage" and node["props"]["src"] == URL


@pytest.mark.parametrize("change", [
    lambda n: n.update(shapeType="rectangle"),
    lambda n: n.update(vectorPaths=[{"data": "M0,0 L1,1"}]),
    lambda n: n.update(clipped=True),
    lambda n: n.update(opacity=0.5),
    lambda n: n.update(rotation=0.1),
    lambda n: n.update(transform=[[1, 0.1, 0], [0, 1, 0]]),
    lambda n: n["paths"][0]["radius"].update(topLeft=6),
    lambda n: n["paths"][0].update(radius=dict.fromkeys(n["radius"], 0)),
    lambda n: n["paths"][0]["frame"].update(left=28),
    lambda n: n["realFrame"].update(width=25),
    lambda n: n["layers"].append(exported()),
])
def test_ambiguous_or_effectful_shapes_retain_their_exported_bitmap(change):
    source = exported(shape=True)
    change(source)
    node = by_source(convert(source))
    assert node["type"] == "lanhuimage" and node["props"]["src"] == URL
    assert not node.get("ddsEmptyShapeProjection")
