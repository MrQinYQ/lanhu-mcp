"""Independent geometry contracts for experimental official-DDS inference."""

from copy import deepcopy

import pytest

from lanhu_codegen.figma_dds_layout import (
    infer_dds_layout, reparent_contained_images, wrap_single_text_rows,
)
from lanhu_codegen.figma_layout import infer_layout


def node(identity, x, y, width, height, *, kind="lanhublock", children=(), style=None, **extra):
    result = {"id": identity, "layerId": identity, "type": kind, "componentName": kind,
              "rowDims": {"left": x, "top": y, "width": width, "height": height},
              "props": {"className": identity, "style": {"width": width, "height": height, **(style or {})}},
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
    return node(identity, x, y, width, height, style={"backgroundColor": "red", **kwargs.pop("style", {})}, **kwargs)


def image(identity, x, y, width=16, height=16, **kwargs):
    return node(identity, x, y, width, height, kind="lanhuimage", **kwargs)


def text(identity, x, y, width=56, height=22):
    return node(identity, x, y, width, height, kind="lanhutext")


def walk(node):
    yield node
    for child in node.get("children", []):
        yield from walk(child)


def by_id(root, identity):
    return next(node for node in walk(root) if node["layerId"] == identity)


def style(node):
    return node["props"]["style"]


def test_dds_partitions_frames_while_source_mode_preserves_shadow_painter_order():
    source = page(painted("right", 200, 0, 20, 20, style={"boxShadow": "-200px 0 10px red"}),
                  painted("left", 0, 0, 20, 20))
    before = deepcopy(source)
    dds, conservative = infer_dds_layout(source), infer_layout(source)
    assert source == before
    assert style(dds)["flexDirection"] == "row"
    assert [child["layerId"] for child in dds["children"]] == ["left", "right"]
    assert [child["layerId"] for child in conservative["children"]] == ["right", "left"]
    assert all(style(child)["position"] == "absolute" for child in conservative["children"])


@pytest.mark.parametrize("effect", [{"filter": "blur(2px)"}, {"transform": "rotate(15deg)"},
                                    {"boxShadow": "var(--unknown-shadow)"}])
def test_unresolved_effects_do_not_acquire_an_invented_frame_partition(effect):
    actual = infer_dds_layout(page(painted("a", 0, 0, 20, 20, style=effect), painted("b", 80, 0, 20, 20)))
    assert "flexDirection" not in style(actual)
    assert all(style(child)["position"] == "absolute" for child in actual["children"])


def marker_example():
    # The late marker fits the panel, but extends beyond the narrow second row.
    rows = [painted("one", 28, 30, 84, 30), painted("two", 28, 80, 84, 30),
            painted("three", 28, 140, 84, 30)]
    panel = painted("panel", 20, 20, 100, 200, children=rows)
    return page(panel, image("marker", 98, 100, 18, 18, sourceHasOrdinaryImage=True))


def test_late_contained_image_moves_to_smallest_container_and_keeps_source_metadata():
    source = marker_example()
    before = deepcopy(source)
    attached = reparent_contained_images(source)
    assert source == before
    assert [child["layerId"] for child in attached["children"]] == ["panel"]
    assert by_id(attached, "panel")["children"][-1]["layerId"] == "marker"
    assert by_id(attached, "marker")["sourceHasOrdinaryImage"] is True
    assert by_id(attached, "marker")["rowDims"] == by_id(source, "marker")["rowDims"]


def test_reparented_single_overlap_is_inline_with_negative_margin_and_following_gap():
    actual = infer_dds_layout(marker_example())
    panel = by_id(actual, "panel")
    assert [child["layerId"] for child in panel["children"]] == ["one", "two", "marker", "three"]
    assert style(panel)["flexDirection"] == "column"
    assert style(by_id(actual, "marker"))["margin"] == "-10px 0 0 78px"
    assert style(by_id(actual, "three"))["margin"] == "22px 0 50px 8px"
    assert "position" not in style(by_id(actual, "marker"))


def envelope_example(*, marked=True, target_style=None, leaf_style=None, obstacle=None, early=False):
    target = painted("target", 10, 10, 40, 40, style=target_style or {})
    projection = painted("projection", 40, 20, 10, 10, style=leaf_style or {})
    if marked:
        projection["ddsRectEnvelopeProjection"] = True
    children = [target, *([obstacle] if obstacle else []), projection]
    if early:
        children = [projection, target]
    return page(*children)


def test_only_explicit_dds_envelope_leaf_can_join_a_preceding_containing_paint_block():
    source = envelope_example()
    before = deepcopy(source)
    actual = infer_dds_layout(source)
    target = by_id(actual, "target")
    assert [child["layerId"] for child in target["children"]] == ["projection"]
    assert style(target["children"][0])["margin"] == "10px 0 0 30px"
    assert source == before
    # The public image-only helper and ordinary/source layout retain their
    # original contract; normal painted leaves do not acquire this inference.
    assert not by_id(reparent_contained_images(source), "target")["children"]
    assert not by_id(infer_layout(source), "target")["children"]
    assert not by_id(infer_dds_layout(envelope_example(marked=False)), "target")["children"]


@pytest.mark.parametrize("case", ["clip", "target_opacity", "target_transform", "leaf_opacity", "unknown_paint", "shadow_outside", "intervening_paint", "earlier_leaf"])
def test_envelope_containment_respects_paint_bounds_scope_and_order(case):
    target_styles = {"clip": {"overflow": "hidden"}, "target_opacity": {"opacity": 0.5},
                     "target_transform": {"transform": "translateX(2px)"}}
    leaf_styles = {"leaf_opacity": {"opacity": 0.5}, "unknown_paint": {"boxShadow": "var(--shadow)"},
                   "shadow_outside": {"boxShadow": "2px 0 0 blue"}}
    obstacle = painted("obstacle", 80, 20, 10, 10, style={"boxShadow": "-40px 0 0 blue"}) if case == "intervening_paint" else None
    source = envelope_example(target_style=target_styles.get(case), leaf_style=leaf_styles.get(case),
                              obstacle=obstacle, early=case == "earlier_leaf")
    actual = infer_dds_layout(source)
    assert not by_id(actual, "target")["children"]


@pytest.mark.parametrize("effect", [
    {"opacity": 0.5}, {"overflow": "hidden"}, {"clipPath": "circle(50%)"},
    {"transform": "scale(2)"}, {"filter": "blur(3px)"}, {"mixBlendMode": "multiply"},
])
def test_reparent_does_not_cross_target_or_ancestor_effects(effect):
    target = painted("target", 30, 30, 100, 100)
    affected = painted("affected", 20, 20, 140, 140, children=[target], style=effect)
    source = page(affected, image("marker", 50, 50))
    attached = reparent_contained_images(source)
    assert attached["children"][-1]["layerId"] == "marker"


def test_equal_containers_and_intervening_shadow_make_reparenting_ambiguous():
    marker = image("marker", 60, 20)
    ambiguous = page(painted("a", 0, 0, 100, 100), painted("b", 0, 0, 100, 100), marker)
    assert reparent_contained_images(ambiguous)["children"][-1]["layerId"] == "marker"
    covered = page(painted("panel", 0, 0, 100, 100),
                   painted("later", 150, 0, 20, 80, style={"boxShadow": "-90px 0 0 red"}), marker)
    assert reparent_contained_images(covered)["children"][-1]["layerId"] == "marker"


def overlay_example(*, early=False, height=30):
    children = [painted("one", 10, 10, 40, 25), painted("two", 10, 60, 40, 25),
                painted("three", 10, 100, 40, 25)]
    marker = image("marker", 30, 80, 20, height)
    children.insert(0 if early else len(children), marker)
    return page(painted("panel", 0, 0, 80, 200, children=children))


def test_late_image_crossing_two_flow_rows_is_one_absolute_overlay():
    actual = infer_dds_layout(overlay_example())
    panel = by_id(actual, "panel")
    assert [child["layerId"] for child in panel["children"]] == ["one", "two", "three", "marker"]
    assert style(panel)["flexDirection"] == "column"
    assert style(panel)["position"] == "relative"
    assert style(by_id(actual, "marker")) == {"width": 20, "height": 30, "position": "absolute", "left": 30, "top": 80}
    assert style(by_id(actual, "three"))["margin"] == "15px 0 75px 10px"
    assert all("position" not in style(by_id(actual, identity)) for identity in ("one", "two", "three"))


def test_baked_oblique_rotation_disambiguates_one_row_overlay():
    source = overlay_example(height=15)
    raw_metadata = {"marker": {"rotation": 17, "name": "irrelevant"}}
    before = deepcopy(raw_metadata)
    actual = infer_dds_layout(source, source_nodes=raw_metadata)
    assert raw_metadata == before
    assert by_id(actual, "panel")["children"][-1]["layerId"] == "marker"
    assert style(by_id(actual, "marker"))["position"] == "absolute"
    unrotated = infer_dds_layout(source, source_nodes={"marker": {"rotation": 180}})
    assert by_id(unrotated, "panel")["children"][-1]["layerId"] != "marker"


def test_earlier_overlapping_image_is_not_promoted_above_later_rows():
    actual = infer_dds_layout(overlay_example(early=True))
    assert by_id(actual, "panel")["children"][-1]["layerId"] != "marker"


def test_matrix_rows_keep_heading_and_footer_as_single_text_rows():
    source = page(painted("panel", 10, 10, 280, 200, children=[
        text("heading", 30, 20), painted("cell-a", 30, 70, 60, 40),
        painted("cell-b", 150, 70, 60, 40), text("footer", 150, 140),
    ]))
    actual = infer_dds_layout(source)
    rows = by_id(actual, "panel")["children"]
    assert [[child["layerId"] for child in row["children"]] for row in rows] == [["heading"], ["cell-a", "cell-b"], ["footer"]]
    assert all(style(row)["flexDirection"] == "row" for row in rows)
    assert rows[0]["rowDims"] == by_id(source, "heading")["rowDims"]
    assert rows[2]["rowDims"] == by_id(source, "footer")["rowDims"]
    assert wrap_single_text_rows(actual) == actual


def test_single_text_columns_and_heterogeneous_rows_do_not_establish_matrix_context():
    plain = infer_dds_layout(page(painted("panel", 0, 0, 200, 150, children=[text("a", 10, 10), text("b", 10, 70)])))
    assert [child["layerId"] for child in by_id(plain, "panel")["children"]] == ["a", "b"]
    mixed = infer_dds_layout(page(painted("panel", 0, 0, 200, 150, children=[
        text("heading", 10, 10), painted("cell", 10, 60, 100, 20), image("arrow", 140, 60),
    ])))
    assert by_id(mixed, "panel")["children"][0]["layerId"] == "heading"
    # Avatar above a text pair must remain available to the semantic pass.
    avatar = infer_dds_layout(page(painted("panel", 0, 0, 200, 150, children=[
        image("avatar", 80, 10, 40, 40), text("name", 80, 60), text("phone", 80, 85),
    ])))
    assert [child["layerId"] for child in by_id(avatar, "panel")["children"]] == ["avatar", "name", "phone"]


@pytest.mark.parametrize("direction", ["row", "column"])
def test_three_distributed_items_retain_explicit_main_axis_gaps(direction):
    coords = [(0, 0), (45, 0), (90, 0)] if direction == "row" else [(0, 0), (0, 45), (0, 90)]
    source = page(*(painted(str(index), x, y, 10, 10) for index, (x, y) in enumerate(coords)), width=100, height=100)
    actual = infer_dds_layout(source)
    assert style(actual)["justifyContent"] == "space-between"
    assert actual["alignJustify"] == {"justifyContent": "space-between"}
    key = "marginLeft" if direction == "row" else "marginTop"
    assert key not in style(actual["children"][0])
    assert [style(child)[key] for child in actual["children"][1:]] == [35, 35]
    conservative = infer_layout(source)
    assert all(key not in style(child) for child in conservative["children"])


def test_two_distributed_items_omit_inner_gap_and_unequal_three_items_keep_margins():
    pair = infer_dds_layout(page(painted("a", 0, 0, 10, 10), painted("b", 90, 0, 10, 10), width=100))
    assert style(pair)["justifyContent"] == "space-between"
    assert all("marginLeft" not in style(child) for child in pair["children"])
    uneven = infer_dds_layout(page(painted("a", 0, 0, 10, 10), painted("b", 20, 0, 10, 10),
                                   painted("c", 90, 0, 10, 10), width=100))
    assert "justifyContent" not in style(uneven)
    assert [style(child)["marginLeft"] for child in uneven["children"][1:]] == [10, 60]


@pytest.mark.parametrize("gap", [3, 4, 9])
def test_inline_text_row_keeps_its_column_line_gap(gap):
    from lanhu_codegen.figma_dds_layout import _place_dds
    row = node("inline", 0, 22 + gap, 180, 20,
               children=[text("label", 0, 22 + gap, 30, 20), text("value", 30, 22 + gap, 150, 20)])
    _place_dds(row, "row")
    column = node("column", 0, 0, 180, 42 + gap, children=[text("title", 0, 0, 50, 22), row])
    _place_dds(column, "column")
    assert style(column)["justifyContent"] == "space-between"
    assert style(row)["marginTop"] == gap
    assert not column.get("uiType")


@pytest.mark.parametrize("change", ["image", "background", "clip", "effect"])
def test_distributed_column_gap_does_not_depend_on_the_child_row_paint_or_contents(change):
    from lanhu_codegen.figma_dds_layout import _place_dds
    row = node("inline", 0, 26, 180, 20,
               children=[text("label", 0, 26, 30, 20), text("value", 30, 26, 150, 20)])
    if change == "image":
        row["children"][1] = image("picture", 30, 26, 150, 20)
    else:
        style(row).update({"backgroundColor": "red"} if change == "background" else
                          {"overflow": "hidden"} if change == "clip" else {"boxShadow": "0 0 2px red"})
    _place_dds(row, "row")
    column = node("column", 0, 0, 180, 46, children=[text("title", 0, 0, 50, 22), row])
    _place_dds(column, "column")
    # The fifth independent DDS sample disproved the earlier text-only
    # restriction: column spacing persists for both painted and mixed cells.
    assert style(row)["marginTop"] == 4


@pytest.mark.parametrize("last_y,expected", [(70, "flex-center"), (65, None)])
def test_symmetric_nonzero_column_edges_use_dds_flex_center(last_y, expected):
    actual = infer_dds_layout(page(painted("a", 0, 10, 20, 20), painted("b", 0, last_y, 20, 20), height=100))
    assert style(actual).get("justifyContent") == expected
    assert style(actual["children"][0])["marginTop"] == 10
    assert style(actual["children"][1])["margin"] == f"{last_y - 30}px 0 {80 - last_y}px 0"


@pytest.mark.parametrize("background,right,expected", [(True, 172, "space-between"), (False, 172, "flex-center"), (True, 171, None)])
def test_symmetric_background_text_then_image_distributes_only_inner_space(background, right, expected):
    source = page(node("control", 0, 0, 200, 40, style={"backgroundColor": "white"} if background else {},
                       uiType="control", children=[text("label", 12, 5, 80, 22), image("arrow", right, 12)]))
    control = by_id(infer_dds_layout(source), "control")
    assert style(control).get("justifyContent") == expected
    assert style(control["children"][0])["margin"] == "5px 0 0 12px"
    gap = 0 if expected == "space-between" else right - 92
    gap_css = f"{gap}px" if gap else "0"
    assert style(control["children"][1])["margin"] == f"12px {184 - right}px 0 {gap_css}"


def test_leading_icon_and_trailing_text_also_distribute_between_symmetric_insets():
    # The fourth paired design disproved the earlier direction-only hypothesis.
    source = page(painted("control", 0, 0, 200, 40, children=[image("icon", 12, 12), text("label", 132, 5)]))
    control = by_id(infer_dds_layout(source), "control")
    assert style(control)["justifyContent"] == "space-between"
    assert style(control["children"][1])["margin"] == "5px 12px 0 0"


@pytest.mark.parametrize('change,distributed', [(None, True), ('text_child', False), ('clip', False),
                                               ('overflow', False), ('empty', False), ('opacity', False)])
def test_two_ended_control_accepts_a_safe_contained_image_wrapper_only(change, distributed):
    inner = image('icon', 15, 15, 18, 9) if change != 'text_child' else text('inside', 15, 15, 18, 9)
    if change == 'overflow':
        inner['rowDims']['left'] = 5
    effects = {'clip': {'overflow': 'hidden'}, 'opacity': {'opacity': .5}}
    wrapper = painted('wrapper', 12, 6, 24, 24, children=[] if change == 'empty' else [inner], style=effects.get(change, {}))
    source = page(painted('control', 0, 0, 200, 36, children=[wrapper, text('label', 44, 7, 144, 22)]))
    actual = infer_dds_layout(source)
    control = by_id(actual, 'control')
    assert (style(control).get('justifyContent') == 'space-between') is distributed
    assert style(by_id(actual, 'label'))['margin'] == f"7px 12px 0 {'0' if distributed else '8px'}"


def overflow_matrix(*, wrappers=True, panel_effect=None, neighbor_x=171, nested=False, both_edges=False):
    bands = [(70, 20), (90, 20), (110, 20)] if nested else [(70, 20), (90, 20)]
    inside = [painted(f"inside-{index}", neighbor_x, y, 20, height) for index, (y, height) in enumerate(bands)]
    outside = [painted(f"outside-{index}", 191, y, 20, height) for index, (y, height) in enumerate(bands)]
    outer_children = outside
    if nested:
        outer_children = [node("inner-wrapper", 191, 70, 20, 40, children=outside[:2]), outside[2]]
    columns = ([node("inside-wrapper", neighbor_x, 70, 20, sum(h for _, h in bands), children=inside),
                node("outside-wrapper", 191, 70, 20, sum(h for _, h in bands), children=outer_children)]
               if wrappers else inside + outside)
    if both_edges:
        left_inside = [painted(f"left-inside-{index}", 69, y, 20, height) for index, (y, height) in enumerate(bands)]
        left_outside = [painted(f"left-outside-{index}", 49, y, 20, height) for index, (y, height) in enumerate(bands)]
        columns[:0] = [node("left-outside-wrapper", 49, 70, 20, 40, children=left_outside),
                       node("left-inside-wrapper", 69, 70, 20, 40, children=left_inside)]
    panel = painted("panel", 50, 40, 160, 110, children=[text("heading", 66, 48, 80, 12), *columns], style=panel_effect or {})
    application = painted("application", 10, 10, 200, 150, children=[
        painted("header", 10, 10, 200, 20), painted("sidebar", 10, 30, 30, 130), panel,
    ])
    return page(application, width=240, height=190)


def test_crossing_matrix_column_lifts_once_and_its_original_panel_is_a_late_overlay():
    source = overflow_matrix()
    before = deepcopy(source)
    actual = infer_dds_layout(source)
    assert source == before
    application = by_id(actual, "application")
    lower_row = application["children"][1]
    assert lower_row["rowDims"] == {"left": 10, "top": 30, "width": 201, "height": 130}
    assert lower_row["children"][0]["layerId"] == "sidebar"
    column, panel = lower_row["children"][1:]
    assert [child["layerId"] for child in column["children"]] == ["outside-0", "outside-1"]
    assert panel["layerId"] == "panel" and style(panel)["position"] == "absolute"
    assert style(panel)["left"] == 40 and style(panel)["top"] == 10
    assert style(panel)["display"] == "flex" and style(panel)["flexDirection"] == "column"
    assert style(lower_row)["position"] == "relative"
    assert "zIndex" not in style(panel)
    # The promoted column extends one pixel beyond the application, but does
    # not move again to the page. Original global rectangles are unchanged.
    assert len(actual["children"]) == 1
    for identity in ("panel", "outside-0", "outside-1", "inside-0", "inside-1"):
        assert by_id(actual, identity)["rowDims"] == by_id(source, identity)["rowDims"]


@pytest.mark.parametrize("change", ["flat", "not_adjacent", "clip", "opacity", "transform"])
def test_overflow_lift_requires_source_column_matrix_evidence_and_a_safe_scope(change):
    effects = {"clip": {"overflow": "hidden"}, "opacity": {"opacity": 0.5}, "transform": {"transform": "scale(2)"}}
    actual = infer_dds_layout(overflow_matrix(wrappers=change != "flat", neighbor_x=165 if change == "not_adjacent" else 171,
                                            panel_effect=effects.get(change)))
    panel = by_id(actual, "panel")
    assert {"outside-0", "outside-1"} <= {child["layerId"] for child in walk(panel)}


def test_nested_column_wrappers_do_not_duplicate_cells_in_overlapping_lift_plans():
    actual = infer_dds_layout(overflow_matrix(nested=True))
    identities = [child["layerId"] for child in walk(actual)]
    assert all(identities.count(f"outside-{index}") == 1 for index in range(3))
    lower_row = by_id(actual, "application")["children"][1]
    assert [child["layerId"] for child in lower_row["children"][1]["children"]] == ["outside-0", "outside-1", "outside-2"]


def test_two_crossing_edge_columns_share_one_original_panel_overlay():
    actual = infer_dds_layout(overflow_matrix(both_edges=True))
    lower_row = by_id(actual, "application")["children"][1]
    assert len(lower_row["children"]) == 4
    assert lower_row["children"][-1]["layerId"] == "panel"
    assert sum(child["layerId"] == "panel" for child in walk(actual)) == 1
    assert [child["layerId"] for child in lower_row["children"][1]["children"]] == ["left-outside-0", "left-outside-1"]
    assert [child["layerId"] for child in lower_row["children"][2]["children"]] == ["outside-0", "outside-1"]


@pytest.mark.parametrize("heading_width,wrapped", [(160, False), (162, False), (80, True)])
def test_full_content_width_text_is_not_a_single_cell_matrix_row(heading_width, wrapped):
    source = page(painted("panel", 10, 10, 200, 150, children=[
        text("heading", 20, 20, heading_width, 20),
        painted("a", 20, 60, 80, 20), painted("b", 100, 60, 80, 20),
        # An unrelated row crosses the panel edge; it must not expand the
        # contained content span used to classify the heading above.
        painted("c", 20, 100, 80, 20), painted("d", 100, 100, 120, 20),
    ]))
    first = by_id(infer_dds_layout(source), "panel")["children"][0]
    assert (first.get("type") == "lanhublock") is wrapped
    assert (first["children"][0] if wrapped else first)["layerId"] == "heading"


def test_original_painted_two_cell_footer_does_not_establish_a_matrix_for_labels():
    source = page(painted('panel', 0, 0, 200, 150, children=[
        text('caption', 10, 10, 70, 20),
        painted('input', 10, 40, 180, 25, children=[text('placeholder', 15, 43, 90, 20)]),
        painted('footer', 0, 100, 200, 50, children=[
            painted('left-button', 80, 110, 50, 30), painted('right-button', 140, 110, 50, 30),
        ]),
    ]))
    actual = infer_dds_layout(source)
    assert [child['layerId'] for child in by_id(actual, 'panel')['children']] == ['caption', 'input', 'footer']


@pytest.mark.parametrize("invalid", [None, [], {"type": "lanhublock"}, {"type": "lanhupage", "rowDims": {}}])
def test_invalid_normalized_root_has_clear_error(invalid):
    with pytest.raises(ValueError):
        infer_dds_layout(invalid)


def test_invalid_children_and_metadata_are_rejected():
    invalid = page()
    invalid["children"] = [None]
    with pytest.raises(ValueError, match="children"):
        infer_dds_layout(invalid)
    with pytest.raises(ValueError, match="source_nodes"):
        infer_dds_layout(page(), source_nodes=[])


def projected_overlay_example(*, marked=True, late=True, effect=None):
    projection = painted('projection', 58, 26, 4, 4, ddsRectEnvelopeProjection=marked)
    decoration = painted('decoration', 50, 19, 12, 18, children=[projection], style=effect or {})
    icon = image('icon', 47, 21, 18, 14)
    content = [image('tool', 10, 18, 24, 24), icon, decoration]
    if not late:
        content[-2:] = [decoration, icon]
    return page(painted('cell', 0, 0, 100, 60, children=content))


def test_projected_badge_container_is_a_late_local_overlay_without_overlap_wrapper():
    source = projected_overlay_example()
    actual = infer_dds_layout(source)
    cell = by_id(actual, 'cell')
    assert [child['layerId'] for child in cell['children']] == ['tool', 'icon', 'decoration']
    assert style(cell)['position'] == 'relative'
    decoration = by_id(actual, 'decoration')
    assert style(decoration)['position'] == 'absolute'
    assert (style(decoration)['left'], style(decoration)['top']) == (50, 19)
    assert style(decoration)['flexDirection'] == 'column'
    assert style(by_id(actual, 'projection'))['margin'] == '7px 0 0 8px'
    assert 'zIndex' not in style(decoration)


@pytest.mark.parametrize('change', ['unmarked', 'early', 'unknown', 'shadow_outside'])
def test_projected_badge_overlay_requires_proof_and_bounded_late_paint(change):
    source = projected_overlay_example(marked=change != 'unmarked', late=change != 'early', effect={
        'unknown': {'filter': 'blur(2px)'}, 'shadow_outside': {'boxShadow': '80px 0 0 red'},
    }.get(change))
    actual = infer_dds_layout(source)
    assert by_id(actual, 'decoration') not in by_id(actual, 'cell')['children'] or style(by_id(actual, 'icon')).get('position') == 'absolute'


def backdrop_example(*, offset=0, effect=None, intervening=False, ordinary=False):
    backdrop = painted('backdrop', 10, 10 + offset, 100, 100,
                       style={'backgroundColor': 'rgba(0,0,0,0.4)', **(effect or {})})
    dialog = painted('dialog', 35, 40, 50, 30, children=[text('caption', 40, 45, 30, 10)])
    children = [painted('header', 10, 10, 100, 20), painted('left', 10, 30, 20, 80),
                painted('content', 30, 30, 80, 80), backdrop]
    if intervening:
        children.append(painted('obstacle', 35, 40, 20, 20))
    children.append(dialog)
    source = page(painted('application', 10, 10, 100, 100, children=children), width=140, height=140)
    metadata = {'backdrop': {'type': 'artboard' if ordinary else 'shapeLayer'}, 'dialog': {'type': 'artboard'}}
    return source, metadata


def test_late_full_frame_translucent_shape_contains_dialog_and_leaves_application_flow():
    source, metadata = backdrop_example()
    before = deepcopy(source)
    actual = infer_dds_layout(source, source_nodes=metadata)
    assert source == before
    app = by_id(actual, 'application')
    assert [child['layerId'] for child in app['children'][1]['children']] == ['left', 'content']
    assert [child['layerId'] for child in by_id(actual, 'backdrop')['children']] == ['dialog']
    assert app['children'][-1]['layerId'] == 'backdrop'
    assert style(by_id(actual, 'backdrop'))['position'] == 'absolute'
    assert 'position' not in style(by_id(actual, 'dialog'))
    assert style(by_id(actual, 'dialog'))['margin'] == '30px 0 0 25px'


def test_crossing_full_frame_backdrop_is_promoted_once_to_parent_and_keeps_dialog_coordinates():
    source, metadata = backdrop_example(offset=1)
    actual = infer_dds_layout(source, source_nodes=metadata)
    assert [child['layerId'] for child in actual['children']] == ['application', 'backdrop']
    assert (style(by_id(actual, 'backdrop'))['left'], style(by_id(actual, 'backdrop'))['top']) == (10, 11)
    assert style(by_id(actual, 'dialog'))['margin'] == '29px 0 0 25px'
    assert 'backdrop' not in {n['layerId'] for n in walk(by_id(actual, 'application'))}


@pytest.mark.parametrize('change', ['opaque', 'opacity', 'clip', 'unknown', 'intervening', 'ordinary', 'parent_clip'])
def test_backdrop_scope_requires_alpha_fill_safe_boundary_and_adjacent_terminal_dialog(change):
    effects = {'opaque': {'backgroundColor': 'rgb(0,0,0)'}, 'opacity': {'opacity': .5},
               'clip': {'overflow': 'hidden'}, 'unknown': {'filter': 'blur(2px)'}}
    source, metadata = backdrop_example(effect=effects.get(change), intervening=change == 'intervening', ordinary=change == 'ordinary')
    if change == 'parent_clip':
        style(by_id(source, 'application'))['overflow'] = 'hidden'
    actual = infer_dds_layout(source, source_nodes=metadata)
    assert not by_id(actual, 'backdrop')['children']
    assert by_id(actual, 'dialog') in by_id(actual, 'application')['children']
    conservative = infer_layout(source)
    assert not by_id(conservative, 'backdrop')['children']


def crossing_label_example(*, clipped=False, neighbor=True, last=True, overlap=False):
    label = text('escaping-label', 99, 20, 20, 12)
    cell_children = [text('a', 20, 20, 30, 12), text('b', 60, 20, 30, 12), label]
    if not last:
        cell_children[-2:] = [label, cell_children[-2]]
    cell = node('cell', 10, 10, 90, 40, children=cell_children,
                style={'border': '1px solid red', **({'overflow': 'hidden'} if clipped else {})})
    next_cell = node('next', 100 if neighbor else 120, 10, 90, 40, style={'border': '1px solid red'})
    panel = painted('panel', 0, 0, 220, 100, children=[cell, next_cell, text('footer', 10, 65, 60, 12)])
    if overlap:
        panel['children'].insert(1, painted('intervening', 90, 10, 40, 40))
    return page(panel)


def test_trailing_text_crossing_adjacent_matrix_cell_enters_parent_row_with_negative_gaps():
    source = crossing_label_example()
    before = deepcopy(source)
    actual = infer_dds_layout(source)
    assert source == before
    row = by_id(actual, 'panel')['children'][0]
    assert [child['layerId'] for child in row['children']] == ['cell', 'escaping-label', 'next']
    assert not {'position', 'left', 'top'} & style(row).keys()
    assert style(by_id(actual, 'escaping-label'))['margin'] == '10px 0 0 -1px'
    assert style(by_id(actual, 'next'))['marginLeft'] == -19
    assert by_id(actual, 'escaping-label')['rowDims'] == by_id(source, 'escaping-label')['rowDims']
    assert len(by_id(actual, 'cell')['children']) == 2


@pytest.mark.parametrize('change', ['clip', 'gap', 'not_last', 'obstacle'])
def test_crossing_label_requires_safe_scope_source_order_and_adjacent_cell(change):
    source = crossing_label_example(clipped=change == 'clip', neighbor=change != 'gap', last=change != 'not_last', overlap=change == 'obstacle')
    actual = infer_dds_layout(source)
    assert 'escaping-label' in {n['layerId'] for n in walk(by_id(actual, 'cell'))}
    assert 'escaping-label' in {n['layerId'] for n in walk(by_id(infer_layout(source), 'cell'))}


def test_adjacent_cell_height_can_differ_while_covering_the_same_label_row():
    source = crossing_label_example()
    by_id(source, 'next')['rowDims']['height'] = 41
    actual = infer_dds_layout(source)
    row = by_id(actual, 'panel')['children'][0]
    assert [child['layerId'] for child in row['children']] == ['cell', 'escaping-label', 'next']
    assert row['rowDims']['height'] == 41


@pytest.mark.parametrize('heading_x,heading_width,wrapped', [(10, 180, False), (60, 80, True)])
def test_leading_symmetric_content_anchor_survives_rounded_matrix_overrun(heading_x, heading_width, wrapped):
    source = page(painted('panel', 0, 0, 200, 100, children=[
        text('heading', heading_x, 10, heading_width, 20),
        painted('a', 10, 50, 91, 30), painted('b', 101, 50, 92, 30),
    ]))
    first = by_id(infer_dds_layout(source), 'panel')['children'][0]
    assert bool(first.get('children')) is wrapped
    assert (first['children'][0] if wrapped else first)['layerId'] == 'heading'


@pytest.mark.parametrize('kind', ['intersecting', 'unknown'])
def test_crossing_backdrop_promotion_rejects_later_paint_conflicts_atomically(kind):
    source, metadata = backdrop_example(offset=1)
    later = painted('later', 70 if kind == 'intersecting' else 120, 10, 20, 100,
                    style={'filter': 'blur(2px)'} if kind == 'unknown' else {})
    source['children'].append(later)
    before = deepcopy(source)
    actual = infer_dds_layout(source, source_nodes=metadata)
    assert source == before
    app = by_id(actual, 'application')
    assert by_id(actual, 'backdrop') in app['children']
    assert by_id(actual, 'dialog') in app['children']
    assert not by_id(actual, 'backdrop')['children']
    identities = [n['layerId'] for n in walk(actual)]
    assert all(identities.count(identity) == 1 for identity in ('backdrop', 'dialog', 'later'))


@pytest.mark.parametrize('earlier', [False, True])
def test_crossing_backdrop_promotion_allows_disjoint_later_or_overlapping_earlier_sibling(earlier):
    source, metadata = backdrop_example(offset=1)
    other = painted('other', 70 if earlier else 120, 10, 20, 100)
    if earlier:
        source['children'].insert(0, other)
    else:
        source['children'].append(other)
    actual = infer_dds_layout(source, source_nodes=metadata)
    assert actual['children'][-1]['layerId'] == 'backdrop'
    assert by_id(actual, 'backdrop')['children'][0]['layerId'] == 'dialog'
    assert 'backdrop' not in {n['layerId'] for n in walk(by_id(actual, 'application'))}


@pytest.mark.parametrize('effect', [{}, {'opacity': .5}, {'overflow': 'hidden'}])
def test_lifted_label_never_enters_synthetic_rows_inside_an_original_sibling(effect):
    cell = painted('cell', 0, 0, 100, 40, children=[text('prefix', 10, 10, 20, 10), text('lifted-label', 90, 10, 20, 10)])
    neighbor = painted('neighbor', 100, 0, 100, 40, style=effect, children=[
        text('a', 80, 10, 10, 10), text('b', 100, 10, 20, 10), text('c', 110, 30, 20, 10),
    ])
    source = page(painted('panel', 0, 0, 200, 60, children=[cell, neighbor]), width=200, height=100)
    before = deepcopy(source)
    actual = infer_dds_layout(source)
    assert source == before
    assert by_id(actual, 'lifted-label') in by_id(actual, 'panel')['children']
    assert 'lifted-label' not in {n['layerId'] for n in walk(by_id(actual, 'neighbor'))}
    assert [n['layerId'] for n in walk(actual)].count('lifted-label') == 1


def test_explicit_rotated_hairline_projection_stays_an_absolute_child_of_its_original_card():
    line = painted('line', 17, 77, 1, 286, ddsRotatedHairlineProjection=True)
    source = page(painted('card', 0, 0, 320, 120, children=[
        painted('summary', 17, 16, 286, 48), line, text('caption', 17, 89, 40, 20),
    ]))
    actual = infer_dds_layout(source)
    card = by_id(actual, 'card')
    assert [child['layerId'] for child in card['children']] == ['summary', 'caption', 'line']
    assert style(card)['position'] == 'relative'
    assert style(by_id(actual, 'line'))['position'] == 'absolute'
    assert (style(by_id(actual, 'line'))['left'], style(by_id(actual, 'line'))['top']) == (17, 77)
    assert style(by_id(actual, 'line'))['flexDirection'] == 'column'
    assert by_id(actual, 'line')['rowDims'] == line['rowDims']
    assert 'zIndex' not in style(by_id(actual, 'line'))


@pytest.mark.parametrize('marker,effect', [(False, {}), (True, {'opacity': .5}), (True, {'filter': 'blur(2px)'})])
def test_ordinary_or_effectful_long_rectangle_is_not_a_hairline_projection_overlay(marker, effect):
    line = painted('line', 17, 77, 1, 286, style=effect, ddsRotatedHairlineProjection=marker)
    source = page(painted('card', 0, 0, 320, 120, children=[painted('summary', 17, 16, 286, 48), line, text('caption', 17, 89, 40, 20)]))
    actual = infer_dds_layout(source)
    assert by_id(actual, 'line') not in by_id(actual, 'card')['children'] or style(by_id(actual, 'caption')).get('position') == 'absolute'


def fractional_columns_example():
    source = page(painted('left', 1, 0, 10, 20), painted('right', 10, 0, 10, 20), width=20, height=20)
    metadata = {'left': {'frame': {'left': .25, 'top': 0, 'width': 9.75, 'height': 20}},
                'right': {'frame': {'left': 10, 'top': 0, 'width': 10, 'height': 20}}}
    return source, metadata


def test_fractional_source_edges_can_prove_touching_cells_despite_ceil_overlap():
    source, metadata = fractional_columns_example()
    actual = infer_dds_layout(source, source_nodes=metadata)
    assert style(actual)['flexDirection'] == 'row'
    assert [child['layerId'] for child in actual['children']] == ['left', 'right']
    assert style(by_id(actual, 'right'))['marginLeft'] == -1
    assert [n['rowDims'] for n in actual['children']] == [n['rowDims'] for n in source['children']]


@pytest.mark.parametrize('change', ['missing', 'stale', 'true_overlap', 'not_cells'])
def test_rounded_column_refinement_requires_matching_source_frames_and_no_real_overlap(change):
    source, metadata = fractional_columns_example()
    if change == 'missing':
        metadata = {}
    elif change == 'stale':
        metadata['left']['frame']['width'] = 9
    elif change == 'true_overlap':
        metadata['left']['frame'].update(left=1, width=10)
    else:
        for child in source['children']:
            child['type'] = 'lanhutext'
    actual = infer_dds_layout(source, source_nodes=metadata)
    assert style(actual).get('flexDirection') is None
    assert all(style(child).get('position') == 'absolute' for child in actual['children'])


def test_fractional_matrix_columns_keep_their_distinct_vertical_bands():
    source, metadata = fractional_columns_example()
    first, second = source['children']
    first['rowDims']['height'] = 21
    metadata['left']['frame']['height'] = 21
    source['children'].extend([painted('left-bottom', 1, 21, 10, 20), painted('right-bottom', 10, 20, 10, 21)])
    metadata['left-bottom'] = {'frame': {'left': .25, 'top': 21, 'width': 9.75, 'height': 20}}
    metadata['right-bottom'] = {'frame': {'left': 10, 'top': 20, 'width': 10, 'height': 21}}
    source['rowDims']['height'] = 41
    actual = infer_dds_layout(source, source_nodes=metadata)
    assert style(actual)['flexDirection'] == 'row'
    assert [[child['layerId'] for child in col['children']] for col in actual['children']] == [['left', 'left-bottom'], ['right', 'right-bottom']]
    assert all(style(col)['flexDirection'] == 'column' for col in actual['children'])


def test_explicit_empty_shape_projection_preserves_its_frame_and_warning_without_invented_paint():
    empty = node('empty', 20, 30, 40, 50, style={'borderRadius': '7px'}, ddsEmptyShapeProjection=True,
                 conversionWarnings=[{'code': 'dds_empty_shape_projection', 'reason': 'source paint is absent'}])
    source = page(empty)
    actual = infer_dds_layout(source)
    retained = by_id(actual, 'empty')
    assert retained['rowDims'] == empty['rowDims']
    assert retained['conversionWarnings'] == empty['conversionWarnings']
    assert not retained.get('uiType')
    assert not {'backgroundColor', 'background', 'border'} & style(retained).keys()
    ordinary = deepcopy(source)
    ordinary['children'][0].pop('ddsEmptyShapeProjection')
    assert not infer_dds_layout(ordinary)['children']
    assert not infer_layout(source)['children']


def test_bounded_late_shadow_menu_is_an_overlay_without_changing_its_original_parent():
    menu = painted('menu', 40, 45, 80, 70, style={'boxShadow': '0px 2px 4px rgba(0,0,0,.2)'},
                   children=[text('item', 48, 53, 50, 20)])
    source = page(painted('panel', 0, 0, 300, 200, children=[
        text('heading', 20, 10, 100, 20), text('choice', 40, 35, 50, 20), image('arrow', 96, 42), menu,
    ]))
    actual = infer_dds_layout(source)
    panel = by_id(actual, 'panel')
    assert panel['children'][-1]['layerId'] == 'menu'
    assert (style(by_id(actual, 'menu'))['left'], style(by_id(actual, 'menu'))['top']) == (40, 45)
    assert style(by_id(actual, 'menu'))['position'] == 'absolute'
    assert style(by_id(actual, 'menu'))['flexDirection'] == 'column'
    assert 'zIndex' not in style(by_id(actual, 'menu'))


@pytest.mark.parametrize('change', ['later_paint', 'outside_paint', 'unknown_shadow', 'no_shadow'])
def test_shadow_menu_overlay_requires_bounded_contained_paint_and_no_later_conflict(change):
    effects = {'outside_paint': '250px 0 0 red', 'unknown_shadow': 'var(--shadow)', 'no_shadow': 'none'}
    menu = painted('menu', 40, 45, 80, 70, style={'boxShadow': effects.get(change, '0px 2px 4px rgba(0,0,0,.2)')},
                   children=[text('item', 48, 53, 50, 20)])
    siblings = [text('choice', 40, 35, 50, 20), menu]
    if change == 'later_paint':
        siblings.append(painted('later', 50, 50, 20, 20))
    source = page(painted('panel', 0, 0, 300, 200, children=siblings))
    actual = infer_dds_layout(source)
    assert by_id(actual, 'menu') not in by_id(actual, 'panel')['children'] or style(by_id(actual, 'choice')).get('position') == 'absolute'


def empty_anchor_example(*, change=None):
    anchor = node('anchor', 80, 50, 120, 100, style={'borderRadius': '8px'}, ddsEmptyShapeProjection=True)
    children = [anchor]
    if change == 'competing':
        children.append(node('other-anchor', 70, 45, 140, 110, style={'borderRadius': '8px'}, ddsEmptyShapeProjection=True))
    if change == 'ordinary':
        anchor.pop('ddsEmptyShapeProjection')
        style(anchor)['backgroundColor'] = 'red'
    effect = {'opacity': {'opacity': .5}, 'clip': {'overflow': 'hidden'}, 'transform': {'transform': 'scale(2)'}}.get(change, {})
    panel = painted('panel', 80 if change == 'outside_parent' else 0, 0, 240, 200, children=children, style=effect)
    bubble = painted('bubble', 50, 40, 80, 20, children=[text('message', 54, 43, 72, 14)])
    pointer = image('pointer', 50, 60, 80, 4)
    cohort = node('source-wrapper', 50, 40, 80, 24, children=[bubble, pointer])
    root_children = [panel]
    if change in ('later_paint', 'unknown_paint'):
        root_children.append(painted('intervening', 60, 45, 20, 20, style={'filter': 'blur(2px)'} if change == 'unknown_paint' else {}))
    root_children.extend([bubble, pointer] if change == 'no_cohort' else [cohort])
    return page(*root_children)


def test_empty_shape_anchor_adopts_a_source_cohort_with_negative_absolute_offsets():
    source = empty_anchor_example()
    before = deepcopy(source)
    actual = infer_dds_layout(source)
    assert source == before
    anchor = by_id(actual, 'anchor')
    assert [n['layerId'] for n in anchor['children']] == ['bubble', 'pointer']
    assert style(anchor)['position'] == 'absolute'
    assert (style(anchor)['left'], style(anchor)['top']) == (80, 50)
    assert (style(by_id(actual, 'bubble'))['left'], style(by_id(actual, 'bubble'))['top']) == (-30, -10)
    assert (style(by_id(actual, 'pointer'))['left'], style(by_id(actual, 'pointer'))['top']) == (-30, 10)
    assert not any('zIndex' in style(n) for n in anchor['children'])
    assert all([n['layerId'] for n in walk(actual)].count(identity) == 1 for identity in ('bubble', 'pointer'))


@pytest.mark.parametrize('change', ['competing', 'ordinary', 'opacity', 'clip', 'transform', 'outside_parent',
                                     'later_paint', 'unknown_paint', 'no_cohort'])
def test_empty_anchor_adoption_requires_unambiguous_source_cohort_and_complete_safe_scope(change):
    source = empty_anchor_example(change=change)
    actual = infer_dds_layout(source)
    assert not by_id(actual, 'anchor')['children']
    assert 'bubble' not in {n['layerId'] for n in walk(by_id(actual, 'panel'))}


def test_late_text_crossing_empty_shape_envelope_is_a_local_overlay():
    source = page(painted('panel', 0, 0, 300, 200, children=[
        node('anchor', 100, 60, 20, 80, style={'borderRadius': '4px'}, ddsEmptyShapeProjection=True),
        text('annotation', 70, 130, 100, 20), painted('control', 70, 160, 100, 30),
    ]))
    actual = infer_dds_layout(source)
    annotation = by_id(actual, 'annotation')
    assert by_id(actual, 'panel')['children'][-1]['layerId'] == 'annotation'
    assert style(annotation)['position'] == 'absolute'
    assert (style(annotation)['left'], style(annotation)['top']) == (70, 130)
    assert 'zIndex' not in style(annotation)


@pytest.mark.parametrize('conflict', ['shadow_only', 'layout', 'content', 'unknown'])
def test_empty_anchor_annotation_only_permits_known_shadow_extension_order_change(conflict):
    control = painted('control', 70, 160 if conflict != 'layout' else 145, 100, 30,
                      style={'boxShadow': '0px -8px 8px rgba(0,0,0,.2)'})
    if conflict == 'content':
        control['children'] = [text('escaping-content', 80, 140, 40, 15)]
    elif conflict == 'unknown':
        style(control)['boxShadow'] = 'var(--shadow)'
    source = page(painted('panel', 0, 0, 300, 220, children=[
        node('anchor', 100, 60, 20, 80, style={'borderRadius': '4px'}, ddsEmptyShapeProjection=True),
        text('annotation', 70, 130, 100, 20), control,
    ]))
    actual = infer_dds_layout(source)
    annotation = by_id(actual, 'annotation')
    if conflict == 'shadow_only':
        assert by_id(actual, 'panel')['children'][-1]['layerId'] == 'annotation'
        assert style(annotation)['position'] == 'absolute'
        assert annotation['conversionWarnings'][0]['code'] == 'dds_annotation_shadow_order'
        assert annotation['conversionWarnings'][0]['layerIds'] == ['control']
    else:
        assert not annotation.get('conversionWarnings')
        assert by_id(actual, 'panel')['children'][-1]['layerId'] != 'annotation'


@pytest.mark.parametrize('change', [None, 'ordinary', 'not_rotated', 'wide', 'not_covering', 'effect', 'later'])
def test_thin_raster_pointer_remains_flow_below_a_following_full_height_body(change):
    pointer = image('pointer', 6, 42, 1, 6)
    body = painted('body', 6, 0, 194, 100, children=[text('caption', 20, 20, 60, 20)])
    metadata = {'pointer': {'rotation': 270, 'hasExportDDSImage': True,
                            'frame': {'left': 6, 'top': 41.5, 'width': .001, 'height': 6}}}
    if change == 'ordinary':
        metadata['pointer']['hasExportDDSImage'] = False
    elif change == 'not_rotated':
        metadata['pointer']['rotation'] = 0
    elif change == 'wide':
        metadata['pointer']['frame']['width'] = 5
    elif change == 'not_covering':
        body['rowDims']['left'] = 20
    elif change == 'effect':
        style(body)['opacity'] = .5
    children = [pointer, body]
    if change == 'later':
        children.append(painted('late', 5, 30, 20, 20))
    actual = infer_dds_layout(page(painted('popover', 0, 0, 200, 100, children=children)), source_nodes=metadata)
    if change is None:
        assert style(by_id(actual, 'popover'))['flexDirection'] == 'column'
        assert style(by_id(actual, 'pointer')).get('position') != 'absolute'
        assert style(by_id(actual, 'pointer'))['margin'] == '42px 0 0 6px'
        assert style(by_id(actual, 'body'))['position'] == 'absolute'
        assert 'zIndex' not in style(by_id(actual, 'body'))
    else:
        assert not (style(by_id(actual, 'popover')).get('flexDirection') == 'column'
                    and style(by_id(actual, 'pointer')).get('position') != 'absolute'
                    and style(by_id(actual, 'body')).get('position') == 'absolute')


@pytest.mark.parametrize('cohort,has_matrix', [(True, True), (False, True), (True, False)])
def test_overlay_source_cohort_keeps_its_single_painted_cell_as_a_matrix_row(cohort, has_matrix):
    annotation = text('annotation', 80, 130, 100, 20)
    control = painted('control', 80, 170, 100, 30)
    contents = [painted('first', 20, 30, 100, 50)]
    if has_matrix:
        contents.append(painted('second', 180, 30, 100, 50))
    contents.append(node('anchor', 100, 80, 20, 60, ddsEmptyShapeProjection=True))
    contents.extend([node('cohort', 80, 130, 100, 70, children=[annotation, control])] if cohort else [annotation, control])
    actual = infer_dds_layout(page(painted('panel', 0, 0, 300, 240, children=contents)))
    parent = next(n for n in walk(actual) if any(c['layerId'] == 'control' for c in n.get('children', [])))
    if cohort and has_matrix:
        assert parent['layerId'] != 'panel'
        assert style(parent)['flexDirection'] == 'row'
        assert [c['layerId'] for c in parent['children']] == ['control']
        assert parent['rowDims'] == control['rowDims']
    else:
        assert parent['layerId'] == 'panel'


@pytest.mark.parametrize('change', [None, 'ordinary', 'offset_column', 'scope', 'later_paint', 'unknown'])
def test_later_same_column_cards_overlay_a_preceding_explicit_hairline_projection(change):
    line = painted('projected-line', 25, 55, 1, 155, ddsRotatedHairlineProjection=change != 'ordinary')
    first = painted('first', 10, 20, 100, 60, children=[text('caption', 20, 25, 50, 20), line])
    second = painted('second', 20 if change == 'offset_column' else 10, 100, 100, 60)
    third = painted('third', 10, 180, 100, 60)
    children = [first, second, third]
    if change in ('later_paint', 'unknown'):
        children.append(painted('late', 20, 130, 20, 20, style={'filter': 'blur(2px)'} if change == 'unknown' else {}))
    parent = painted('panel', 0, 0, 180, 280, children=children,
                     style={'opacity': .5} if change == 'scope' else {})
    actual = infer_dds_layout(page(parent))
    if change is None:
        assert [c['layerId'] for c in by_id(actual, 'panel')['children']] == ['first', 'second', 'third']
        assert style(by_id(actual, 'first')).get('position') != 'absolute'
        assert style(by_id(actual, 'second'))['position'] == 'absolute'
        assert style(by_id(actual, 'third'))['position'] == 'absolute'
        assert style(by_id(actual, 'first'))['margin'] == '20px 0 0 10px'
    else:
        assert (style(by_id(actual, 'second')).get('position') != 'absolute'
                or 'zIndex' in style(by_id(actual, 'second'))
                or by_id(actual, 'second') not in by_id(actual, 'panel')['children'])


@pytest.mark.parametrize('change', [None, 'ordinary', 'no_intersection', 'scope', 'later_paint', 'unknown'])
def test_root_card_overlay_uses_a_real_crossing_projection_in_an_earlier_subtree(change):
    line = painted('line', 70, 70, 1, 110, ddsRotatedHairlineProjection=change != 'ordinary')
    nested = painted('nested', 20, 20, 80, 70, children=[line],
                     style={'opacity': .5} if change == 'scope' else {})
    app = painted('app', 0, 0, 150, 100, children=[nested])
    card = painted('card', 160 if change == 'no_intersection' else 50, 120, 80, 70,
                   children=[text('heading', 60, 125, 30, 10),
                             painted('a', 60, 150, 20, 20), painted('b', 90, 150, 20, 20)])
    children = [app, card]
    if change in ('later_paint', 'unknown'):
        children.append(painted('late', 80, 140, 20, 20, style={'filter': 'blur(2px)'} if change == 'unknown' else {}))
    source = page(*children)
    actual = infer_dds_layout(source)
    result = by_id(actual, 'card')
    if change is None:
        assert actual['children'][-1]['layerId'] == 'card'
        assert style(result)['position'] == 'absolute'
        assert (style(result)['left'], style(result)['top']) == (50, 120)
        assert result['children'][0]['layerId'] == 'heading'
        assert style(result['children'][0])['margin'] == '5px 0 0 10px'
    else:
        assert (style(result).get('position') != 'absolute' or 'zIndex' in style(result)
                or result not in actual['children'])


@pytest.mark.parametrize('multicolumn', [False, True])
def test_multicolumn_title_canvas_keeps_a_single_panel_body_band_as_a_row(multicolumn):
    headings = [painted('heading-a', 0, 0, 100, 20, children=[text('title-a', 10, 2, 70, 14)])]
    if multicolumn:
        headings.append(painted('heading-b', 120, 0, 100, 20, children=[text('title-b', 130, 2, 70, 14)]))
    source = page(*headings, painted('body', 120, 50, 100, 80), width=240, height=180)
    actual = infer_dds_layout(source)
    parent = next(n for n in walk(actual) if any(c['layerId'] == 'body' for c in n.get('children', [])))
    assert (parent['layerId'] != 'root') is multicolumn
    if multicolumn:
        assert parent['rowDims'] == by_id(actual, 'body')['rowDims']
        assert style(parent)['flexDirection'] == 'row'


def test_dds_final_overflow_gap_is_positive_without_altering_interior_overlap_or_source_layout():
    source = page(text('first', 0, 0, 20, 20), text('second', 0, 10, 20, 100), width=40, height=100)
    from lanhu_codegen.figma_dds_layout import _place_dds
    from lanhu_codegen.figma_layout import _place
    actual, conservative = deepcopy(source), deepcopy(source)
    _place_dds(actual, 'column')
    _place(conservative, 'column')
    assert style(by_id(actual, 'second'))['margin'] == '-10px 0 10px 0'
    assert style(by_id(conservative, 'second'))['margin'] == '-10px 0 -10px 0'
    assert not any('flexShrink' in style(c) for c in actual['children'])
    assert all(style(c)['flexShrink'] == 0 for c in conservative['children'])


def test_overflow_edge_distance_does_not_become_a_symmetric_positive_inset():
    from lanhu_codegen.figma_dds_layout import _place_dds
    source = page(text('first', 0, 10, 20, 20), text('second', 0, 40, 20, 70), width=40, height=100)
    _place_dds(source, 'column')
    assert 'justifyContent' not in style(source)
    assert style(by_id(source, 'second'))['margin'] == '10px 0 10px 0'


@pytest.mark.parametrize('kind,direction,retain', [('text', 'column', True), ('image', 'column', True),
                                                  ('block', 'column', True), ('text', 'row', False)])
def test_columns_retain_the_gap_between_two_distributed_children(kind, direction, retain):
    from lanhu_codegen.figma_dds_layout import _place_dds
    maker = text if kind == 'text' else image if kind == 'image' else painted
    second = maker('second', 0 if direction == 'column' else 24, 24 if direction == 'column' else 0, 20, 20)
    source = page(maker('first', 0, 0, 20, 20), second, width=20 if direction == 'column' else 44,
                  height=44 if direction == 'column' else 20)
    _place_dds(source, direction)
    assert style(source)['justifyContent'] == 'space-between'
    assert (style(second).get('marginTop') == 4) is retain
