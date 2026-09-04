"""The public source-layout branch must preserve source paint ordering.

These are generic counterexamples to frame-only DDS partitioning. Assertions
inspect the final official HTML/CSS, so merely dispatching to a named helper
cannot satisfy the contract.
"""

from copy import deepcopy
from html.parser import HTMLParser
import re

import pytest

from lanhu_codegen import generate_design_files
from lanhu_codegen.figma_schema import figma_to_dds_schema


def layer(identity, box, color, *, children=()):
    return {
        "id": identity, "name": identity, "type": "artboard", "visible": True,
        "opacity": 1, "rotation": 0, "clipped": False, "isMask": False,
        "frame": dict(zip(("left", "top", "width", "height"), box)),
        "realFrame": dict(zip(("left", "top", "width", "height"), box)),
        "transform": [[1, 0, box[0]], [0, 1, box[1]]],
        "style": {"isEnabled": True, "opacity": 1, "blendMode": 0,
                  "fills": [{"type": "color", "isEnabled": True, "opacity": 1,
                             "color": dict(zip(("r", "g", "b", "a"), (*color, 1)))}],
                  "borders": [], "shadows": [], "blurs": []},
        "layers": list(children),
    }


def document(*children):
    root = layer("root", (0, 0, 240, 180), (1, 1, 1), children=children)
    root["origin"] = "figma"
    return {"meta": {"host": {"name": "figma"}}, "artboard": root}


def walk(node):
    yield node
    for child in node["children"]:
        yield from walk(child)


def find(root, identity):
    return next(node for node in walk(root) if node["layerId"] == identity)


def css_rule(files, node):
    selector = re.escape(node["props"]["className"])
    match = re.search(r"\." + selector + r"\s*\{([^}]*)\}", files["index.css"])
    assert match is not None
    return {key.strip(): value.strip() for key, value in
            (part.split(":", 1) for part in match[1].split(";") if part.strip())}


class DivTree(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.parents = {}
        self.order = []
        self.stack = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag != "div":
            return
        classes = dict(attrs).get("class", "").split()
        assert classes
        identity = classes[0]
        self.parents[identity] = self.stack[-1] if self.stack else None
        self.order.append(identity)
        self.stack.append(identity)

    def handle_endtag(self, tag):
        if tag == "div":
            self.stack.pop()


@pytest.mark.parametrize("axis", ["horizontal", "vertical"])
def test_source_branch_keeps_a_later_box_above_an_earlier_displaced_shadow(axis):
    if axis == "horizontal":
        first_box, second_box, x, y = (100, 20, 20, 20), (0, 20, 20, 20), -100, 0
    else:
        first_box, second_box, x, y = (20, 100, 20, 20), (20, 0, 20, 20), 0, -100
    first = layer("earlier-shadow", first_box, (0, 1, 0))
    first["style"]["shadows"] = [{
        "isEnabled": True, "blendMode": 0, "opacity": 1,
        "x": x, "y": y, "blur": 0, "spread": 0, "inset": False,
        "color": {"r": 1, "g": 0, "b": 0, "a": 1},
    }]
    second = layer("later-blue", second_box, (0, 0, 1))
    raw = document(first, second)
    before = deepcopy(raw)
    schema = figma_to_dds_schema(raw, border_layout="source")
    assert raw == before
    assert [child["layerId"] for child in schema["children"]] == ["earlier-shadow", "later-blue"]
    files = generate_design_files(schema)
    earlier, later = find(schema, "earlier-shadow"), find(schema, "later-blue")
    ec, lc = css_rule(files, earlier), css_rule(files, later)
    assert ec["position"] == lc["position"] == "absolute"
    assert int(ec["z-index"]) < int(lc["z-index"])
    assert "box-shadow" in ec and "100px" in ec["box-shadow"]
    assert lc["background-color"] == "rgba(0, 0, 255, 1)"
    for item, original in ((earlier, first), (later, second)):
        rule = css_rule(files, item)
        for axis in ("left", "top"):
            value = original["frame"][axis]
            assert rule[axis] == (f"{value}px" if value else "0")
    tree = DivTree(files["index.html"])
    early_class, late_class = earlier["props"]["className"], later["props"]["className"]
    assert tree.parents[early_class] == tree.parents[late_class] == schema["props"]["className"]
    assert tree.order.index(early_class) < tree.order.index(late_class)


def test_source_branch_keeps_positioned_descendants_inside_their_paint_scope():
    back = layer("red-child", (10, 10, 50, 20), (1, 0, 0))
    front = layer("green-child", (15, 15, 40, 20), (0, 1, 0))
    earlier = layer("earlier-parent", (10, 10, 20, 30), (1, 1, 0), children=[back, front])
    later = layer("later-blue", (40, 10, 30, 30), (0, 0, 1))
    raw = document(earlier, later)
    before = deepcopy(raw)
    schema = figma_to_dds_schema(raw, border_layout="source")
    assert raw == before
    files = generate_design_files(schema)
    parent, late = find(schema, "earlier-parent"), find(schema, "later-blue")
    red, green = find(schema, "red-child"), find(schema, "green-child")
    pc, lc, rc, gc = [css_rule(files, node) for node in (parent, late, red, green)]
    # Both original siblings need atomic positioned scopes. Otherwise the
    # parent's positive-z descendant escapes above the later static flex item.
    assert pc["position"] == lc["position"] == "absolute"
    assert int(pc["z-index"]) < int(lc["z-index"])
    assert rc["position"] == gc["position"] == "absolute"
    assert int(rc["z-index"]) < int(gc["z-index"])
    assert pc["left"] == pc["top"] == "10px"
    assert lc["left"] == "40px" and lc["top"] == "10px"
    assert rc["left"] == rc["top"] == "0"
    assert gc["left"] == gc["top"] == "5px"
    tree = DivTree(files["index.html"])
    parent_class, late_class = parent["props"]["className"], late["props"]["className"]
    assert tree.parents[parent_class] == tree.parents[late_class] == schema["props"]["className"]
    assert tree.parents[red["props"]["className"]] == tree.parents[green["props"]["className"]] == parent_class
    assert tree.order.index(parent_class) < tree.order.index(late_class)
