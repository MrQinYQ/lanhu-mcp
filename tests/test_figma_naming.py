"""Semantic naming is stable and independent of example identities/content."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from lanhu_codegen.figma_naming import assign_class_names


def node(kind="lanhublock", *, children=None, width=100, height=20, left=0, top=0, ui_type=""):
    return {"id": "source-id", "layerId": "source-layer", "type": kind, "uiType": ui_type,
            "rowDims": {"left": left, "top": top, "width": width, "height": height},
            "props": {"className": "old-name", "style": {"color": "red"}}, "children": children or []}


def walk(root):
    yield root
    for child in root.get("children", []):
        yield from walk(child)


def classes(root):
    return [item["props"]["className"] for item in walk(root)]


def without_classes(root):
    result = deepcopy(root)
    for item in walk(result):
        item.get("props", {}).pop("className", None)
    return result


def test_matches_all_example_names_after_removing_original_names_and_source_content():
    fixture = Path(__file__).parent / "fixtures" / "official_no_permission" / "schema.json"
    official = json.loads(fixture.read_text())
    expected = classes(official)
    input_tree = deepcopy(official)
    for index, item in enumerate(walk(input_tree)):
        item["id"] = f"unrelated-node-{index}"
        item["layerId"] = f"unrelated-layer-{index}"
        item["eleName"] = "not a semantic hint"
        item["props"]["className"] = "discarded"
        if "text" in item["props"]:
            item["props"]["text"] = "unrelated content"
        item["data"] = {"value": "unrelated data"}
    before = deepcopy(input_tree)
    actual = assign_class_names(input_tree)
    assert len(expected) == 38
    assert classes(actual) == expected
    assert input_tree == before
    assert without_classes(actual) == without_classes(before)
    assert classes(assign_class_names(actual)) == expected


def test_complex_fixture_semantic_names_match_without_claiming_generic_alias_parity():
    fixture = Path(__file__).parent / "fixtures" / "figma_complex" / "official-schema.json"
    official = json.loads(fixture.read_text())
    input_tree = deepcopy(official)
    for index, item in enumerate(walk(input_tree)):
        item["id"] = f"unrelated-node-{index}"
        item["layerId"] = f"unrelated-layer-{index}"
        item["eleName"] = "unrelated element"
        item["props"]["className"] = "discarded"
        item["data"] = {"value": "unrelated data"}
        if "text" in item["props"]:
            item["props"]["text"] = "unrelated content"
    before = deepcopy(input_tree)
    actual = assign_class_names(input_tree)

    # Generic synonym selection is still unproven. This assertion covers the
    # independently inferable roles and their counters, including TextGroup
    # containers, pure-image wrappers, 24 px labels and plain input text.
    generic_prefixes = {"block", "group", "box", "section"}
    expected_names = classes(official)
    actual_names = classes(actual)
    assert len(actual_names) == len(expected_names)
    for expected, actual_name in zip(expected_names, actual_names):
        if expected.split("_")[0] not in generic_prefixes:
            assert actual_name == expected
    assert input_tree == before
    assert without_classes(actual) == without_classes(before)


@pytest.mark.parametrize("width,height,prefix", [
    (14, 14, "thumbnail"), (16, 16, "thumbnail"), (24, 24, "label"), (30, 30, "label"),
    (32, 32, "label"), (44, 44, "label"), (64, 64, "label"), (128, 128, "image"),
    (22, 17, "image"), (52, 16, "image"), (105, 79, "image"),
    (16, 16.25, "thumbnail"), (0, 0, "image"), (None, None, "image"),
])
def test_documented_image_size_heuristics(width, height, prefix):
    tree = node("lanhupage", children=[node("lanhuimage", width=width, height=height)])
    assert classes(assign_class_names(tree)) == ["page", f"{prefix}_1"]


def test_image_dimensions_can_come_from_style_when_row_dims_are_absent():
    image = node("lanhuimage")
    image.pop("rowDims")
    image["props"]["style"].update(width="16px", height="16px")
    assert classes(assign_class_names(node(children=[image]))) == ["page", "thumbnail_1"]


def test_image_text_context_and_text_only_wrappers_have_independent_counters():
    pair = node(ui_type="ImageText", children=[node("lanhuimage", width=16, height=16), node("lanhutext")])
    texts = node(children=[node("lanhutext"), node("lanhutext")])
    tree = node("lanhupage", children=[pair, texts, deepcopy(pair)])
    assert classes(assign_class_names(tree)) == [
        "page", "image-text_1", "thumbnail_1", "text-group_1", "text-wrapper_1",
        "text_1", "text_2", "image-text_2", "thumbnail_2", "text-group_2",
    ]


def test_unmarked_horizontal_pair_does_not_infer_image_text_semantics():
    row = node(children=[node("lanhuimage", width=16, height=16, top=3), node("lanhutext", left=24, height=22)])
    column = node(children=[node("lanhuimage", width=100, height=100), node("lanhutext", top=120)])
    named = assign_class_names(node("lanhupage", children=[row, column]))
    assert named["children"][0]["props"]["className"] == "block_1"
    assert named["children"][0]["children"][1]["props"]["className"] == "text_1"
    assert named["children"][1]["props"]["className"] == "block_2"
    assert named["children"][1]["children"][1]["props"]["className"] == "text_2"


def test_text_group_marker_on_a_container_overrides_text_wrapper_classification():
    texts = node(ui_type="TextGroup", children=[node("lanhutext"), node("lanhutext")])
    pair = node(ui_type="ImageText", children=[deepcopy(texts), node("lanhuimage", width=16, height=16)])
    named = assign_class_names(node("lanhupage", children=[texts, pair]))
    assert classes(named) == ["page", "text-group_1", "text_1", "text_2",
                              "image-text_1", "text-group_2", "text_3", "text_4", "thumbnail_1"]


def test_nonempty_image_only_containers_use_image_wrapper_independent_of_paint_and_direction():
    single = node(children=[node("lanhuimage", width=16, height=16)])
    single["props"]["style"].update(backgroundColor="white", flexDirection="column")
    multiple = node(children=[node("lanhuimage", width=30, height=30), node("lanhuimage", width=100, height=20)])
    multiple["props"]["style"]["flexDirection"] = "row"
    named = assign_class_names(node("lanhupage", children=[single, multiple]))
    assert classes(named) == ["page", "image-wrapper_1", "thumbnail_1", "image-wrapper_2", "label_1", "image_1"]


def test_input_with_text_and_trailing_icon_keeps_plain_text_semantics():
    control = node(width=224, height=32,
                   children=[node("lanhutext", width=154, height=22, left=12, top=5),
                             node("lanhuimage", width=14, height=14, left=198, top=9)])
    control["props"]["style"].update(backgroundColor="#f5f5f5", borderRadius="8px", flexDirection="row")
    control["children"][0]["props"]["text"] = "Any placeholder"
    named = assign_class_names(node("lanhupage", children=[control]))
    assert classes(named) == ["page", "block_1", "text_1", "thumbnail_1"]


def test_general_container_roles_and_decorative_leaf_blocks():
    nested = node(children=[node(children=[node(children=[node(children=[node("lanhuimage", width=80, height=80)])])])])
    named = assign_class_names(node("lanhupage", children=[nested, node(width=1, height=20)]))
    assert classes(named) == ["page", "block_1", "group_1", "box_1", "image-wrapper_1", "image_1", "group_2"]


def test_return_value_does_not_share_nested_style_or_children_with_input():
    tree = node("lanhupage", children=[node("lanhutext")])
    before = deepcopy(tree)
    result = assign_class_names(tree)
    result["children"][0]["props"]["style"]["color"] = "blue"
    result["children"].append(node())
    assert tree == before


@pytest.mark.parametrize("bad", [[], {"children": {}}, {"children": [None]}, {"props": []}])
def test_invalid_tree_shape_is_explicit(bad):
    with pytest.raises(ValueError):
        assign_class_names(bad)
