"""End-to-end regressions from independent, small Figma export examples."""

from copy import deepcopy
from html.parser import HTMLParser
from io import BytesIO
import re

from PIL import Image
import pytest

from lanhu_codegen import generate_design_files
from lanhu_codegen.figma_schema import figma_to_dds_schema


def color(red=0, green=0, blue=0):
    return {"r": red, "g": green, "b": blue, "a": 1}


def layer(identity, box, *, children=(), paint=None, kind="groupLayer"):
    return {
        "id": identity, "name": identity, "type": kind, "visible": True,
        "opacity": 1, "frame": dict(zip(("left", "top", "width", "height"), box)),
        "style": {"isEnabled": True, "opacity": 1, "blendMode": 0,
                  "fills": [] if paint is None else [{"type": "color", "isEnabled": True,
                                                       "opacity": 1, "color": color(*paint)}],
                  "borders": [], "shadows": [], "blurs": []},
        "layers": list(children),
    }


def document(*children, width=300, height=240):
    root = layer("root", (0, 0, width, height), children=children, paint=(1, 1, 1), kind="artboard")
    root["origin"] = "figma"
    return {"meta": {"host": {"name": "figma"}}, "artboard": root}


def text_layer(identity, content, box):
    result = layer(identity, box, kind="textLayer")
    result["text"] = {"value": content, "style": {
        "font": {"postScriptName": "monospace", "name": "monospace", "size": 16,
                 "fontWeight": 400, "verticalAlignment": "top", "align": "left",
                 "lineHeight": {"unit": "PIXELS", "value": 20},
                 "letterSpacing": {"unit": "PIXELS", "value": 0}},
        "color": color(),
    }}
    return result


def image_layer(identity, x, *, dds=False):
    result = layer(identity, (x, 0, 16, 16))
    marker, resource = ("hasExportDDSImage", "ddsImage") if dds else ("hasExportImage", "image")
    result[marker] = True
    result[resource] = {"imageUrl": f"https://example.test/{identity}.png"}
    return result


def descendants(node):
    yield node
    for child in node["children"]:
        yield from descendants(child)


def find(root, identity):
    return next(node for node in descendants(root) if node["layerId"] == identity)


class ParsedHTML(HTMLParser):
    """Decode exactly what a browser text node receives, including entities."""

    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.elements = []
        self.stack = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        element = {"tag": tag, "attrs": dict(attrs), "text": ""}
        self.elements.append(element)
        if tag == "br":
            self.handle_data("\n")
        elif tag not in {"meta", "link", "img", "input", "hr"}:
            self.stack.append(element)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index]["tag"] == tag:
                del self.stack[index:]
                break

    def handle_data(self, value):
        for element in self.stack:
            element["text"] += value

    def by_class(self, name):
        return next(element for element in self.elements
                    if name in element["attrs"].get("class", "").split())


def css_rule(files, node):
    selector = re.escape(node["props"]["className"])
    match = re.search(r"\." + selector + r"\s*\{([^}]*)\}", files["index.css"])
    assert match, f"missing generated CSS for {selector}"
    return dict(part.strip().split(":", 1) for part in match[1].split(";") if part.strip())


def px(value):
    assert re.fullmatch(r"\s*-?[\d.]+(?:px)?\s*", value), value
    return float(value.strip().removesuffix("px"))


def edge(rule, name, side):
    explicit = rule.get(f"{name}-{side}")
    if explicit is not None:
        return px(explicit)
    values = rule.get(name, "0").split()
    if len(values) == 1:
        values *= 4
    elif len(values) == 2:
        values *= 2
    elif len(values) == 3:
        values.append(values[1])
    return px(values[("top", "right", "bottom", "left").index(side)])


@pytest.mark.parametrize("axis", ["row", "column"])
def test_unequal_gaps_keep_actual_css_positions(axis):
    boxes = [(offset, 0, 10, 10) if axis == "row" else (0, offset, 10, 10)
             for offset in (0, 20, 90)]
    raw = document(*(layer(f"child-{i}", box, paint=(i / 2, 0, 1)) for i, box in enumerate(boxes)),
                   width=100 if axis == "row" else 20, height=20 if axis == "row" else 100)
    schema = figma_to_dds_schema(raw)
    files = generate_design_files(schema)
    parent_markup = ParsedHTML(files["index.html"]).by_class(schema["props"]["className"])
    classes = parent_markup["attrs"]["class"].split()
    assert f"flex-{'row' if axis == 'row' else 'col'}" in classes
    assert "justify-between" not in classes
    assert css_rule(files, schema).get("justify-content", "").strip() != "space-between"
    side, dimension = ("left", "width") if axis == "row" else ("top", "height")
    positions, cursor = [], 0
    for i in range(3):
        rule = css_rule(files, find(schema, f"child-{i}"))
        cursor += edge(rule, "margin", side)
        positions.append(cursor)
        cursor += px(rule[dimension])
    assert positions == [0, 20, 90]


def test_explicit_newline_and_tab_survive_final_official_html():
    content = "alpha\tbeta\n<gamma>"
    schema = figma_to_dds_schema(document(text_layer("text", content, (0, 0, 240, 40))))
    files = generate_design_files(schema)
    text = find(schema, "text")
    assert ParsedHTML(files["index.html"]).by_class(text["props"]["className"])["text"] == content
    rule = css_rule(files, text)
    assert rule["white-space"].strip() == "pre-wrap"
    assert px(rule["line-height"]) == 20
    assert text["props"]["lines"] == 2


def test_wrapped_text_preserves_breakable_ascii_spaces():
    schema = figma_to_dds_schema(document(text_layer("wrapped", "alpha beta", (0, 0, 80, 40))))
    files = generate_design_files(schema)
    text = find(schema, "wrapped")
    decoded = ParsedHTML(files["index.html"]).by_class(text["props"]["className"])["text"]
    assert decoded == "alpha beta"
    assert "\u00a0" not in decoded
    rule = css_rule(files, text)
    assert rule["white-space"].strip() == "pre-wrap"
    assert rule["overflow-wrap"].strip() == "break-word"
    assert px(rule["width"]) == 80
    assert px(rule["font-size"]) == 16
    assert px(rule["line-height"]) == 20


def test_native_group_opacity_is_kept_as_one_compositing_boundary():
    parent = layer("translucent", (0, 0, 60, 40), children=[
        layer("back", (0, 0, 40, 40), paint=(1, 0, 0)),
        layer("front", (20, 0, 40, 40), paint=(0, 0, 1)),
    ])
    parent["opacity"] = 0.5  # Native export leaves style.opacity at its default 1.
    schema = figma_to_dds_schema(document(parent))
    files = generate_design_files(schema)
    group = find(schema, "translucent")
    assert [child["layerId"] for child in group["children"]] == ["back", "front"]
    assert float(css_rule(files, group)["opacity"]) == 0.5
    for child in group["children"]:
        assert float(css_rule(files, child).get("opacity", "1")) == 1


@pytest.mark.parametrize("overlapping", [False, True])
def test_uniform_inside_border_does_not_shift_child_twice(overlapping):
    children = [layer("child", (10, 10, 20, 20), paint=(1, 0, 0))]
    if overlapping:
        children.append(layer("overlap", (15, 15, 20, 20), paint=(0, 0, 1)))
    parent = layer("bordered", (0, 0, 100, 100), children=children, paint=(1, 1, 1))
    parent["style"]["borders"] = [{"isEnabled": True, "opacity": 1, "width": 10,
                                     "lineAlignment": "inside", "lineJoin": "miter", "lineCap": "none",
                                     "style": "solid", "color": color()}]
    schema = figma_to_dds_schema(document(parent), border_layout="source")
    files = generate_design_files(schema)
    parent_rule = css_rule(files, find(schema, "bordered"))
    child_rule = css_rule(files, find(schema, "child"))
    assert parent_rule["box-sizing"].strip() == "border-box"
    border_width = px(parent_rule["border"].split()[0])
    assert border_width == 10
    assert px(parent_rule["width"]) == 100
    if overlapping:
        assert child_rule["position"].strip() == "absolute"
        offset = (px(child_rule["left"]), px(child_rule["top"]))
    else:
        offset = (edge(child_rule, "margin", "left"), edge(child_rule, "margin", "top"))
    # CSS's containing/content block already begins inside the 10px border.
    assert (border_width + offset[0], border_width + offset[1]) == (10, 10)


def test_default_border_layout_matches_dds_outer_frame_offsets():
    child = layer("child", (12, 12, 20, 20), paint=(1, 0, 0))
    parent = layer("bordered", (0, 0, 100, 100), children=[child], paint=(1, 1, 1))
    parent["style"]["borders"] = [{"isEnabled": True, "opacity": 1, "width": 2,
                                  "lineAlignment": "inside", "color": color()}]
    raw = document(parent)
    dds = figma_to_dds_schema(raw)
    source = figma_to_dds_schema(raw, border_layout="source")
    actual = css_rule(generate_design_files(dds), find(dds, "child"))
    preserved = css_rule(generate_design_files(source), find(source, "child"))
    assert edge(actual, "margin", "left") == edge(actual, "margin", "top") == 12
    assert edge(preserved, "margin", "left") == edge(preserved, "margin", "top") == 10
    assert find(dds, "child")["rowDims"] == find(source, "child")["rowDims"]
    assert "outer-frame" in find(dds, "bordered")["conversionWarnings"][0]["reason"]


def test_dds_bordered_two_ended_row_distributes_inner_gap_with_outer_edge_margins():
    parent = layer("control", (0, 0, 100, 40), children=[
        layer("left", (10, 10, 20, 20), paint=(1, 0, 0)),
        layer("right", (80, 10, 10, 20), paint=(0, 0, 1)),
    ], paint=(1, 1, 1))
    parent["style"]["borders"] = [{"isEnabled": True, "opacity": 1, "width": 1,
                                  "lineAlignment": "inside", "color": color()}]
    schema = figma_to_dds_schema(document(parent))
    files = generate_design_files(schema)
    markup = ParsedHTML(files["index.html"]).by_class(find(schema, "control")["props"]["className"])
    assert "justify-between" in markup["attrs"]["class"].split()
    assert re.search(r"\.justify-between\s*\{[^}]*justify-content:\s*space-between;", files["common.css"])
    assert css_rule(files, find(schema, "control")).get("justify-content", "space-between").strip() == "space-between"
    left, right = css_rule(files, find(schema, "left")), css_rule(files, find(schema, "right"))
    assert edge(left, "margin", "left") == edge(right, "margin", "right") == 10
    assert edge(right, "margin", "left") == 0


@pytest.mark.parametrize("dds", [False, True])
def test_optional_composition_keeps_images_when_png_is_not_one_times(dds):
    raw = document(image_layer("asset-a", 0, dds=dds), image_layer("asset-b", 36, dds=dds),
                   width=100, height=100)
    before = deepcopy(raw)
    stream = BytesIO()
    Image.new("RGBA", (32, 32), (0, 0, 255, 255)).save(stream, format="PNG")
    calls = []
    def load_asset(url):
        calls.append(url)
        return stream.getvalue()
    schema = figma_to_dds_schema(raw, asset_loader=load_asset)
    assert raw == before
    images = [node for node in descendants(schema) if node["type"] == "lanhuimage"]
    assert [node["layerId"] for node in images] == ["asset-a", "asset-b"]
    files = generate_design_files(schema)
    for image in images:
        assert image["props"]["src"] == f"https://example.test/{image['layerId']}.png"
        rule = css_rule(files, image)
        assert px(rule["width"]) == px(rule["height"]) == 16
    if dds:
        assert calls, "DDS mismatch must exercise the failed-composition fallback"
        assert any(node.get("layoutWarnings") for node in descendants(schema))


def test_complete_parent_export_survives_unrepresentable_parent_effect():
    parent = layer("complete-parent", (0, 0, 50, 50), children=[image_layer("dds-child", 10, dds=True)])
    parent["hasExportImage"] = True
    parent["image"] = {"imageUrl": "https://example.test/complete-parent.png"}
    parent["style"]["shadows"] = [{"type": "outer", "isEnabled": True, "opacity": 1,
                                     "offsetX": 2, "offsetY": 2, "blur": 4, "spread": 0, "color": color()}]
    raw = document(parent)
    before = deepcopy(raw)
    schema = figma_to_dds_schema(raw)
    assert raw == before
    image = find(schema, "complete-parent")
    assert image["type"] == "lanhuimage"
    assert image["children"] == []
    assert image["props"]["src"] == parent["image"]["imageUrl"]
    assert not any(node["layerId"] == "dds-child" for node in descendants(schema))
    assert image.get("conversionWarnings"), "fallback must remain diagnosable"
    files = generate_design_files(schema)
    markup = ParsedHTML(files["index.html"]).by_class(image["props"]["className"])
    assert markup["tag"] == "img"
    assert markup["attrs"]["src"] == parent["image"]["imageUrl"]
