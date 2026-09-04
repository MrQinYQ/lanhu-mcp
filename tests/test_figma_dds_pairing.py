"""Generic role/geometry tests; no sample IDs, text, assets, or network access."""

from copy import deepcopy

import pytest

from lanhu_codegen.figma_dds_pairing import (
    checkbox_layer_ids, compact_source_pairs, contextual_pairing_exclusions,
    pair_dds_image_text, repeated_view_layer_ids,
)
from lanhu_codegen.figma_layout import _image_text_pairs


def node(identity, box, kind="lanhublock", *, style=None, children=()):
    left, top, width, height = box
    result = {
        "id": identity, "layerId": identity, "type": kind,
        "rowDims": dict(zip(("left", "top", "width", "height"), box)),
        "props": {"style": {"width": width, "height": height, **(style or {})}},
        "data": {"value": identity}, "uiType": "", "children": list(children),
    }
    if kind == "lanhuimage":
        result["props"]["src"] = f"https://assets.example/{identity}.png"
    elif kind == "lanhutext":
        result["props"].update(text=identity, lines=1)
        result["props"]["style"].update(lineHeight=height, fontSize=14, whiteSpace="nowrap")
    return result


def text_icon(*, gap=15, icon_size=12, text_height=22, scale=1):
    text_width = 56
    box = lambda values: tuple(value * scale for value in values)
    return [
        node("copy", box((0, 0, text_width, text_height)), "lanhutext"),
        node("suffix", box((text_width + gap, (text_height - icon_size) / 2, icon_size, icon_size)), "lanhuimage"),
    ]


def pairs(nodes):
    return [node for node in nodes if node.get("uiType") == "ImageText"]


@pytest.mark.parametrize("gap", [11, 15])
def test_nearby_suffix_icons_form_text_first_pairs_without_changing_input(gap):
    nodes = text_icon(gap=gap)
    before = deepcopy(nodes)
    result = pair_dds_image_text(nodes)
    assert nodes == before
    assert len(result) == 1
    pair = result[0]
    assert pair["uiType"] == "ImageText"
    assert pair["rowDims"] == {"left": 0, "top": 0, "width": 56 + gap + 12, "height": 22}
    assert [child["layerId"] for child in pair["children"]] == ["copy", "suffix"]
    assert pair["children"][0]["uiType"] == "TextGroup"
    assert pair["props"]["style"]["display"] == "flex"
    assert pair["props"]["style"]["flexDirection"] == "row"
    assert pair["children"][1]["props"]["style"]["marginTop"] == 5
    assert [child["rowDims"] for child in pair["children"]] == [child["rowDims"] for child in nodes]
    assert pair_dds_image_text(result) == result


@pytest.mark.parametrize("gap", [23, 32])
def test_distant_range_separators_and_search_suffixes_remain_independent(gap):
    nodes = text_icon(gap=gap)
    assert pair_dds_image_text(nodes) == nodes


@pytest.mark.parametrize("scale", [0.5, 1, 2])
@pytest.mark.parametrize("gap,expected", [(15, True), (23, False)])
def test_suffix_gap_rule_scales_with_text_and_icon_geometry(scale, gap, expected):
    assert bool(pairs(pair_dds_image_text(text_icon(gap=gap, scale=scale)))) is expected


@pytest.mark.parametrize("box", [(71, 5, 12, 13), (71, 7, 12, 12), (71, -6, 34, 34), (71, -1, 24, 24)])
def test_suffix_must_be_small_square_centered_and_no_taller_than_text(box):
    nodes = text_icon()
    nodes[1] = node("suffix", box, "lanhuimage")
    assert pair_dds_image_text(nodes) == nodes


def test_normal_fourteen_pixel_left_icon_is_still_an_image_text_pair():
    nodes = [node("ordinary-icon", (0, 4, 14, 14), "lanhuimage"),
             node("label", (22, 0, 56, 22), "lanhutext")]
    before = deepcopy(nodes)
    result = pair_dds_image_text(nodes)
    assert nodes == before
    assert result == _image_text_pairs(deepcopy(nodes))
    assert [child["layerId"] for child in result[0]["children"]] == ["ordinary-icon", "label"]


def test_original_left_helper_default_and_accept_all_have_identical_behavior():
    nodes = [node("ordinary-icon", (0, 4, 14, 14), "lanhuimage"),
             node("label", (22, 0, 56, 22), "lanhutext")]
    assert _image_text_pairs(deepcopy(nodes)) == _image_text_pairs(deepcopy(nodes), accept_image=lambda _: True)


def test_checkbox_role_inherits_through_source_wrappers_and_component_exports():
    checked_image = {"id": "checked-pixels", "type": "artboard", "layers": []}
    wrapper = {"id": "wrapper", "layers": [checked_image]}
    checked_label = {"id": "checked-label", "type": "textLayer", "layers": []}
    checked = {"id": "checked-control", "componentGroup": "checkbox", "layers": [wrapper, checked_label]}
    unchecked = {"id": "unchecked-pixels", "componentGroup": ".checkbox-input", "layers": []}
    unrelated = {"id": "unrelated", "name": "checkbox", "componentGroup": "Button", "layers": [],
                 "componentProperties": {"选中": {"type": "VARIANT", "value": "true"}}}
    source = {item["id"]: item for item in [checked, wrapper, checked_image, checked_label, unchecked, unrelated]}
    before = deepcopy(source)
    assert checkbox_layer_ids(source) == {"checked-control", "wrapper", "checked-pixels", "checked-label", "unchecked-pixels"}
    assert source == before
    # Text, names, role-neutral component metadata and source mapping order do
    # not establish a checkbox; the role survives renamed display layers.
    checked["name"] = "arbitrary component label"
    wrapper["name"] = "renamed nesting"
    assert "checked-pixels" in checkbox_layer_ids(dict(reversed(list(source.items()))))
    assert "unrelated" not in checkbox_layer_ids(source)


def test_source_ids_join_indexed_descendants_without_using_display_names():
    source = {
        "control": {"id": "control", "componentGroup": "checkbox", "layers": [{"id": "container"}]},
        "container": {"id": "container", "layers": [{"id": "pixels"}]},
        "pixels": {"id": "pixels", "layers": []},
    }
    assert checkbox_layer_ids(source) == {"control", "container", "pixels"}


def test_checkbox_glyph_does_not_pair_with_own_or_previous_item_label():
    nodes = [node("previous-label", (0, 0, 28, 22), "lanhutext"),
             node("checkbox-pixels", (44, 4, 14, 14), "lanhuimage"),
             node("own-label", (66, 0, 28, 22), "lanhutext")]
    assert pair_dds_image_text(nodes, excluded_image_ids={"checkbox-pixels"}) == nodes


def test_excluded_checkbox_remains_a_paint_obstacle_for_other_left_pairs():
    nodes = [node("icon", (0, 4, 14, 14), "lanhuimage"),
             node("checkbox", (16, 5, 12, 12), "lanhuimage"),
             node("label", (22, 0, 28, 22), "lanhutext")]
    assert not pairs(pair_dds_image_text(nodes, excluded_image_ids={"checkbox"}))
    assert not pairs(_image_text_pairs(deepcopy(nodes), accept_image=lambda node: node["layerId"] != "checkbox"))


def test_excluded_checkbox_remains_a_paint_obstacle_for_suffix_pairs():
    nodes = text_icon()
    nodes.insert(1, node("checkbox", (59, 5, 12, 12), "lanhuimage"))
    assert not pairs(pair_dds_image_text(nodes, excluded_image_ids={"checkbox"}))


@pytest.mark.parametrize("obstacle", [
    node("shadow", (100, 0, 10, 10), style={"boxShadow": "-40px 0 5px 0 rgba(0,0,0,0.5)"}),
    node("escaped", (100, 0, 10, 10), children=[node("ink", (59, 2, 12, 12))]),
    node("unresolved", (100, 0, 10, 10), style={"filter": "blur(var(--blur))"}),
])
def test_full_paint_or_unknown_effect_blocks_suffix_grouping(obstacle):
    nodes = text_icon()
    nodes.insert(1, deepcopy(obstacle))
    assert not pairs(pair_dds_image_text(nodes))


def test_suffix_source_order_is_preserved_and_reverse_source_pair_is_not_created():
    nodes = list(reversed(text_icon()))
    assert pair_dds_image_text(nodes) == nodes


def test_nearest_suffix_wins_when_source_order_lists_a_more_distant_icon_first():
    nodes = [node("text", (0, 0, 56, 22), "lanhutext"),
             node("farther", (68, 5, 12, 12), "lanhuimage"),
             node("nearest", (56, 5, 12, 12), "lanhuimage")]
    result = pair_dds_image_text(nodes)
    assert len(result) == 2
    assert [child["layerId"] for child in result[0]["children"]] == ["text", "nearest"]
    assert result[1]["layerId"] == "farther"


def test_effectful_image_is_not_misclassified_as_a_suffix_icon():
    nodes = text_icon()
    nodes[1]["props"]["style"]["opacity"] = 0.5
    assert pair_dds_image_text(nodes) == nodes


@pytest.mark.parametrize("icon_size,text_height", [(24, 22), (18, 16)])
def test_leading_icon_can_exceed_its_centered_text_line_box_by_two_pixels(icon_size, text_height):
    nodes = [node("icon", (0, 0, icon_size, icon_size), "lanhuimage"),
             node("text", (icon_size + 8, 1, 56, text_height), "lanhutext")]
    before = deepcopy(nodes)
    result = pair_dds_image_text(nodes)
    assert nodes == before
    assert len(result) == 1 and result[0]["uiType"] == "ImageText"
    assert result[0]["rowDims"]["height"] == icon_size
    assert result[0]["children"][1]["props"]["style"]["marginTop"] == 1
    assert [c["rowDims"] for c in result[0]["children"]] == [n["rowDims"] for n in nodes]


def test_larger_leading_icon_keeps_the_same_exclusions_and_full_paint_guard():
    nodes = [node("icon", (0, 0, 24, 24), "lanhuimage"),
             node("text", (32, 1, 56, 22), "lanhutext")]
    assert pair_dds_image_text(nodes, excluded_image_ids={"icon"}) == nodes
    obstacle = node("shadow", (100, 0, 10, 10), style={"boxShadow": "-72px 0 3px 0 black"})
    assert not pairs(pair_dds_image_text([nodes[0], obstacle, nodes[1]]))


@pytest.mark.parametrize("size,text_height", [(26, 22), (34, 32)])
def test_leading_icon_height_tolerance_does_not_admit_large_avatars(size, text_height):
    nodes = [node("icon", (0, 0, size, size), "lanhuimage"),
             node("text", (size + 8, (size - text_height) / 2, 56, text_height), "lanhutext")]
    assert not pairs(pair_dds_image_text(nodes))


def source_node(identity, box, *, kind="artboard", children=(), paint=False, raster=False):
    return {
        "id": identity, "name": "irrelevant display name", "type": kind,
        "frame": dict(zip(("left", "top", "width", "height"), box)),
        "visible": True, "opacity": 1, "layers": list(children),
        "hasExportDDSImage": raster,
        "ddsImage": {"imageUrl": "https://assets.example/shared-icon.png"} if raster else None,
        "style": {"isEnabled": True, "fills": [
            {"type": "color", "isEnabled": True, "opacity": 1, "color": {"a": 1, "r": 1, "g": 1, "b": 1}}
        ] if paint else []},
    }


def source_view(identity, x, y, *, width=300, height=200):
    def control(suffix, cx, cy):
        return source_node(identity + suffix, (cx, cy, 60, 24), children=[
            source_node(identity + suffix + "-icon", (cx, cy, 16, 16), raster=True),
            source_node(identity + suffix + "-text", (cx + 20, cy, 40, 22), kind="textLayer"),
        ])
    header = source_node(identity + "-header", (x, y, width, 30), paint=True,
                         children=[control("-heading-content", x + 4, y + 3)])
    left = source_node(identity + "-left", (x, y + 30, 70, height - 30), paint=True,
                       children=[control("-nav-a", x + 2, y + 36), control("-nav-b", x + 2, y + 68)])
    right = source_node(identity + "-right", (x + 80, y + 40, width - 90, height - 50), paint=True,
                        children=[control("-body-a", x + 84, y + 44), control("-body-b", x + 84, y + 76)])
    return source_node(identity, (x, y, width, height), children=[header, left, right], paint=True)


def source_index(*children):
    root = source_node("source-canvas", (-1000, 900, 2000, 1000), children=children)
    def walk(node):
        yield node
        for child in node.get("layers", []):
            yield from walk(child)
    return {node["id"]: node for node in walk(root)}


@pytest.mark.parametrize("count", [2, 3])
def test_repeated_complete_views_exclude_only_their_descendants_not_independent_examples(count):
    views = [source_view(f"view-{index}", 20 + index * 320, 40) for index in range(count)]
    standalone = source_node("outside-icon", (20, 300, 24, 24), raster=True)
    source = source_index(*views, standalone)
    before = deepcopy(source)
    excluded = repeated_view_layer_ids(source)
    expected = set(source) - {"source-canvas", "outside-icon"}
    assert excluded == expected
    assert source == before
    # The URL is deliberately identical inside and outside the views.
    assert source["outside-icon"]["ddsImage"] == source["view-0-nav-a-icon"]["ddsImage"]
    inside_pair = [node("view-0-nav-a-icon", (0, 3, 16, 16), "lanhuimage"),
                   node("label", (24, 0, 56, 22), "lanhutext")]
    assert not pairs(pair_dds_image_text(inside_pair, excluded_image_ids=excluded))
    outside_pair = [node("outside-icon", (0, 0, 24, 24), "lanhuimage"),
                    node("outside-label", (32, 1, 56, 22), "lanhutext")]
    assert len(pairs(pair_dds_image_text(outside_pair, excluded_image_ids=excluded))) == 1


def test_single_complete_view_retains_ordinary_pairing():
    assert repeated_view_layer_ids(source_index(source_view("only-view", 20, 40))) == set()


@pytest.mark.parametrize("second_x,second_y,width,height", [
    (350, 40, 310, 200), (350, 40, 300, 210), (250, 40, 300, 200), (350, 41, 300, 200),
])
def test_differing_size_vertical_band_or_overlap_does_not_establish_repeated_scope(second_x, second_y, width, height):
    source = source_index(source_view("first", 20, 40),
                          source_view("second", second_x, second_y, width=width, height=height))
    assert repeated_view_layer_ids(source) == set()


@pytest.mark.parametrize("scale", [0.5, 2])
def test_repeated_scope_uses_structure_and_relative_geometry_not_canvas_or_view_size(scale):
    source = source_index(source_view("first", 20, 40), source_view("second", 350, 40))
    for item in source.values():
        item["frame"] = {key: value * scale + (700 if key == "left" else -300 if key == "top" else 0)
                         for key, value in item["frame"].items()}
        item["name"] = "renamed"
    assert repeated_view_layer_ids(source) == set(source) - {"source-canvas"}


def test_repeated_large_cards_or_buttons_do_not_establish_view_scope_without_header_and_body():
    cards = [source_node(f"card-{i}", (i * 400, 0, 300, 200), paint=True, children=[
        source_node(f"card-{i}-icon", (i * 400, 0, 16, 16), raster=True),
        source_node(f"card-{i}-label", (i * 400 + 24, 0, 56, 22), kind="textLayer"),
    ]) for i in range(3)]
    assert repeated_view_layer_ids(source_index(*cards)) == set()


@pytest.mark.parametrize("mutation", ["narrow-header", "one-body-column", "overlapping-body", "shallow-card", "rasterized-view", "invisible-view"])
def test_complete_view_requires_live_full_width_header_and_nested_nonoverlapping_body_partitions(mutation):
    first, second = source_view("first", 20, 40), source_view("second", 350, 40)
    if mutation == "narrow-header":
        second["layers"][0]["frame"]["width"] -= 10
    elif mutation == "one-body-column":
        second["layers"].pop()
    elif mutation == "overlapping-body":
        second["layers"][2]["frame"]["left"] = 400
    elif mutation == "shallow-card":
        for partition in second["layers"][1:]:
            partition["layers"] = [child for wrapper in partition["layers"] for child in wrapper["layers"]]
    elif mutation == "rasterized-view":
        second["hasExportDDSImage"] = True
    else:
        second["visible"] = False
    assert repeated_view_layer_ids(source_index(first, second)) == set()


def scrim_view():
    view = source_view("view", 20, 40)
    card = source_node("card", (104, 88, 150, 94), paint=True, children=[
        source_node("card-heading", (112, 96, 110, 22), children=[
            source_node("card-icon", (112, 99, 16, 16), raster=True),
            source_node("card-text", (136, 96, 78, 22), kind="textLayer"),
        ]),
        source_node("card-second-line", (112, 140, 110, 22), kind="textLayer"),
    ])
    card["style"]["borders"] = [{"isEnabled": True, "opacity": 1, "lineAlignment": "inside",
                                  "style": "solid", "width": 1,
                                  "widths": dict.fromkeys(("left", "right", "top", "bottom"), 1),
                                  "color": {"a": 1}}]
    button = source_node("explicit-button", (104, 190, 130, 24), children=[
        source_node("button-icon", (110, 194, 16, 16), raster=True),
        source_node("button-text", (134, 191, 90, 22), kind="textLayer"),
    ], paint=True)
    button["componentGroup"] = "Button"
    view["layers"][2]["layers"].extend([card, button])
    scrim = source_node("scrim", (20, 40, 300, 200), kind="shapeLayer", paint=True)
    scrim["style"]["fills"][0]["opacity"] = 0.35
    scrim["style"]["fills"][0]["color"]["a"] = 0.35
    scrim["paths"] = [{"type": "rect", "frame": deepcopy(scrim["frame"]),
                       "radius": dict.fromkeys(("topLeft", "topRight", "bottomLeft", "bottomRight"), 0)}]
    # The Button exception is only evidenced when a later opaque foreground
    # fully covers it. Uncovered/partially covered controls have separate tests.
    foreground = source_node("foreground", (100, 100, 200, 120), paint=True, children=[
        source_node("foreground-icon", (148, 110, 16, 16), raster=True),
        source_node("foreground-text", (172, 107, 60, 22), kind="textLayer"),
    ])
    view["layers"].extend([scrim, foreground])
    return view


@pytest.mark.parametrize("scale", [0.5, 1, 2])
def test_scrim_background_rule_preserves_independent_bordered_cards_explicit_buttons_and_foreground(scale):
    source = source_index(scrim_view(), source_node("outside", (0, 300, 16, 16), raster=True))
    for item in source.values():
        item["frame"] = {key: value * scale + (900 if key == "left" else -300 if key == "top" else 0)
                         for key, value in item["frame"].items()}
        item["name"] = "unrelated renamed item"
        for path in item.get("paths", []):
            path["frame"] = deepcopy(item["frame"])
    before = deepcopy(source)
    excluded = contextual_pairing_exclusions(source)
    assert source == before
    assert {"view-nav-a-icon", "view-nav-b-icon", "view-body-a-icon", "view-body-b-icon"} <= excluded
    assert not ({"card-icon", "button-icon", "foreground-icon", "outside"} & excluded)
    assert contextual_pairing_exclusions(dict(reversed(list(source.items())))) == excluded


@pytest.mark.parametrize("mutation", ["no-scrim", "partial", "opaque", "transparent", "hidden", "effect", "no-header", "no-foreground", "foreground-before"])
def test_no_context_exclusion_without_a_real_full_view_scrim_sequence(mutation):
    view = scrim_view()
    scrim = view["layers"][-2]
    if mutation == "no-scrim":
        view["layers"].remove(scrim)
    elif mutation == "partial":
        scrim["frame"]["width"] -= 1
        scrim["paths"][0]["frame"] = deepcopy(scrim["frame"])
    elif mutation in {"opaque", "transparent"}:
        value = 1 if mutation == "opaque" else 0
        scrim["style"]["fills"][0].update(opacity=value, color={"a": value})
    elif mutation == "hidden":
        scrim["visible"] = False
    elif mutation == "effect":
        scrim["style"]["shadows"] = [{"isEnabled": True}]
    elif mutation == "no-header":
        view["layers"].pop(0)
    elif mutation == "no-foreground":
        view["layers"].pop()
    else:
        view["layers"][-2:] = reversed(view["layers"][-2:])
    assert contextual_pairing_exclusions(source_index(view)) == set()


@pytest.mark.parametrize("mutation", ["no-border", "partial-border", "one-line", "transparent", "clip"])
def test_a_painted_box_alone_does_not_establish_an_independent_multiline_card(mutation):
    source = source_index(scrim_view())
    card = source["card"]
    if mutation == "no-border":
        card["style"]["borders"] = []
    elif mutation == "partial-border":
        card["style"]["borders"][0]["widths"]["right"] = 0
    elif mutation == "one-line":
        card["layers"].pop()
    elif mutation == "transparent":
        card["style"]["fills"] = []
    else:
        card["clipped"] = True
    assert "card-icon" in contextual_pairing_exclusions(source)


def test_button_display_name_without_explicit_component_role_does_not_escape_scrim_scope():
    source = source_index(scrim_view())
    button = source["explicit-button"]
    button.pop("componentGroup")
    button["name"] = "Button"
    assert "button-icon" in contextual_pairing_exclusions(source)


def wide_field():
    return source_node("field-label", (10, 20, 180, 22), children=[
        source_node("field-text", (10, 20, 40, 22), kind="textLayer"),
        source_node("field-icon", (56, 25, 12, 12), raster=True),
    ])


@pytest.mark.parametrize("width", [140, 230])
def test_wide_transparent_two_leaf_field_label_keeps_suffix_as_independent_row_item(width):
    parent = wide_field()
    parent["frame"]["width"] = width
    source = source_index(parent)
    before = deepcopy(source)
    assert contextual_pairing_exclusions(source) == {"field-icon"}
    assert source == before


@pytest.mark.parametrize("mutation", ["tight", "left-icon", "paint", "clip", "shadow", "opacity", "third-leaf", "offset", "nested-paint", "unknown-filter"])
def test_field_label_rule_does_not_generalize_to_navigation_controls_or_unknown_paint_scopes(mutation):
    parent = wide_field()
    if mutation == "tight":
        parent["frame"]["width"] = 100
    elif mutation == "left-icon":
        parent["layers"].reverse()
        parent["layers"][0]["frame"]["left"] = 10
        parent["layers"][1]["frame"]["left"] = 30
    elif mutation == "paint":
        parent["style"]["fills"] = source_node("dummy", (0, 0, 1, 1), paint=True)["style"]["fills"]
    elif mutation == "clip":
        parent["clipped"] = True
    elif mutation == "shadow":
        parent["style"]["shadows"] = [{"isEnabled": True}]
    elif mutation == "opacity":
        parent["opacity"] = 0.5
    elif mutation == "third-leaf":
        parent["layers"].append(source_node("extra", (80, 20, 24, 22), kind="textLayer"))
    elif mutation == "offset":
        parent["layers"][1]["frame"]["top"] += 3
    elif mutation == "nested-paint":
        parent["layers"][0] = source_node("painted-text-wrapper", (10, 20, 40, 22), paint=True,
                                          children=[parent["layers"][0]])
    else:
        parent["style"]["filter"] = "blur(1px)"
    assert contextual_pairing_exclusions(source_index(parent)) == set()


def compact_pair_source():
    parent = wide_field()
    parent["frame"]["width"] = 58
    return source_index(parent)


def compact_dds_nodes():
    return [node("field-text", (10, 20, 40, 22), "lanhutext"),
            node("field-icon", (56, 25, 12, 12), "lanhuimage")]


def test_compact_source_evidence_uses_geometry_and_order_without_mutating_input():
    source = compact_pair_source()
    before = deepcopy(source)
    assert compact_source_pairs(source) == {("field-text", "field-icon")}
    assert source == before
    source["field-label"]["layers"].reverse()
    assert compact_source_pairs(source) == {("field-icon", "field-text")}


@pytest.mark.parametrize("feature", ["padding", "paint", "clip", "shadow", "filter", "transform", "ordinary-image", "third-child", "not-direct"])
def test_compact_evidence_requires_an_explicit_tight_transparent_two_leaf_parent(feature):
    source = compact_pair_source()
    parent = source["field-label"]
    if feature == "padding":
        parent["frame"]["width"] += 1
    elif feature == "paint":
        parent["style"]["fills"] = [{"type": "color", "color": {"a": 1}}]
    elif feature == "clip":
        parent["clipped"] = True
    elif feature == "shadow":
        parent["style"]["shadows"] = [{"isEnabled": True}]
    elif feature == "filter":
        parent["style"]["filter"] = "blur(2px)"
    elif feature == "transform":
        parent["transform"] = [[1, 0.1, 0], [0, 1, 0]]
    elif feature == "ordinary-image":
        source["field-icon"].update(hasExportDDSImage=False, hasExportImage=True)
    elif feature == "third-child":
        parent["layers"].append(source_node("third", (15, 22, 4, 4), raster=True))
    else:
        parent["layers"][0] = source_node("nested", (10, 20, 40, 22), children=[parent["layers"][0]])
    assert compact_source_pairs(source) == set()


@pytest.mark.parametrize("position", ["before", "after"])
def test_compact_adjacent_pair_can_preserve_paint_from_an_external_known_shadow(position):
    nodes = compact_dds_nodes()
    shadow = node("dropdown", (10, 46, 60, 70), style={"boxShadow": "0px 4px 10px 0px rgba(0,0,0,0.1)"})
    shadow["style"] = deepcopy(shadow["props"]["style"])
    nodes.insert(0, shadow) if position == "before" else nodes.append(shadow)
    before = deepcopy(nodes)
    evidence = compact_source_pairs(compact_pair_source())
    assert not pairs(pair_dds_image_text(nodes))  # Existing default is unchanged.
    result = pair_dds_image_text(nodes, compact_pairs=evidence)
    assert nodes == before
    assert len(pairs(result)) == 1
    expected_order = ["dropdown", "field-text", "field-icon"] if position == "before" else ["field-text", "field-icon", "dropdown"]
    flattened = [child["layerId"] for item in result
                 for child in (item["children"] if item.get("uiType") == "ImageText" else [item])]
    assert flattened == expected_order
    pair = pairs(result)[0]
    assert pair["rowDims"] == {"left": 10, "top": 20, "width": 58, "height": 22}
    assert [child["rowDims"] for child in pair["children"]] == [item["rowDims"] for item in compact_dds_nodes()]
    assert next(item for item in result if item.get("layerId") == "dropdown") == shadow


@pytest.mark.parametrize("position", ["before", "after"])
@pytest.mark.parametrize("kind", ["solid", "escaped-child", "shadow-and-solid"])
def test_compact_exception_never_ignores_external_real_ink_or_escaped_children(position, kind):
    nodes = compact_dds_nodes()
    if kind == "escaped-child":
        obstacle = node("obstacle", (10, 70, 60, 40), children=[
            node("escaped-ink", (45, 20, 4, 22), style={"backgroundColor": "red"}),
        ])
    else:
        obstacle = node("obstacle", (40, 28, 8, 8), style={"backgroundColor": "red"})
        if kind == "shadow-and-solid":
            obstacle["props"]["style"]["boxShadow"] = "0px 4px 10px 0px rgba(0,0,0,0.1)"
    nodes.insert(0, obstacle) if position == "before" else nodes.append(obstacle)
    before = deepcopy(nodes)
    assert not pairs(pair_dds_image_text(nodes, compact_pairs=compact_source_pairs(compact_pair_source())))
    assert nodes == before


@pytest.mark.parametrize("feature", ["intervening", "unknown-before", "unknown-after", "excluded", "reverse-evidence", "oversized", "off-center", "far-gap"])
def test_compact_evidence_never_bypasses_unknown_or_intervening_paint_and_icon_constraints(feature):
    nodes = compact_dds_nodes()
    shadow = node("dropdown", (10, 46, 60, 70), style={"boxShadow": "0px 4px 10px 0px rgba(0,0,0,0.1)"})
    evidence = compact_source_pairs(compact_pair_source())
    excluded = set()
    if feature == "intervening":
        nodes.insert(1, shadow)
    elif feature in {"unknown-before", "unknown-after"}:
        shadow["props"]["style"]["filter"] = "blur(var(--missing))"
        nodes.insert(0, shadow) if feature == "unknown-before" else nodes.append(shadow)
    else:
        nodes.append(shadow)
        if feature == "excluded":
            excluded.add("field-icon")
        elif feature == "reverse-evidence":
            evidence = {("field-icon", "field-text")}
        elif feature == "oversized":
            nodes[1]["rowDims"].update(width=34, height=34)
        elif feature == "off-center":
            nodes[1]["rowDims"]["top"] += 3
        else:
            nodes[1]["rowDims"]["left"] += 40
    assert not pairs(pair_dds_image_text(nodes, compact_pairs=evidence, excluded_image_ids=excluded))
