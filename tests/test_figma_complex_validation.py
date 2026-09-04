"""Visual/export parity for the second, complex design.

The first unchanged run failed on a shadow. These are capability-regression
checks after that failure, not proof of general or independent first-run parity.
The accepted contract permits consistent class renaming and pixel-identical
image URLs; structure, text and all remaining HTML/CSS must still match.
"""

import base64
from collections import Counter
from copy import deepcopy
import hashlib
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
from lanhu_codegen.figma_schema import figma_to_dds_schema


FIXTURE = Path(__file__).parent / "fixtures" / "figma_complex"


def walk(node, children="children"):
    yield node
    for child in node.get(children, []):
        yield from walk(child, children)


def original_nodes(schema, source_ids):
    result = {}
    for node in walk(schema):
        layer_id = node.get("layerId")
        if layer_id in source_ids:
            assert layer_id not in result, f"Duplicate original layer ID: {layer_id}"
            result[layer_id] = node
    return result


def convert_from_original_resources_only(raw, resources):
    input_urls = {
        node["ddsImage"]["imageUrl"] for node in walk(raw["artboard"], "layers")
        if isinstance(node.get("ddsImage"), dict) and node["ddsImage"].get("imageUrl")
    }
    calls = []

    def loader(url):
        assert url in input_urls, "Only URLs present in raw Figma exports may enter conversion"
        assert url in resources, "Only the two original composition PNGs are supplied"
        calls.append(url)
        return resources[url]

    def guarded(original):
        def open_file(file, *args, **kwargs):
            if isinstance(file, (str, bytes, os.PathLike)):
                path = os.path.abspath(os.fsdecode(file))
                fixture_root = str(FIXTURE.parent.resolve()) + os.sep
                assert not path.startswith(fixture_root), "Conversion must not read fixtures or official oracles from disk"
            return original(file, *args, **kwargs)
        return open_file

    import builtins
    before = deepcopy(raw)
    with patch("builtins.open", guarded(builtins.open)), patch("io.open", guarded(io.open)):
        actual = figma_to_dds_schema(raw, asset_loader=loader)
    assert raw == before
    assert Counter(calls) == Counter(resources.keys())
    assert len(calls) == 2
    return actual


@pytest.fixture(scope="module")
def paired():
    raw = json.loads((FIXTURE / "raw.json").read_text())
    reference = json.loads((FIXTURE / "official-schema.json").read_text())
    image_manifest = json.loads((FIXTURE / "image-resources.json").read_text())
    resources = {}
    for url, entry in image_manifest["sources"].items():
        data = (FIXTURE / entry["path"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == entry["sha256"]
        resources[url] = data
    assert len(resources) == 2
    assert image_manifest["expected_composite"]["url"] not in resources
    actual = convert_from_original_resources_only(raw, resources)
    source_ids = {node["id"] for node in walk(raw["artboard"], "layers")}
    return {
        "raw": raw, "reference": reference, "actual": actual, "source_ids": source_ids,
        "image_manifest": image_manifest,
        "reference_original": original_nodes(reference, source_ids),
        "actual_original": original_nodes(actual, source_ids),
        "reference_files": generate_design_files(reference), "actual_files": generate_design_files(actual),
    }


def test_fixture_provenance_locks_the_same_unmodified_input_version():
    metadata = json.loads((FIXTURE / "metadata.json").read_text())
    assert metadata["version"]["id"] == "7703002a-81e1-4653-9494-8638902c1f37"
    for name, expected_sha in metadata["sha256"].items():
        assert hashlib.sha256((FIXTURE / name).read_bytes()).hexdigest() == expected_sha


def test_all_original_layer_ids_types_and_global_bounds_are_preserved(paired):
    reference, actual = paired["reference_original"], paired["actual_original"]
    assert len(reference) == 122
    assert actual.keys() == reference.keys()
    for layer_id, expected in reference.items():
        assert actual[layer_id]["type"] == expected["type"], layer_id
        assert actual[layer_id]["rowDims"] == expected["rowDims"], layer_id


def structure_contract(node, original_ids, aliases=None):
    identity = node.get("layerId", "")
    original = identity in original_ids
    return {
        "identity": (aliases or {}).get(identity, identity) if original else identity.split("_", 1)[0],
        "type": node["type"], "componentName": node["componentName"],
        "uiType": node.get("uiType", ""), "rowDims": node["rowDims"],
        "children": [structure_contract(child, original_ids, aliases) for child in node.get("children", [])],
    }


def test_all_158_nodes_match_official_hierarchy_order_semantics_and_bounds(paired):
    assert len(list(walk(paired["actual"]))) == 158
    assert structure_contract(paired["actual"], paired["source_ids"]) == structure_contract(
        paired["reference"], paired["source_ids"])


def test_all_node_style_values_match_ignoring_only_rgba_number_spelling(paired):
    def normalize(value):
        if not isinstance(value, str):
            return value
        return re.sub(r"rgba\(([^)]+)\)", lambda match: "rgba(" + ",".join(
            str(float(part)) for part in match.group(1).split(",")) + ")", value)

    expected, actual = list(walk(paired["reference"])), list(walk(paired["actual"]))
    assert len(expected) == len(actual) == 158
    for reference, observed in zip(expected, actual):
        assert {k: normalize(v) for k, v in observed["props"]["style"].items()} == {
            k: normalize(v) for k, v in reference["props"]["style"].items()
        }, reference["props"]["className"]


def test_complex_inference_does_not_depend_on_source_ids_names_or_text_literals(paired):
    raw = deepcopy(paired["raw"])
    aliases = {}
    for index, node in enumerate(walk(raw["artboard"], "layers")):
        identity = f"renamed:{index}"
        aliases[identity] = node["id"]
        node["id"] = identity
        # Retain the weak rectangle-export hint needed when vector geometry is
        # missing. All other names and every literal text are arbitrary.
        if node.get("type") != "shapeLayer":
            node["name"] = f"Anonymous {index}"
        if node.get("type") == "textLayer":
            node["text"]["value"] = re.sub(r"[^\n\r\t ]", "X", node["text"]["value"])
    manifest = paired["image_manifest"]
    resources = {url: (FIXTURE / entry["path"]).read_bytes() for url, entry in manifest["sources"].items()}
    actual = convert_from_original_resources_only(raw, resources)
    assert structure_contract(actual, set(aliases), aliases) == structure_contract(
        paired["actual"], paired["source_ids"])
    assert [node["props"]["className"] for node in walk(actual)] == [
        node["props"]["className"] for node in walk(paired["actual"])]


def test_all_41_text_nodes_keep_content_lines_and_geometry(paired):
    reference = {node["layerId"]: node for node in walk(paired["reference"]) if node["type"] == "lanhutext"}
    actual = {node["layerId"]: node for node in walk(paired["actual"]) if node["type"] == "lanhutext"}
    assert len(reference) == 41
    assert actual.keys() == reference.keys()
    assert sum(node["type"] == "lanhutext" for node in walk(paired["actual"])) == len(reference)
    for layer_id, expected in reference.items():
        observed = actual[layer_id]
        assert observed["props"]["text"] == expected["props"]["text"], layer_id
        assert observed["props"]["lines"] == expected["props"]["lines"], layer_id
        assert observed["data"]["value"] == expected["data"]["value"], layer_id
        assert observed["rowDims"] == expected["rowDims"], layer_id


def test_all_46_image_identities_and_45_unmerged_urls_are_preserved(paired):
    reference = {node["layerId"]: node for node in walk(paired["reference"]) if node["type"] == "lanhuimage"}
    actual = {node["layerId"]: node for node in walk(paired["actual"]) if node["type"] == "lanhuimage"}
    assert len(reference) == 46
    assert actual.keys() == reference.keys()
    assert sum(node["type"] == "lanhuimage" for node in walk(paired["actual"])) == len(reference)
    composite_id = paired["image_manifest"]["expected_composite"]["layerId"]
    changed = {layer_id for layer_id in reference if actual[layer_id]["props"]["src"] != reference[layer_id]["props"]["src"]}
    assert changed == {composite_id}
    input_urls = {node["ddsImage"]["imageUrl"] for node in walk(paired["raw"]["artboard"], "layers")
                  if isinstance(node.get("ddsImage"), dict) and node["ddsImage"].get("imageUrl")}
    for layer_id in reference.keys() - changed:
        assert actual[layer_id]["props"]["src"] == reference[layer_id]["props"]["src"]
        assert actual[layer_id]["props"]["src"] in input_urls


def verified_composite_urls(paired):
    expected = paired["image_manifest"]["expected_composite"]
    composite = paired["actual_original"][expected["layerId"]]
    prefix, payload = composite["props"]["src"].split(",", 1)
    assert prefix == "data:image/png;base64"
    assert composite["data"]["value"] == composite["props"]["src"]
    assert len(composite["sourceLayerIds"]) == 2
    assert set(composite["sourceLayerIds"]) <= paired["source_ids"]
    expected_bytes = (FIXTURE / expected["path"]).read_bytes()
    assert hashlib.sha256(expected_bytes).hexdigest() == expected["sha256"]
    with Image.open(io.BytesIO(expected_bytes)) as image:
        assert image.format == "PNG" and image.n_frames == 1, "Reference must be a static PNG"
        reference = image.convert("RGBA")
    with Image.open(io.BytesIO(base64.b64decode(payload, validate=True))) as image:
        assert image.format == "PNG" and image.n_frames == 1, "Composite must be a static PNG"
        actual = image.convert("RGBA")
    assert actual.size == reference.size
    assert actual.tobytes() == reference.tobytes(), "Composite pixels differ"
    return {composite["props"]["src"]: expected["url"]}


def test_original_two_source_images_reconstruct_exact_official_composite_pixels(paired):
    verified_composite_urls(paired)


@pytest.mark.parametrize("name", ["index.html", "index.css", "common.css", "index.rem.css", "index.response.css"])
def test_official_ui_file_bytes_match_the_fixed_renderer_for_this_schema(paired, name):
    assert paired["reference_files"][name].encode("utf-8") == (FIXTURE / "official-ui" / name).read_bytes()


def normalize_html_names_and_sources(text, class_names, image_urls):
    """Change actual tag attributes only, preserving all other source bytes."""
    attribute = re.compile(r'''\s+[\w:-]+\s*=\s*(["']).*?\1''', re.DOTALL)
    line_offsets = [0, *(match.end() for match in re.finditer("\n", text))]
    replacements = []

    class Normalizer(HTMLParser):
        def handle_starttag(self, tag, attrs):
            original = self.get_starttag_text()

            def rewrite(match):
                token = match.group()
                name, quoted = token.split("=", 1)
                quote_position = len(quoted) - len(quoted.lstrip())
                value = quoted[quote_position + 1:-1]
                if name.strip().lower() == "class":
                    changed = re.sub(r"\S+", lambda word: class_names.get(word.group(), word.group()), value)
                elif tag == "img" and name.strip().lower() == "src":
                    changed = image_urls.get(value, value)
                else:
                    return token
                return name + "=" + quoted[:quote_position + 1] + changed + quoted[-1]

            changed = attribute.sub(rewrite, original)
            if changed != original:
                line, column = self.getpos()
                start = line_offsets[line - 1] + column
                replacements.append((start, start + len(original), changed))

        handle_startendtag = handle_starttag

    parser = Normalizer(convert_charrefs=False)
    parser.feed(text)
    parser.close()
    for start, end, changed in reversed(replacements):
        text = text[:start] + changed + text[end:]
    return text


def normalize_css_class_selectors(text, class_names):
    # The pinned generator emits one simple class selector per rule. Restrict
    # rewriting to those selector lines; declaration values are never changed.
    return re.sub(r"(?m)^([ \t]*)\.([\w-]+)([ \t]*\{[ \t]*$)",
                  lambda match: match[1] + "." + class_names.get(match[2], match[2]) + match[3], text)


def assert_accepted_export_parity(paired):
    assert structure_contract(paired["actual"], paired["source_ids"]) == structure_contract(
        paired["reference"], paired["source_ids"])
    actual_nodes = list(walk(paired["actual"]))
    reference_nodes = list(walk(paired["reference"]))
    actual_names = [node["props"]["className"] for node in actual_nodes]
    reference_names = [node["props"]["className"] for node in reference_nodes]
    assert len(actual_names) == len(reference_names)
    assert len(set(actual_names)) == len(actual_names), "Class-name collision in actual schema"
    assert len(set(reference_names)) == len(reference_names)
    class_names = dict(zip(actual_names, reference_names))
    image_urls = verified_composite_urls(paired)
    files = dict(paired["actual_files"])
    for url in image_urls:
        assert files["index.html"].count(url) == 1
    files["index.html"] = normalize_html_names_and_sources(files["index.html"], class_names, image_urls)
    for name in files.keys() - {"index.html"}:
        assert name.endswith(".css"), name
        files[name] = normalize_css_class_selectors(files[name], class_names)
    # User-approved allowance: names and verified image URLs only. Text,
    # structure, formatting, CSS properties, values and order remain exact.
    assert files == paired["reference_files"]


def test_full_official_html_css_parity_with_accepted_name_and_image_url_differences(paired):
    assert_accepted_export_parity(paired)


def test_name_normalization_does_not_rewrite_visible_text_or_css_values():
    names = {"block_1": "box_1"}
    html = '<div title=\'class="block_1"\' class="block_1 flex-col">class="block_1"<img src="old.png" /></div>'
    assert normalize_html_names_and_sources(html, names, {"old.png": "new.png"}) == (
        '<div title=\'class="block_1"\' class="box_1 flex-col">class="block_1"<img src="new.png" /></div>')
    css = '.block_1 {\n  content: ".block_1";\n  background: url("old.png");\n}\n'
    assert normalize_css_class_selectors(css, names) == css.replace('.block_1 {', '.box_1 {', 1)


@pytest.mark.parametrize("name,before,after", [
    ("index.css", "width:", "min-width:"),
    ("index.rem.css", "height:", "min-height:"),
    ("index.response.css", "position: relative;", "position: absolute;"),
    ("index.html", "</span>", "changed</span>"),
])
def test_accepted_parity_still_rejects_style_or_text_changes(paired, name, before, after):
    changed = {**paired, "actual_files": dict(paired["actual_files"])}
    assert before in changed["actual_files"][name]
    changed["actual_files"][name] = changed["actual_files"][name].replace(before, after, 1)
    with pytest.raises(AssertionError):
        assert_accepted_export_parity(changed)


def test_accepted_parity_rejects_a_different_composite_pixel(paired):
    changed = deepcopy(paired)
    composite = changed["actual_original"][changed["image_manifest"]["expected_composite"]["layerId"]]
    old_url = composite["props"]["src"]
    with Image.open(io.BytesIO(base64.b64decode(old_url.split(",", 1)[1]))) as original:
        image = original.convert("RGBA")
    r, g, b, alpha = image.getpixel((0, 0))
    image.putpixel((0, 0), (r ^ 255, g, b, alpha))
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    url = "data:image/png;base64," + base64.b64encode(stream.getvalue()).decode()
    composite["props"]["src"] = composite["data"]["value"] = url
    changed["actual_files"]["index.html"] = changed["actual_files"]["index.html"].replace(old_url, url, 1)
    with pytest.raises(AssertionError, match="Composite pixels differ"):
        assert_accepted_export_parity(changed)


def test_accepted_parity_rejects_animation_even_when_the_first_frame_matches(paired):
    changed = deepcopy(paired)
    composite = changed["actual_original"][changed["image_manifest"]["expected_composite"]["layerId"]]
    old_url = composite["props"]["src"]
    with Image.open(io.BytesIO(base64.b64decode(old_url.split(",", 1)[1]))) as original:
        first_frame = original.convert("RGBA")
    second_frame = Image.new("RGBA", first_frame.size, (255, 0, 0, 255))
    stream = io.BytesIO()
    first_frame.save(stream, format="PNG", save_all=True, append_images=[second_frame], duration=100, loop=0)
    url = "data:image/png;base64," + base64.b64encode(stream.getvalue()).decode()
    composite["props"]["src"] = composite["data"]["value"] = url
    changed["actual_files"]["index.html"] = changed["actual_files"]["index.html"].replace(old_url, url, 1)
    with pytest.raises(AssertionError, match="Composite must be a static PNG"):
        assert_accepted_export_parity(changed)
