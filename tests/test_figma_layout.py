"""Layout inference contracts use independent geometry, not the sample oracle."""

from copy import deepcopy

import pytest

from lanhu_codegen.figma_layout import infer_layout


def node(identity, x, y, width, height, *, kind="lanhublock", children=(), style=None, **extra):
    result = {"id": identity, "layerId": identity, "type": kind, "componentName": kind,
              "rowDims": {"left": x, "top": y, "width": width, "height": height},
              "props": {"className": identity, "style": {
                  "position": "absolute", "width": width, "height": height,
                  "left": x, "top": y, **(style or {})}},
              "data": {"value": ""}, "children": list(children), **extra}
    if kind == "lanhuimage":
        result["props"]["src"] = f"https://example.test/{identity}.png"
        result["data"]["value"] = result["props"]["src"]
    if kind == "lanhutext":
        result["props"]["text"] = identity
        result["data"]["value"] = identity
    return result


def page(*children, width=400, height=300):
    return node("root", 0, 0, width, height, kind="lanhupage", children=children)


def painted(identity, x, y, width, height, **kwargs):
    return node(identity, x, y, width, height, style={"backgroundColor": "red"}, **kwargs)


def image(identity, x, y, width=16, height=16):
    return node(identity, x, y, width, height, kind="lanhuimage")


def text(identity, x, y, width=56, height=22):
    return node(identity, x, y, width, height, kind="lanhutext")


def all_nodes(root):
    yield root
    for child in root["children"]:
        yield from all_nodes(child)


def style(root):
    return root["props"]["style"]


def test_harmless_wrappers_flatten_and_source_is_not_mutated():
    raw = page(node("wrapper", 10, 20, 100, 100,
                    children=[text("label", 25, 35)], style={"borderRadius": "9px"}))
    before = deepcopy(raw)
    converted = infer_layout(raw)
    assert raw == before
    assert [child["layerId"] for child in converted["children"]] == ["label"]
    assert style(converted["children"][0])["margin"] == "35px 0 0 25px"


@pytest.mark.parametrize("effect", [
    {"opacity": 0.5}, {"overflow": "hidden"}, {"clipPath": "circle(50%)"},
    {"maskImage": "url(mask.png)"}, {"transform": "rotate(5deg)"},
    {"mixBlendMode": "multiply"}, {"boxShadow": "2px 2px red"},
    {"backgroundColor": "red"}, {"border": "1px solid red"},
    {"filter": "blur(2px)"}, {"isolation": "isolate"},
])
def test_effectful_wrappers_are_preserved(effect):
    raw = page(node("wrapper", 10, 20, 100, 100, children=[text("label", 25, 35)], style=effect))
    converted = infer_layout(raw)
    assert converted["children"][0]["layerId"] == "wrapper"
    assert all(style(converted["children"][0])[key] == value for key, value in effect.items())


def test_behavioral_wrapper_is_not_removed():
    wrapper = node("wrapper", 0, 0, 100, 100, children=[text("label", 20, 30)], loop="this.items")
    assert infer_layout(page(wrapper))["children"][0]["layerId"] == "wrapper"


def test_projection_rebuilds_row_under_column_and_distributes_gap_once():
    title = painted("title", 0, 0, 400, 40)
    left = painted("left", 0, 40, 80, 260)
    right = painted("right", 100, 60, 300, 220)
    converted = infer_layout(page(title, left, right))
    assert style(converted)["flexDirection"] == "column"
    assert style(converted)["justifyContent"] == "space-between"
    row = converted["children"][1]
    assert [child["layerId"] for child in row["children"]] == ["left", "right"]
    assert row["rowDims"] == {"left": 0, "top": 40, "width": 400, "height": 260}
    assert style(row)["flexDirection"] == "row"
    assert style(row)["justifyContent"] == "space-between"
    assert row["alignJustify"] == {"justifyContent": "space-between"}
    assert style(row["children"][1])["marginTop"] == 20
    assert "marginLeft" not in style(row["children"][1])  # gap comes from justify.


def test_image_text_has_union_bounds_and_precise_vertical_offset():
    icon = image("icon", 20, 23)
    label = text("label", 44, 20)
    converted = infer_layout(page(painted("button", 4, 12, 160, 40, children=[icon, label])))
    button = converted["children"][0]
    group = button["children"][0]
    assert group["uiType"] == "ImageText"
    assert group["rowDims"] == {"left": 20, "top": 20, "width": 80, "height": 22}
    assert style(button)["flexDirection"] == "row"
    assert style(group)["margin"] == "8px 0 0 16px"
    assert style(group["children"][0])["marginTop"] == 3
    assert group["children"][1]["uiType"] == "TextGroup"
    assert "marginLeft" not in style(group["children"][1])


def test_singleton_has_no_spurious_trailing_margin_and_multi_child_does():
    converted = infer_layout(page(text("first", 10, 20), text("last", 10, 90)))
    assert style(converted["children"][0])["margin"] == "20px 0 0 10px"
    assert style(converted["children"][1])["margin"] == "48px 0 188px 10px"
    singleton = infer_layout(page(text("alone", 10, 20)))["children"][0]
    assert style(singleton)["margin"] == "20px 0 0 10px"


def test_unresolved_overlaps_keep_painter_order_and_local_absolute_offsets():
    first = painted("first", 90, 55, 60, 80)
    second = painted("second", 60, 75, 50, 50)
    parent = painted("parent", 50, 40, 150, 150, children=[first, second])
    converted = infer_layout(page(parent))["children"][0]
    assert style(converted)["position"] == "relative"
    assert [child["layerId"] for child in converted["children"]] == ["first", "second"]
    assert style(converted["children"][0])["left"] == 40
    assert style(converted["children"][0])["top"] == 15
    assert style(converted["children"][1])["left"] == 10
    assert style(converted["children"][1])["zIndex"] == 1


def test_shadow_extents_do_not_justify_reordering_nonoverlapping_frames():
    front = node("front", 200, 0, 20, 20, style={"boxShadow": "-200px 0 10px red"})
    back = painted("back", 0, 0, 20, 20)
    converted = infer_layout(page(front, back))
    assert [child["layerId"] for child in converted["children"]] == ["front", "back"]
    assert all(style(child)["position"] == "absolute" for child in converted["children"])


def composer_spy(calls):
    def compose(nodes):
        calls.append([node["layerId"] for node in nodes])
        left = min(node["rowDims"]["left"] for node in nodes)
        top = min(node["rowDims"]["top"] for node in nodes)
        right = max(node["rowDims"]["left"] + node["rowDims"]["width"] for node in nodes)
        bottom = max(node["rowDims"]["top"] + node["rowDims"]["height"] for node in nodes)
        merged = deepcopy(nodes[-1])
        merged["rowDims"] = {"left": left, "top": top, "width": right - left, "height": bottom - top}
        merged["props"]["src"] = "data:image/png;base64,test"
        return merged
    return compose


def test_image_merge_preserves_order_and_requires_callback():
    raw = page(image("back", 10, 10, 35, 30), image("front", 25, 15, 20, 35))
    assert len(infer_layout(raw)["children"]) == 2
    calls = []
    converted = infer_layout(raw, image_composer=composer_spy(calls))
    assert calls == [["back", "front"]]
    assert converted["children"][0]["layerId"] == "front"
    assert converted["children"][0]["rowDims"] == {"left": 10, "top": 10, "width": 35, "height": 40}
    assert style(converted["children"][0])["width"] == 35
    assert style(converted["children"][0])["height"] == 40


def test_same_size_nearby_icons_merge_but_wordmarks_do_not():
    calls = []
    raw = page(image("a", 10, 10), image("b", 46, 10), image("wordmark", 70, 10, 100, 16))
    converted = infer_layout(raw, image_composer=composer_spy(calls))
    assert calls == [["a", "b"]]
    assert sum(node["type"] == "lanhuimage" for node in all_nodes(converted)) == 2


def test_image_effects_and_intervening_paint_prevent_merging():
    calls = []
    a, b = image("a", 10, 10), image("b", 46, 10)
    middle = painted("paint", 30, 12, 8, 8)
    infer_layout(page(a, b, middle), image_composer=composer_spy(calls))
    assert calls == []


def test_symmetric_row_spacing_preserves_official_alignment_literal():
    converted = infer_layout(page(painted("a", 10, 10, 20, 20), painted("b", 70, 10, 20, 20), width=100))
    assert style(converted)["justifyContent"] == "flex-center"
    assert converted["alignJustify"] == {"justifyContent": "flex-center"}


def test_composition_respects_effects_retained_on_the_node():
    calls = []
    a, b = image("a", 10, 10), image("b", 46, 10)
    a["clipped"] = True
    infer_layout(page(a, b), image_composer=composer_spy(calls))
    assert calls == []
    a.pop("clipped")
    a["props"]["style"]["opacity"] = 0.5
    infer_layout(page(a, b), image_composer=composer_spy(calls))
    assert calls == []


def test_inferred_ids_are_deterministic_without_input_specific_tables():
    raw = page(painted("button", 0, 0, 160, 40, children=[image("icon", 16, 11), text("label", 40, 8)]))
    assert infer_layout(raw) == infer_layout(raw)
    once = infer_layout(raw)
    assert infer_layout(once) == once


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), "10", True])
def test_invalid_frames_fail_before_layout(bad):
    raw = page(text("label", 0, 0))
    raw["children"][0]["rowDims"]["width"] = bad
    with pytest.raises(ValueError, match="finite numeric"):
        infer_layout(raw)


def test_uniform_inside_border_uses_content_origin_once_in_column():
    parent = node("bordered", 50, 40, 100, 100, style={"border": "5px solid red"},
                  layoutInsets=dict.fromkeys(("top", "right", "bottom", "left"), 5),
                  children=[text("label", 70, 55)])
    converted = infer_layout(page(parent))["children"][0]
    assert style(converted)["boxSizing"] == "border-box"
    assert style(converted)["width"] == 100
    assert style(converted)["height"] == 100
    assert style(converted)["flexShrink"] == 0
    child = converted["children"][0]
    assert style(child)["margin"] == "10px 0 0 15px"
    assert style(child)["flexShrink"] == 0
    # Outer parent coordinate + CSS border + CSS margin recovers the source.
    assert 50 + 5 + 15 == child["rowDims"]["left"]
    assert 40 + 5 + 10 == child["rowDims"]["top"]


def test_inside_border_row_uses_inner_edges_for_justify():
    parent = node("bordered", 50, 40, 100, 60, style={"border": "5px solid red"},
                  layoutInsets=dict.fromkeys(("top", "right", "bottom", "left"), 5),
                  children=[painted("a", 55, 45, 20, 20), painted("b", 115, 45, 30, 20)])
    converted = infer_layout(page(parent))["children"][0]
    assert style(converted)["flexDirection"] == "row"
    assert style(converted)["justifyContent"] == "space-between"
    assert all(not any(key.startswith("margin") for key in style(child)) for child in converted["children"])
    assert all(style(child)["flexShrink"] == 0 for child in converted["children"])


def test_asymmetric_border_absolute_fallback_uses_content_origin_once():
    parent = node("bordered", 50, 40, 150, 150,
                  style={"borderTop": "3px solid red", "borderLeft": "7px solid red"},
                  layoutInsets={"top": 3, "left": 7},
                  children=[painted("a", 90, 55, 60, 80), painted("b", 60, 75, 50, 50)])
    converted = infer_layout(page(parent))["children"][0]
    a, b = converted["children"]
    assert style(converted)["position"] == "relative"
    assert style(a)["position"] == "absolute"
    assert style(a)["left"] == 33
    assert style(a)["top"] == 12
    assert style(b)["left"] == 3
    assert style(b)["top"] == 32


def test_border_reduced_content_does_not_shrink_an_oversized_flex_child():
    parent = node("bordered", 0, 0, 100, 80, style={"border": "5px solid red"},
                  layoutInsets=dict.fromkeys(("top", "right", "bottom", "left"), 5),
                  children=[painted("fixed-size-child", 5, 5, 90, 75)])
    converted = infer_layout(page(parent))["children"][0]
    child = converted["children"][0]
    assert style(converted)["height"] == 80
    assert style(child)["height"] == 75  # 5px taller than the 70px content box.
    assert style(child)["flexShrink"] == 0


def test_missing_border_metadata_keeps_official_compatibility_styles():
    parent = node("legacy", 50, 40, 100, 100, style={"border": "1px solid red"},
                  children=[text("label", 70, 55)])
    converted = infer_layout(page(parent))["children"][0]
    assert "boxSizing" not in style(converted)
    assert "flexShrink" not in style(converted)
    assert style(converted["children"][0])["margin"] == "15px 0 0 20px"
    assert "flexShrink" not in style(converted["children"][0])


@pytest.mark.parametrize("insets", [{"left": -1}, {"left": float("nan")}, {"left": "5"}, {"left": True}, {"inlineStart": 5}, {"left": 500}])
def test_invalid_border_metadata_is_explicit(insets):
    raw = page()
    raw["layoutInsets"] = insets
    with pytest.raises(ValueError, match="layoutInsets"):
        infer_layout(raw)


def test_ineligible_regular_exports_are_not_sent_to_the_composer():
    calls = []
    a, b = image("a", 10, 10), image("b", 46, 10)
    a["mergeEligible"] = b["mergeEligible"] = False
    converted = infer_layout(page(a, b), image_composer=composer_spy(calls))
    assert calls == []
    assert sum(item["type"] == "lanhuimage" for item in all_nodes(converted)) == 2


def test_composition_resource_failure_keeps_images_and_records_diagnostics():
    from lanhu_codegen.figma_images import FigmaImageCompositionError

    def failed_composer(nodes):
        raise FigmaImageCompositionError("DDS PNG size does not match its frame")

    raw = page(image("a", 10, 10), image("b", 46, 10))
    converted = infer_layout(raw, image_composer=failed_composer)
    assert sum(item["type"] == "lanhuimage" for item in all_nodes(converted)) == 2
    assert converted["layoutWarnings"] == [{"code": "image_merge_skipped", "layerIds": ["a", "b"],
                                            "reason": "DDS PNG size does not match its frame"}]
    assert "layoutWarnings" not in raw


def test_programming_errors_in_composer_are_not_swallowed():
    def broken_composer(nodes):
        raise RuntimeError("bug in compositor")

    with pytest.raises(RuntimeError, match="bug in compositor"):
        infer_layout(page(image("a", 10, 10), image("b", 46, 10)), image_composer=broken_composer)


@pytest.mark.parametrize("direction,margin", [("row", "marginLeft"), ("column", "marginTop")])
def test_unequal_main_axis_gaps_are_preserved_when_outer_edges_are_flush(direction, margin):
    children = [painted(str(index), coordinate if direction == "row" else 0,
                        coordinate if direction == "column" else 0, 10, 10)
                for index, coordinate in enumerate((0, 20, 90))]
    converted = infer_layout(page(*children, width=100, height=100))
    assert style(converted)["flexDirection"] == direction
    assert "justifyContent" not in style(converted)
    assert converted["alignJustify"] == {}
    assert style(converted["children"][1])[margin] == 10
    assert style(converted["children"][2])[margin] == 60


def test_three_equal_main_axis_gaps_can_use_space_between():
    converted = infer_layout(page(*(painted(str(index), coordinate, 0, 10, 10)
                                    for index, coordinate in enumerate((0, 45, 90))), width=100))
    assert style(converted)["justifyContent"] == "space-between"
    assert all("marginLeft" not in style(child) for child in converted["children"])


@pytest.mark.parametrize("clipped", [False, True])
def test_unbordered_short_parent_preserves_tall_child_geometry(clipped):
    parent_style = {"backgroundColor": "blue", **({"overflow": "hidden"} if clipped else {})}
    parent = node("short-parent", 10, 20, 100, 40, style=parent_style,
                  children=[painted("tall-child", 10, 20, 100, 80)])
    converted = infer_layout(page(parent))["children"][0]
    child = converted["children"][0]
    assert style(converted)["height"] == 40
    assert style(converted).get("overflow") == ("hidden" if clipped else None)
    assert style(child)["height"] == 80
    assert style(child)["flexShrink"] == 0
    assert child["rowDims"] == {"left": 10, "top": 20, "width": 100, "height": 80}


@pytest.mark.parametrize("clipped", [False, True])
def test_row_overflow_protects_all_siblings_from_flex_shrink(clipped):
    parent_style = {"backgroundColor": "blue", **({"overflow": "hidden"} if clipped else {})}
    parent = node("narrow-parent", 0, 0, 40, 30, style=parent_style,
                  children=[painted("first", 0, 0, 20, 20), painted("second", 20, 0, 40, 20)])
    converted = infer_layout(page(parent))["children"][0]
    assert style(converted)["flexDirection"] == "row"
    assert [style(child)["width"] for child in converted["children"]] == [20, 40]
    assert all(style(child)["flexShrink"] == 0 for child in converted["children"])


def test_official_generator_emits_overflow_size_and_shrink_protection():
    from lanhu_codegen import generate_design_files

    parent = node("clipped-parent", 0, 0, 100, 40,
                  style={"overflow": "hidden"}, children=[painted("tall-child", 0, 0, 100, 80)])
    files = generate_design_files(infer_layout(page(parent)))
    child_css = files["index.css"].split(".tall-child {", 1)[1].split("}", 1)[0]
    parent_css = files["index.css"].split(".clipped-parent {", 1)[1].split("}", 1)[0]
    assert 'class="tall-child flex-col"' in files["index.html"]
    assert "height: 80px" in child_css
    assert "flex-shrink: 0" in child_css
    assert "height: 40px" in parent_css
    assert "overflow: hidden" in parent_css


def test_distant_shadow_does_not_block_safe_geometric_ordering():
    right = node("right", 200, 10, 20, 20, style={"boxShadow": "2px 2px 4px rgba(0, 0, 0, 0.5)"})
    left = painted("left", 0, 10, 20, 20)
    converted = infer_layout(page(right, left))
    assert style(converted)["flexDirection"] == "row"
    assert [child["layerId"] for child in converted["children"]] == ["left", "right"]
    assert style(converted["children"][1])["boxShadow"] == "2px 2px 4px rgba(0, 0, 0, 0.5)"


def test_contained_descendant_shadow_does_not_poison_ancestor_layout():
    shadow = node("shadow", 120, 120, 20, 20, style={"boxShadow": "0px 0px 3px red"})
    right = painted("right", 100, 100, 100, 100, children=[shadow])
    left = painted("left", 0, 100, 20, 20)
    converted = infer_layout(page(right, left))
    assert style(converted)["flexDirection"] == "row"
    assert [child["layerId"] for child in converted["children"]] == ["left", "right"]


def test_intersecting_shadows_can_flow_when_painter_order_is_unchanged():
    left = node("left", 0, 0, 20, 20, style={"boxShadow": "20px 0px red"})
    right = painted("right", 30, 0, 20, 20)
    converted = infer_layout(page(left, right))
    assert style(converted)["flexDirection"] == "row"
    assert [child["layerId"] for child in converted["children"]] == ["left", "right"]


def test_intersecting_multiple_shadow_layers_prevent_painter_order_reversal():
    right = node("right", 100, 0, 20, 20,
                 style={"boxShadow": "2px 2px 3px rgba(0, 0, 0, 0.3), -100px 0px 2px red"})
    left = painted("left", 0, 0, 20, 20)
    converted = infer_layout(page(right, left))
    assert [child["layerId"] for child in converted["children"]] == ["right", "left"]
    assert all(style(child)["position"] == "absolute" for child in converted["children"])


@pytest.mark.parametrize("effect", [
    {"filter": "blur(1px)"}, {"transform": "rotate(1deg)"},
    {"textShadow": "1px 1px red"}, {"boxShadow": "var(--shadow)"}, {"boxShadow": "0 0 2rem red"},
])
def test_unresolved_paint_effects_still_keep_absolute_painter_order(effect):
    right = node("right", 100, 0, 20, 20, style=effect)
    left = painted("left", 0, 0, 20, 20)
    converted = infer_layout(page(right, left))
    assert [child["layerId"] for child in converted["children"]] == ["right", "left"]
    assert all(style(child)["position"] == "absolute" for child in converted["children"])


@pytest.mark.parametrize("clipped", [False, True])
def test_overflow_paint_propagates_only_when_not_clipped(clipped):
    right = node("right", 100, 0, 20, 20,
                 style={"backgroundColor": "blue", **({"overflow": "hidden"} if clipped else {})},
                 children=[painted("escaped", 0, 0, 10, 10)])
    left = painted("left", 0, 0, 20, 20)
    converted = infer_layout(page(right, left))
    if clipped:
        assert style(converted)["flexDirection"] == "row"
        assert [child["layerId"] for child in converted["children"]] == ["left", "right"]
    else:
        assert [child["layerId"] for child in converted["children"]] == ["right", "left"]
        assert all(style(child)["position"] == "absolute" for child in converted["children"])


def test_overflow_hidden_does_not_clip_the_containers_own_outer_shadow():
    right = node("right", 100, 0, 20, 20, style={"overflow": "hidden", "boxShadow": "-100px 0px red"})
    left = painted("left", 0, 0, 20, 20)
    converted = infer_layout(page(right, left))
    assert [child["layerId"] for child in converted["children"]] == ["right", "left"]
    assert all(style(child)["position"] == "absolute" for child in converted["children"])


def test_inset_shadow_does_not_extend_outside_the_container():
    right = node("right", 100, 0, 20, 20, style={"boxShadow": "inset -100px 0px 5px red"})
    left = painted("left", 0, 0, 20, 20)
    converted = infer_layout(page(right, left))
    assert style(converted)["flexDirection"] == "row"
    assert [child["layerId"] for child in converted["children"]] == ["left", "right"]


def test_image_text_grouping_does_not_move_text_behind_an_intervening_shadow():
    icon = image("icon", 10, 13)
    blocker = node("blocker", 50, 10, 16, 22,
                   style={"backgroundColor": "blue", "boxShadow": "-20px 0px 0px 0px green"})
    label = text("label", 30, 10, 16, 22)
    converted = infer_layout(page(icon, blocker, label))
    assert [child["layerId"] for child in converted["children"]] == ["icon", "blocker", "label"]
    assert not any(child.get("uiType") == "ImageText" for child in all_nodes(converted))
    assert [style(child)["zIndex"] for child in converted["children"]] == [0, 1, 2]


def test_image_text_grouping_is_conservative_for_unknown_intervening_paint():
    icon = image("icon", 10, 13)
    blocker = node("blocker", 100, 10, 16, 22, style={"filter": "blur(1px)"})
    label = text("label", 30, 10, 16, 22)
    converted = infer_layout(page(icon, blocker, label))
    assert [child["layerId"] for child in converted["children"]] == ["icon", "blocker", "label"]
    assert not any(child.get("uiType") == "ImageText" for child in all_nodes(converted))


def test_image_text_pair_can_still_cross_unrelated_distant_paint():
    converted = infer_layout(page(image("icon", 10, 13), painted("distant", 100, 10, 16, 22),
                                  text("label", 30, 10, 16, 22)))
    pair = converted["children"][0]
    assert pair["uiType"] == "ImageText"
    assert [child["layerId"] for child in pair["children"]] == ["icon", "label"]


def test_overlapping_positioned_descendants_stay_below_later_atomic_siblings():
    early = node("early", 10, 10, 20, 30, style={"backgroundColor": "yellow"},
                 children=[painted("back", 10, 10, 50, 20), painted("front", 15, 15, 40, 20)])
    late = painted("late", 40, 10, 30, 30)
    converted = infer_layout(page(early, late))
    assert [child["layerId"] for child in converted["children"]] == ["early", "late"]
    first, last = converted["children"]
    assert style(first)["position"] == style(last)["position"] == "absolute"
    assert style(first)["zIndex"] == 0
    assert style(last)["zIndex"] == 1
    assert [style(child)["zIndex"] for child in first["children"]] == [0, 1]


def test_positioned_descendants_do_not_force_unrelated_siblings_absolute():
    early = node("early", 10, 10, 20, 30, style={"backgroundColor": "yellow"},
                 children=[painted("back", 10, 10, 50, 20), painted("front", 15, 15, 40, 20)])
    late = painted("late", 100, 10, 30, 30)
    converted = infer_layout(page(early, late))
    assert style(converted)["flexDirection"] == "row"
    assert "zIndex" not in style(converted["children"][0])
    assert "zIndex" not in style(converted["children"][1])
