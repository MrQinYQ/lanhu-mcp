"""Paired Figma/DDS acceptance plus identity and geometry metamorphic checks.

Only four original exported PNGs enter the converter through an in-memory
loader. Official schemas, generated goldens and merged PNGs are test oracles;
the conversion call is forbidden from reading any fixture from disk.
"""

import base64
from collections import Counter
from copy import deepcopy
from html.parser import HTMLParser
import io
import json
import os
from pathlib import Path
import re
from unittest.mock import patch

from PIL import Image
import pytest

from lanhu_codegen import generate_design_files
from lanhu_codegen.figma_schema import UnsupportedFigmaFeature, figma_to_dds_schema


FIXTURES = Path(__file__).parent / "fixtures"
OFFICIAL = FIXTURES / "official_no_permission"
COMPOSITES = FIXTURES / "figma_composites"
CSS_FILES = {"common.css", "index.css", "index.rem.css", "index.response.css"}
SYNTHETIC = re.compile(r"^(row|col|rect)_")


def walk(node, child_key="children"):
    yield node
    for child in node.get(child_key, []):
        yield from walk(child, child_key)


def convert_without_fixture_access(raw, assets):
    """Prove conversion receives sources only, never any official oracle."""
    calls = []

    def load(url):
        assert url in assets, f"Unexpected image source requested: {url}"
        calls.append(url)
        return assets[url]

    def guard(original):
        def open_file(file, *args, **kwargs):
            if isinstance(file, (str, bytes, os.PathLike)):
                path = os.path.abspath(os.fsdecode(file))
                assert not path.startswith(str(FIXTURES.resolve()) + os.sep), "Conversion attempted to read a test fixture"
            return original(file, *args, **kwargs)
        return open_file

    import builtins
    before = deepcopy(raw)
    with patch("builtins.open", guard(builtins.open)), patch("io.open", guard(io.open)):
        schema = figma_to_dds_schema(raw, asset_loader=load)
    assert raw == before
    assert Counter(calls) == Counter(assets.keys())  # Exactly four source reads, once each.
    return schema


@pytest.fixture(scope="module")
def paired():
    raw = json.loads((FIXTURES / "figma_no_permission" / "v5.json").read_text())
    reference = json.loads((OFFICIAL / "schema.json").read_text())
    source_files = {
        "253:37592": "header-left.png", "253:37596": "header-right.png",
        "259:7474": "illustration-ground.png", "259:7475": "illustration-lock.png",
    }
    # IDs are only fixture lookup metadata; the converter sees URLs and bytes.
    assets = {
        layer["ddsImage"]["imageUrl"]: (COMPOSITES / source_files[layer["id"]]).read_bytes()
        for layer in walk(raw["artboard"], "layers") if layer.get("id") in source_files
    }
    assert len(assets) == 4
    actual = convert_without_fixture_access(raw, assets)
    return {"raw": raw, "assets": assets, "reference": reference, "actual": actual,
            "reference_files": generate_design_files(reference), "actual_files": generate_design_files(actual)}


def assert_tree_contract(reference, actual, path="root"):
    for field in ("type", "componentName", "uiType", "rowDims"):
        assert actual.get(field) == reference.get(field), (path, field)
    assert actual["props"]["className"] == reference["props"]["className"], path
    if SYNTHETIC.match(reference["layerId"]):
        # Deterministic generated suffixes replace the official random suffixes.
        assert actual["layerId"].split("_", 1)[0] == reference["layerId"].split("_", 1)[0], path
    else:
        assert actual["layerId"] == reference["layerId"], path
    assert len(actual["children"]) == len(reference["children"]), path
    for index, (expected_child, actual_child) in enumerate(zip(reference["children"], actual["children"])):
        assert_tree_contract(expected_child, actual_child, f"{path}/children/{index}")


class ImageSources(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.sources = {}
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag == "img":
            attrs = dict(attrs)
            assert attrs["class"] not in self.sources
            self.sources[attrs["class"]] = attrs["src"]


def test_inferred_tree_matches_all_38_official_nodes_and_four_css_files(paired):
    assert len(list(walk(paired["reference"]))) == len(list(walk(paired["actual"]))) == 38
    assert_tree_contract(paired["reference"], paired["actual"])
    expected, actual = paired["reference_files"], paired["actual_files"]
    assert {name for name in expected if name.endswith(".css")} == CSS_FILES
    assert set(actual) == set(expected)
    # The three independently captured official outputs also freeze the oracle.
    for name in ("index.html", "index.css", "common.css"):
        assert expected[name].encode("utf-8") == (OFFICIAL / name).read_bytes(), name
    for name in CSS_FILES:
        assert actual[name].encode("utf-8") == expected[name].encode("utf-8"), name


def test_html_diff_is_exactly_two_composite_sources_with_other_11_urls_unchanged(paired):
    expected_html = paired["reference_files"]["index.html"]
    actual_html = paired["actual_files"]["index.html"]
    expected_sources = ImageSources(expected_html).sources
    actual_sources = ImageSources(actual_html).sources
    assert len(expected_sources) == len(actual_sources) == 13
    assert actual_sources.keys() == expected_sources.keys()
    changed = {name for name in expected_sources if actual_sources[name] != expected_sources[name]}
    assert changed == {"image_3", "image_4"}
    input_sources = {
        layer["ddsImage"]["imageUrl"] for layer in walk(paired["raw"]["artboard"], "layers")
        if isinstance(layer.get("ddsImage"), dict) and layer["ddsImage"].get("imageUrl")
    }
    for name in expected_sources.keys() - changed:
        assert actual_sources[name] == expected_sources[name]
        assert actual_sources[name] in input_sources
    normalized = actual_html
    for name in changed:
        assert actual_sources[name].startswith("data:image/png;base64,")
        assert actual_html.count(actual_sources[name]) == 1
        normalized = normalized.replace(actual_sources[name], expected_sources[name], 1)
    # No whitespace, styles, DOM or non-source attribute differences are allowed.
    assert normalized.encode("utf-8") == expected_html.encode("utf-8")


@pytest.mark.parametrize("class_name,filename", [("image_3", "header-official.png"), ("image_4", "illustration-official.png")])
def test_composite_data_uri_has_exact_official_rgba_pixels(paired, class_name, filename):
    images = {node["props"]["className"]: node for node in walk(paired["actual"]) if node["type"] == "lanhuimage"}
    composite = images[class_name]
    prefix, encoded = composite["props"]["src"].split(",", 1)
    assert prefix == "data:image/png;base64"
    assert composite["data"]["value"] == composite["props"]["src"]
    with Image.open(io.BytesIO(base64.b64decode(encoded, validate=True))) as image:
        actual = image.convert("RGBA")
    with Image.open(COMPOSITES / filename) as image:
        reference = image.convert("RGBA")
    assert actual.size == reference.size
    assert actual.tobytes() == reference.tobytes()
    assert len(composite["sourceLayerIds"]) == 2


def structure_signature(node, *, offset=(0, 0), root=True):
    dims = deepcopy(node["rowDims"])
    if not root:
        dims["left"] -= offset[0]
        dims["top"] -= offset[1]
    return {"type": node["type"], "uiType": node["uiType"], "rowDims": dims,
            "className": node["props"]["className"],
            "children": [structure_signature(child, offset=offset, root=False) for child in node["children"]]}


def replace_text(content):
    # Preserve length and whitespace so this mutation changes no supplied font
    # metrics, run boundaries or line count; only the literal wording changes.
    return "".join(character if character.isspace() else "Z" for character in content)


def rename_layers(raw, *, rename_shapes=False, declare_shapes=False):
    renamed = deepcopy(raw)
    ids = {}
    originals = list(walk(raw["artboard"], "layers"))
    for index, layer in enumerate(walk(renamed["artboard"], "layers")):
        ids[layer["id"]] = f"independent-source-{index}"
        layer["id"] = ids[layer["id"]]
        if layer["type"] != "shapeLayer" or rename_shapes:
            # Ordinary nodes, including image containers, receive no name hint.
            layer["name"] = f"unrelated-object-{index}"
        if declare_shapes and layer["type"] == "shapeLayer":
            # Only original rectangle declarations may acquire an explicit type;
            # VECTOR paths also say 'rect' despite having lost their geometry.
            original = originals[index]
            if re.match(r"^(?:Rectangle|矩形)(?:\s|$)", original.get("name", "")):
                layer["shapeType"] = "rectangle"
        if "text" in layer:
            layer["text"]["value"] = replace_text(layer["text"]["value"])
            for style in [layer["text"].get("style", {}), *layer["text"].get("styles", [])]:
                if "content" in style:
                    style["content"] = replace_text(style["content"])
    return renamed, ids


@pytest.mark.parametrize("explicit_shapes", [False, True])
def test_all_ids_text_and_supported_layer_names_can_change_without_changing_grouping(paired, explicit_shapes):
    mutated, ids = rename_layers(paired["raw"], rename_shapes=explicit_shapes, declare_shapes=explicit_shapes)
    actual = convert_without_fixture_access(mutated, paired["assets"])
    assert structure_signature(actual) == structure_signature(paired["actual"])
    original_nodes, actual_nodes = list(walk(paired["actual"])), list(walk(actual))
    for before, after in zip(original_nodes, actual_nodes):
        if before["layerId"] in ids:
            assert after["layerId"] == ids[before["layerId"]]
        if before["type"] == "lanhuimage":
            assert after["props"]["src"] == before["props"]["src"]
        if before["type"] == "lanhutext":
            assert after["props"]["text"] != before["props"]["text"]
        if "sourceLayerIds" in before:
            assert after["sourceLayerIds"] == [ids[layer_id] for layer_id in before["sourceLayerIds"]]
    files = generate_design_files(actual)
    for name in CSS_FILES:
        assert files[name] == paired["actual_files"][name], name


def test_renaming_untyped_bare_shapes_explicitly_reports_missing_geometry(paired):
    # This export loses real vector paths and tags every shape path as 'rect'.
    # A bare Rectangle name is currently the parser's only weak shape hint.
    # Arbitrary renaming cannot manufacture reliable geometry; do not silently
    # infer a rectangle from this example's dimensions or its original layer ID.
    mutated, _ = rename_layers(paired["raw"], rename_shapes=True)
    before = deepcopy(mutated)
    with pytest.raises(UnsupportedFigmaFeature, match="missing vector geometry"):
        figma_to_dds_schema(mutated, asset_loader=paired["assets"].__getitem__)
    assert mutated == before


@pytest.mark.parametrize("dx,dy", [(37, 19), (-17, -29)])
def test_translating_all_non_root_frames_preserves_grouping_and_composite_pixels(paired, dx, dy):
    translated = deepcopy(paired["raw"])
    for layer in list(walk(translated["artboard"], "layers"))[1:]:
        layer["frame"]["left"] += dx
        layer["frame"]["top"] += dy
        if isinstance(layer.get("text", {}).get("frame"), dict):
            layer["text"]["frame"]["left"] += dx
            layer["text"]["frame"]["top"] += dy
    actual = convert_without_fixture_access(translated, paired["assets"])
    assert structure_signature(actual, offset=(dx, dy)) == structure_signature(paired["actual"])
    original_images = [node["props"]["src"] for node in walk(paired["actual"]) if node["type"] == "lanhuimage"]
    actual_images = [node["props"]["src"] for node in walk(actual) if node["type"] == "lanhuimage"]
    assert actual_images == original_images
