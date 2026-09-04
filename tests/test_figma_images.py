import base64
from copy import deepcopy
from io import BytesIO
from pathlib import Path

from PIL import Image
import pytest

from lanhu_codegen.figma_images import FigmaImageCompositionError, compose_image_nodes


FIXTURES = Path(__file__).parent / "fixtures" / "figma_composites"


def png(size, color):
    stream = BytesIO()
    Image.new("RGBA", size, color).save(stream, format="PNG")
    return stream.getvalue()


def node(layer_id, dims, src):
    return {
        "id": f"id-{layer_id}", "layerId": layer_id, "eleName": layer_id,
        "type": "lanhuimage", "componentName": "lanhuimage",
        "rowDims": dict(zip(("left", "top", "width", "height"), dims)),
        "style": {"left": dims[0], "top": dims[1], "width": dims[2], "height": dims[3]},
        "props": {"className": layer_id, "src": src, "style": {"inlineSize": "10.5px", "left": 99}},
        "data": {"value": src}, "children": [],
    }


def pixels(result):
    prefix, encoded = result["props"]["src"].split(",", 1)
    assert prefix == "data:image/png;base64"
    return Image.open(BytesIO(base64.b64decode(encoded))).convert("RGBA")


def test_source_over_alpha_order_and_input_unchanged():
    nodes = [node("back", (0, 0, 2, 1), "red"), node("front", (1, 0, 1, 1), "blue")]
    before = deepcopy(nodes)
    assets = {"red": png((2, 1), (255, 0, 0, 255)), "blue": png((1, 1), (0, 0, 255, 128))}
    result = compose_image_nodes(nodes, assets.__getitem__)
    assert nodes == before
    assert result["id"] == nodes[-1]["id"]
    assert result["layerId"] == "front"
    assert result["props"]["className"] == "front"
    assert result["sourceLayerIds"] == ["back", "front"]
    assert result["rowDims"] == {"left": 0, "top": 0, "width": 2, "height": 1}
    assert result["props"]["style"]["left"] == 0
    assert "inlineSize" not in result["props"]["style"]
    assert result["data"]["value"] == result["props"]["src"]
    image = pixels(result)
    assert [image.getpixel((x, 0)) for x in range(2)] == [(255, 0, 0, 255), (127, 0, 128, 255)]
    assert result["imageComposition"]["sources"][1]["rowDims"] == nodes[1]["rowDims"]
    assert result["imageComposition"]["sources"][1]["offset"] == {"left": 1, "top": 0}


def test_negative_fractional_bounds_are_ceiled_before_union():
    nodes = [node("a", (-1.4, -2.8, 1.1, 1.1), "a"), node("b", (1.2, -1.2, 1, 1), "b")]
    assets = {"a": png((2, 2), (20, 30, 40, 255)), "b": png((1, 1), (80, 90, 100, 255))}
    result = compose_image_nodes(nodes, assets.__getitem__)
    assert result["rowDims"] == {"left": -1, "top": -2, "width": 4, "height": 2}
    image = pixels(result)
    assert image.getpixel((0, 0)) == (20, 30, 40, 255)
    assert image.getpixel((2, 0)) == (0, 0, 0, 0)
    assert image.getpixel((3, 1)) == (80, 90, 100, 255)
    assert result["imageComposition"]["sources"][0]["rasterBounds"] == {
        "left": -1, "top": -2, "width": 2, "height": 2,
    }


@pytest.mark.parametrize("field,value", [("left", float("nan")), ("top", True), ("width", 0), ("height", -1)])
def test_invalid_dimensions_fail_before_loading(field, value):
    source = node("invalid", (0, 0, 1, 1), "asset")
    source["rowDims"][field] = value
    def loader(_):
        pytest.fail("invalid geometry must not load resources")
    with pytest.raises(FigmaImageCompositionError, match=f"rowDims.{field}"):
        compose_image_nodes([source], loader)


def test_mismatched_pixel_size_is_not_silently_resampled():
    with pytest.raises(FigmaImageCompositionError, match="PNG size.*does not match"):
        compose_image_nodes([node("wrong-size", (0, 0, 1, 1), "asset")], lambda _: png((2, 2), (0, 0, 0, 0)))


def test_sparse_giant_union_fails_without_allocating_or_loading():
    nodes = [node("first", (0, 0, 1, 1), "a"), node("distant", (10**9, 10**9, 1, 1), "b")]
    def loader(_):
        pytest.fail("impossible canvas must fail before resource reads")
    with pytest.raises(FigmaImageCompositionError, match="pixel limit"):
        compose_image_nodes(nodes, loader)


def test_non_png_resource_is_rejected():
    stream = BytesIO()
    Image.new("RGB", (1, 1)).save(stream, format="JPEG")
    with pytest.raises(FigmaImageCompositionError, match="expected a DDS PNG, got JPEG"):
        compose_image_nodes([node("not-png", (0, 0, 1, 1), "asset")], lambda _: stream.getvalue())


@pytest.mark.parametrize("content", [None, b"", b"not an image"])
def test_missing_or_invalid_resource_has_explicit_error(content):
    with pytest.raises(FigmaImageCompositionError, match="resource"):
        compose_image_nodes([node("bad-resource", (0, 0, 1, 1), "asset")], lambda _: content)


def test_loader_error_keeps_layer_identity_and_cause():
    def loader(_):
        raise OSError("unavailable")
    with pytest.raises(FigmaImageCompositionError, match="missing-layer.*resource loader failed") as caught:
        compose_image_nodes([node("missing-layer", (0, 0, 1, 1), "asset")], loader)
    assert isinstance(caught.value.__cause__, OSError)


def test_invalid_group_and_missing_source_are_rejected():
    with pytest.raises(FigmaImageCompositionError, match="empty"):
        compose_image_nodes([], lambda _: b"")
    with pytest.raises(FigmaImageCompositionError, match="lanhuimage"):
        compose_image_nodes([{"type": "lanhublock"}], lambda _: b"")
    source = node("no-url", (0, 0, 1, 1), "")
    with pytest.raises(FigmaImageCompositionError, match="props.src"):
        compose_image_nodes([source], lambda _: b"")


@pytest.mark.parametrize("name,sources,expected_dims", [
    ("header", [
        ("header-left.png", (1280, 280, 16, 16)),
        ("header-right.png", (1316, 280, 16, 16)),
    ], {"left": 1280, "top": 280, "width": 52, "height": 16}),
    ("illustration", [
        ("illustration-ground.png", (881.9765625, 675.75, 105, 33.773441314697266)),
        ("illustration-lock.png", (903.818359375, 631, 62.727272033691406, 64.18194580078125)),
    ], {"left": 882, "top": 631, "width": 105, "height": 79}),
])
def test_real_dds_exports_match_official_merged_pixels(name, sources, expected_dims):
    # These source/expected PNGs are public resources from the v5 design fixture.
    # Synthetic identities ensure the implementation cannot rely on sample IDs.
    inputs = [node(f"source-{index}", dims, filename) for index, (filename, dims) in enumerate(sources)]
    result = compose_image_nodes(inputs, lambda filename: (FIXTURES / filename).read_bytes())
    expected = Image.open(FIXTURES / f"{name}-official.png").convert("RGBA")
    actual = pixels(result)
    assert result["rowDims"] == expected_dims
    assert actual.size == expected.size
    assert actual.tobytes() == expected.tobytes()
