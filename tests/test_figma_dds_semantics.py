"""Evidence-bounded semantic grouping, independent of sample names and IDs.

The ordinary-export marker distinguishes the otherwise identical account
subtrees in the two paired designs. It is an inferred boundary, not a proven
description of Lanhu's complete semantic classifier.
"""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from lanhu_codegen.figma_dds_semantics import is_multicolumn_text_header, refine_dds_semantics
from lanhu_codegen.figma_layout import infer_layout


def node(identity, box, kind="lanhublock", *, children=(), style=None, **metadata):
    left, top, width, height = box
    result = {
        "id": identity, "layerId": identity, "type": kind, "componentName": kind,
        "rowDims": dict(zip(("left", "top", "width", "height"), box)),
        "props": {"className": identity, "style": {
            "position": "absolute", "left": left, "top": top,
            "width": width, "height": height, **(style or {}),
        }},
        "data": {"value": ""}, "children": list(children), "uiType": "",
        "uiTypeProb": {}, "alignJustify": {}, **metadata,
    }
    if kind == "lanhuimage":
        result["props"]["src"] = f"https://example.test/{identity}.png"
        result["data"]["value"] = result["props"]["src"]
        result["mergeEligible"] = True
    elif kind == "lanhutext":
        result["props"].update(text=identity, lines=1)
        result["data"]["value"] = identity
        result["props"]["style"].update(fontSize=14, lineHeight=height,
                                          fontFamily="Arial", whiteSpace="nowrap")
    return result


def page(*children):
    return node("page", (0, 0, 480, 260), "lanhupage", children=children)


def walk(root, key="children"):
    yield root
    for child in root.get(key, []):
        yield from walk(child, key)


def leaves(root):
    return {n["layerId"] for n in walk(root) if not n.get("children")}


def find(root, identity):
    return next(n for n in walk(root) if n["layerId"] == identity)


def semantic(root, kind):
    return [n for n in walk(root) if n.get("uiType") == kind]


def assert_original_geometry(before, after):
    known = {n["layerId"]: n for n in walk(before) if not n.get("children")}
    observed = {n["layerId"]: n for n in walk(after) if n["layerId"] in known}
    assert observed.keys() == known.keys()
    for identity, n in known.items():
        assert observed[identity]["rowDims"] == n["rowDims"]
        assert observed[identity]["data"] == n["data"]


def account_row(*, ordinary=True, avatar_left=180, arrow_left=311):
    avatar = node("avatar", (avatar_left, 16, 32, 32), "lanhuimage",
                  sourceHasOrdinaryImage=ordinary)
    first = node("account-name", (220, 11, 42, 22), "lanhutext")
    second = node("account-detail", (220, 33, 87, 20), "lanhutext")
    arrow = node("arrow", (arrow_left, 24, 16, 16), "lanhuimage")
    return infer_layout(page(node("header", (0, 0, 400, 64),
                                  children=[avatar, first, second, arrow],
                                  style={"backgroundColor": "white"})))


def test_explicit_ordinary_avatar_separates_right_hand_text_and_arrow():
    raw = account_row()
    before = deepcopy(raw)
    result = refine_dds_semantics(raw)
    assert raw == before
    groups = semantic(result, "ImageText")
    assert len(groups) == 1
    pair = groups[0]
    assert leaves(pair) == {"account-name", "account-detail", "arrow"}
    assert pair["rowDims"] == {"left": 220, "top": 11, "width": 107, "height": 42}
    assert pair["props"]["style"]["flexDirection"] == "row"
    text_group, arrow = pair["children"]
    assert text_group["uiType"] == "TextGroup"
    assert leaves(text_group) == {"account-name", "account-detail"}
    assert text_group["rowDims"] == {"left": 220, "top": 11, "width": 87, "height": 42}
    assert text_group["props"]["style"]["flexDirection"] == "column"
    assert arrow["layerId"] == "arrow"
    assert_original_geometry(before, result)
    assert refine_dds_semantics(result) == result


def test_same_geometry_without_ordinary_export_keeps_the_first_design_structure():
    raw = account_row(ordinary=False)
    before = deepcopy(raw)
    result = refine_dds_semantics(raw)
    assert not semantic(result, "ImageText")
    assert not semantic(result, "TextGroup")
    assert [leaves(n) for n in find(result, "header")["children"]] == [
        {"avatar"}, {"account-name", "account-detail"}, {"arrow"},
    ]
    assert raw == before
    assert_original_geometry(before, result)


@pytest.mark.parametrize("avatar_left,arrow_left", [(100, 311), (180, 380)])
def test_distant_ordinary_image_or_arrow_does_not_imply_an_account_pair(avatar_left, arrow_left):
    raw = account_row(avatar_left=avatar_left, arrow_left=arrow_left)
    result = refine_dds_semantics(raw)
    assert not semantic(result, "ImageText")
    assert_original_geometry(raw, result)


@pytest.mark.parametrize("effect", [
    {"backgroundColor": "red"},
    {"clipPath": "circle(40%)"},
    {"overflow": "hidden"},
])
def test_painted_or_clipped_text_container_is_not_reclassified_as_a_plain_pair(effect):
    raw = account_row()
    column = next(n for n in walk(raw) if leaves(n) == {"account-name", "account-detail"})
    column["props"]["style"].update(effect)
    column["style"] = deepcopy(column["props"]["style"])
    before = deepcopy(raw)
    result = refine_dds_semantics(raw)
    assert not semantic(result, "ImageText")
    assert raw == before
    after = next(n for n in walk(result) if leaves(n) == {"account-name", "account-detail"})
    assert all(after["props"]["style"][key] == value for key, value in effect.items())


def account_column(*, ordinary=True, avatar_top=24, detail_left=77):
    avatar = node("portrait", (108, avatar_top, 44, 44), "lanhuimage",
                  sourceHasOrdinaryImage=ordinary)
    first = node("full-name", (0, 80, 260, 24), "lanhutext", style={"textAlign": "center"})
    second = node("contact", (detail_left, 108, 106, 20), "lanhutext")
    return infer_layout(page(node("profile", (0, 24, 260, 129),
                                  children=[avatar, first, second],
                                  style={"backgroundColor": "white"})))


def test_ordinary_portrait_groups_two_centered_lines_below_it():
    raw = account_column()
    before = deepcopy(raw)
    result = refine_dds_semantics(raw)
    assert raw == before
    groups = semantic(result, "TextGroup")
    assert len(groups) == 1
    group = groups[0]
    assert leaves(group) == {"full-name", "contact"}
    assert group["rowDims"] == {"left": 0, "top": 80, "width": 260, "height": 48}
    assert group["props"]["style"]["flexDirection"] == "column"
    assert not semantic(result, "ImageText")
    assert [leaves(n) for n in find(result, "profile")["children"]] == [
        {"portrait"}, {"full-name", "contact"},
    ]
    assert_original_geometry(before, result)
    assert refine_dds_semantics(result) == result


@pytest.mark.parametrize("change", [
    {"ordinary": False}, {"avatar_top": -80}, {"detail_left": 130},
])
def test_missing_export_distant_portrait_or_misaligned_lines_stay_independent(change):
    raw = account_column(**change)
    result = refine_dds_semantics(raw)
    assert not semantic(result, "TextGroup")
    assert_original_geometry(raw, result)


def icon_description(*, ordinary=True, detail_left=42, gap=4, detail_effect=None):
    icon = node("status-icon", (16, 18, 18, 18), "lanhuimage", sourceHasOrdinaryImage=ordinary)
    title = node("title", (42, 16, 276, 22), "lanhutext")
    detail = node("description", (detail_left, 38 + gap, 276, 44), "lanhutext")
    footer = node("footer", (180, 102, 138, 32), style={"backgroundColor": "gray"})
    result = infer_layout(page(node("body", (0, 0, 334, 150),
                                    children=[icon, title, detail, footer],
                                    style={"backgroundColor": "white"})))
    if detail_effect:
        wrapper = node("detail-wrap", (detail_left, 38 + gap, 276, 44),
                       children=[find(result, "description")], style=detail_effect)
        body = find(result, "body")
        body["children"] = [wrapper if child.get("layerId") == "description" else child
                            for child in body["children"]]
    return result


def test_ordinary_status_icon_covers_title_and_detail_without_changing_geometry():
    raw = icon_description()
    before = deepcopy(raw)
    result = refine_dds_semantics(raw)
    groups = [n for n in semantic(result, "TextGroup") if n.get("children")]
    assert len(groups) == 1
    assert leaves(groups[0]) == {"title", "description"}
    assert groups[0]["rowDims"] == {"left": 42, "top": 16, "width": 276, "height": 70}
    assert find(result, "title")["uiType"] == ""
    pair = next(n for n in semantic(result, "ImageText") if "description" in leaves(n))
    assert leaves(pair) == {"status-icon", "title", "description"}
    assert raw == before
    assert_original_geometry(raw, result)
    assert refine_dds_semantics(result) == result


@pytest.mark.parametrize("footer_shift,expected", [(0, "flex-center"), (2, None)])
def test_description_regroup_preserves_centered_column_only_while_outer_insets_match(footer_shift, expected):
    raw = icon_description()
    body = find(raw, "body")
    body["props"]["style"]["justifyContent"] = "flex-center"
    find(raw, "footer")["rowDims"]["top"] += footer_shift
    before = deepcopy(raw)
    result = refine_dds_semantics(raw)
    assert find(result, "body")["props"]["style"].get("justifyContent") == expected
    assert len(find(result, "body")["children"]) == 2
    assert raw == before
    assert_original_geometry(before, result)


@pytest.mark.parametrize("changes", [{"ordinary": False}, {"detail_left": 45}, {"gap": 23},
                                     {"detail_effect": {"backgroundColor": "red"}},
                                     {"detail_effect": {"overflow": "hidden"}}])
def test_status_icon_does_not_absorb_unmarked_or_misaligned_description(changes):
    raw = icon_description(**changes)
    result = refine_dds_semantics(raw)
    assert not any(n.get("children") for n in semantic(result, "TextGroup"))
    assert_original_geometry(raw, result)


def repeated_cards(*, reuse=True, image_height=48, gap=12, caption_effect=None):
    cards = []
    for index, y in enumerate([0, 100]):
        avatar = node(f"avatar-{index}", (10, y + 10, 48, image_height), "lanhuimage")
        if reuse:
            avatar["props"]["src"] = avatar["data"]["value"] = "https://example.test/reused-avatar.png"
        title = node(f"title-{index}", (58 + gap, y + 10, 42, 22), "lanhutext")
        detail = node(f"detail-{index}", (58 + gap, y + 36, 200, 22), "lanhutext")
        cards.append(node(f"card-{index}", (0, y, 300, 80), children=[avatar, title, detail],
                          style={"backgroundColor": "white"}))
    result = infer_layout(page(*cards))
    if caption_effect:
        for n in walk(result):
            if n.get("type") == "lanhublock" and len(n.get("children", [])) == 2 and all(
                    c.get("type") == "lanhutext" for c in n["children"]):
                n["props"]["style"].update(caption_effect)
                n["style"] = deepcopy(n["props"]["style"])
    return result


def test_reused_square_avatar_with_equal_height_description_gets_text_column_role():
    raw = repeated_cards()
    before = deepcopy(raw)
    result = refine_dds_semantics(raw)
    groups = [n for n in semantic(result, "TextGroup") if n.get("children")]
    assert len(groups) == 2
    assert {frozenset(leaves(n)) for n in groups} == {
        frozenset({"title-0", "detail-0"}), frozenset({"title-1", "detail-1"})}
    assert raw == before
    assert_original_geometry(raw, result)
    assert refine_dds_semantics(result) == result


@pytest.mark.parametrize("changes", [{"reuse": False}, {"image_height": 40}, {"gap": 30},
                                     {"caption_effect": {"backgroundColor": "red"}},
                                     {"caption_effect": {"opacity": 0.5}}])
def test_caption_role_requires_reused_square_and_aligned_plain_description(changes):
    raw = repeated_cards(**changes)
    result = refine_dds_semantics(raw)
    assert not any(n.get("children") for n in semantic(result, "TextGroup"))
    assert_original_geometry(raw, result)


@pytest.mark.parametrize("raw_path,reference_path,expected_marker", [
    ("figma_no_permission/v5.json", "official_no_permission/schema.json", False),
    ("figma_complex/raw.json", "figma_complex/official-schema.json", True),
])
def test_marker_hypothesis_matches_both_paired_account_subtrees(raw_path, reference_path, expected_marker):
    """Verify the distinguishing evidence without source IDs or text matching."""
    fixture = Path(__file__).parent / "fixtures"
    raw = json.loads((fixture / raw_path).read_text())
    reference = json.loads((fixture / reference_path).read_text())
    candidates = []
    for parent in walk(raw["artboard"], "layers"):
        children = parent.get("layers", [])
        if len(children) != 2:
            continue
        avatar, tail = children
        af = avatar["frame"]
        if not avatar.get("hasExportDDSImage") or af["width"] != af["height"] or af["width"] != 32:
            continue
        descendants = []
        def retained(n):
            if n.get("hasExportDDSImage") or n.get("type") == "textLayer":
                descendants.append(n)
            else:
                for child in n.get("layers", []): retained(child)
        retained(tail)
        if len(descendants) == 3 and sum(n.get("type") == "textLayer" for n in descendants) == 2:
            candidates.append((avatar, {n["id"] for n in descendants}))
    assert len(candidates) == 1
    avatar, source_ids = candidates[0]
    assert avatar.get("hasExportImage", False) is expected_marker
    matching = [n for n in walk(reference) if n.get("uiType") == "ImageText" and leaves(n) == source_ids]
    assert bool(matching) is expected_marker


def titled_canvas(*, page_width=600, page_height=500, header_height=60,
                  first_left=40, first_top=140, lower_top=300,
                  lower_height=80, include_lower=True, textual_header=True):
    """A narrow painted title and two spatial content rows, with no sample data."""
    header_children = [node("canvas-heading", (60, 45, 160, 30), "lanhutext")] if textual_header else []
    header = node("heading-panel", (40, 30, 520, header_height), children=header_children,
                  style={"backgroundColor": "rgba(255,255,255,.1)", "borderRadius": "20px"})
    content = [node("upper-card", (first_left, first_top, 520, 100),
                    style={"backgroundColor": "white"})]
    if include_lower:
        content += [
            node("lower-left", (40, lower_top, 200, lower_height),
                 style={"backgroundColor": "white"}),
            node("lower-right", (280, lower_top, 280, lower_height),
                 style={"backgroundColor": "white"}),
        ]
    # The raw paint order deliberately need not already be spatial order.
    return infer_layout(node("canvas", (0, 0, page_width, page_height), "lanhupage",
                             children=[*content, header]))


def body_after_title(root):
    assert len(root["children"]) == 2
    title, body = root["children"]
    assert title["layerId"] == "heading-panel"
    assert body["type"] == "lanhublock"
    assert leaves(body) == {"upper-card", "lower-left", "lower-right"}
    return body


def test_canvas_body_uses_remaining_page_rectangle_for_multiple_content_rows():
    raw = titled_canvas()
    before = deepcopy(raw)
    assert len(raw["children"]) == 3  # Heading, upper card, lower spatial row.
    result = refine_dds_semantics(raw)
    assert raw == before
    body = body_after_title(result)
    assert body["rowDims"] == {"left": 0, "top": 90, "width": 600, "height": 411}
    assert body["props"]["style"]["flexDirection"] == "column"
    assert body["props"]["style"]["marginBottom"] == 1
    assert len(body["children"]) == 2
    assert leaves(body["children"][0]) == {"upper-card"}
    assert leaves(body["children"][1]) == {"lower-left", "lower-right"}
    known = {n["layerId"]: n["rowDims"] for n in walk(before)}
    after = {n["layerId"]: n["rowDims"] for n in walk(result)}
    assert all(after[identity] == frame for identity, frame in known.items())
    assert_original_geometry(before, result)
    assert refine_dds_semantics(result) == result


@pytest.mark.parametrize("page_width,page_height,header_height", [
    (600, 600, 60),  # Increasing page height enlarges only the remaining area.
    (720, 500, 60),  # The wrapper inherits page width, not title/content width.
    (600, 500, 80),  # A taller title moves the split without moving content.
    (720, 640, 80),
])
def test_canvas_body_follows_page_and_title_resize_without_moving_content(page_width, page_height, header_height):
    raw = titled_canvas(page_width=page_width, page_height=page_height, header_height=header_height)
    result = refine_dds_semantics(raw)
    body = body_after_title(result)
    split = 30 + header_height
    assert body["rowDims"] == {"left": 0, "top": split, "width": page_width,
                               "height": page_height - split + 1}
    assert body["props"]["style"]["marginBottom"] == 1
    assert find(result, "upper-card")["rowDims"]["top"] == 140
    assert find(result, "lower-left")["rowDims"]["top"] == 300
    assert_original_geometry(raw, result)
    assert refine_dds_semantics(result) == result


def test_moving_body_content_changes_its_margin_not_the_page_split():
    raw = titled_canvas(first_top=160, lower_top=320)
    result = refine_dds_semantics(raw)
    body = body_after_title(result)
    assert body["rowDims"] == {"left": 0, "top": 90, "width": 600, "height": 411}
    upper = find(result, "upper-card")
    style = upper["props"]["style"]
    if "margin" in style:
        assert style["margin"].split()[0] == "70px"
    else:
        assert style["marginTop"] == 70
    assert_original_geometry(raw, result)


def test_one_remaining_spatial_row_has_no_redundant_body_wrapper():
    raw = titled_canvas(include_lower=False)
    before = deepcopy(raw)
    result = refine_dds_semantics(raw)
    assert [n["layerId"] for n in result["children"]] == ["heading-panel", "upper-card"]
    assert raw == before
    assert_original_geometry(raw, result)


def test_two_same_row_cards_still_count_as_one_remaining_spatial_row():
    raw = titled_canvas()
    raw["children"] = [raw["children"][0], raw["children"][2]]
    assert len(raw["children"][1]["children"]) == 2
    result = refine_dds_semantics(raw)
    assert [n["layerId"] for n in result["children"]] == [n["layerId"] for n in raw["children"]]
    assert leaves(result["children"][1]) == {"lower-left", "lower-right"}
    assert_original_geometry(raw, result)


@pytest.mark.parametrize("change", [
    {"textual_header": False},
    {"first_left": 20},  # Still inside the page, outside the title's left edge.
    {"first_top": 80},  # Content overlaps the title rather than lying below it.
    {"lower_top": 460},  # Content bottom exceeds the 500px canvas.
])
def test_canvas_partition_rejects_missing_title_overlap_or_out_of_bounds_content(change):
    raw = titled_canvas(**change)
    before = deepcopy(raw)
    result = refine_dds_semantics(raw)
    assert [n["layerId"] for n in result["children"]] == [n["layerId"] for n in raw["children"]]
    assert raw == before
    assert_original_geometry(raw, result)


def test_canvas_partition_is_not_applied_to_a_row_page():
    raw = titled_canvas()
    raw["props"]["style"]["flexDirection"] = "row"
    raw["style"] = deepcopy(raw["props"]["style"])
    result = refine_dds_semantics(raw)
    assert [n["layerId"] for n in result["children"]] == [n["layerId"] for n in raw["children"]]
    assert_original_geometry(raw, result)


def panel_header():
    panels = [node(f"panel-{index}", (left, 30, 240, 60),
                   children=[node(f"caption-{index}", (left + 10, 40, 100, 30), "lanhutext")],
                   style={"backgroundColor": "white"}) for index, left in enumerate((40, 320))]
    header = node("header-band", (40, 30, 520, 60), children=panels,
                  style={"flexDirection": "row", "display": "flex"})
    header["props"]["style"].pop("position")
    return header


def test_disjoint_equal_title_panels_keep_body_rows_at_canvas_root():
    raw = titled_canvas()
    raw["children"][0] = panel_header()
    before = deepcopy(raw)
    assert is_multicolumn_text_header(raw["children"][0])
    result = refine_dds_semantics(raw)
    assert [n["layerId"] for n in result["children"]] == [n["layerId"] for n in raw["children"]]
    assert not any(n.get("ddsCanvasRemainder") for n in walk(result))
    assert_original_geometry(before, result)
    assert raw == before
    assert refine_dds_semantics(result) == result


@pytest.mark.parametrize("change", ["overlap", "different-width", "different-height", "different-top", "nontext", "unknown-paint"])
def test_multicolumn_title_requires_matching_text_panels_with_known_paint(change):
    header = panel_header()
    right = header["children"][1]
    if change == "overlap":
        right["rowDims"]["left"] = 100
    elif change == "different-width":
        right["rowDims"]["width"] = 200
    elif change == "different-height":
        right["rowDims"]["height"] = 55
    elif change == "different-top":
        right["rowDims"]["top"] += 10
    elif change == "nontext":
        right["children"][0]["type"] = "lanhuimage"
    else:
        right["props"]["style"]["filter"] = "blur(3px)"
    assert not is_multicolumn_text_header(header)


def test_parallel_text_leaves_inside_one_title_are_not_separate_title_panels():
    header = panel_header()
    header["children"] = [child["children"][0] for child in header["children"]]
    assert not is_multicolumn_text_header(header)
