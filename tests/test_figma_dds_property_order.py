"""DDS declaration phases depend on source structure and the final layout.

The paired schemas here are test-only order oracles. Their declaration order is
scrambled before normalization; no reference schema enters Figma conversion.
"""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from lanhu_codegen.figma_schema import _normalize_dds_properties


def node(*, children=(), direction="column", kind="lanhublock", ui_type="", **styles):
    return {
        "type": kind, "uiType": ui_type, "layerId": "source-container",
        "eleName": "unrelated name", "props": {"className": "unrelated_class",
            "style": {"justifyContent": "flex-center", "flexDirection": direction,
                      "display": "flex", "height": 37, "width": 123, **styles}},
        "children": list(children),
    }


def leaf(kind="lanhutext"):
    return {"type": kind, "layerId": "leaf", "props": {"style": {"height": 11, "width": 21}}, "children": []}


def raw_sources(*kinds):
    return {"source-container": {"type": "artboard", "name": "unrelated source name",
                                 "layers": [{"type": kind} for kind in kinds]}}


def ordered(tree, sources):
    _normalize_dds_properties(tree, source_nodes=sources)
    return list(tree["props"]["style"])


@pytest.mark.parametrize("raw_kind,output_kind", [("textLayer", "lanhutext"), ("artboard", "lanhuimage")])
def test_retained_single_child_column_assigns_width_after_its_layout(raw_kind, output_kind):
    tree = node(children=[leaf(output_kind)], border="1px solid red", marginTop=3)
    tree["props"]["style"].pop("justifyContent")
    before, sources = deepcopy(tree), raw_sources(raw_kind)
    sources_before = deepcopy(sources)
    assert ordered(tree, sources) == ["height", "border", "marginTop", "display", "flexDirection", "width"]
    assert tree == before  # Object equality ignores order: all values and other fields remain intact.
    assert sources == sources_before


def test_column_with_direct_source_text_assigns_width_before_multi_child_layout():
    tree = node(children=[node(children=[leaf()], direction="row"), node(children=[leaf("lanhuimage")], direction="row")],
                backgroundColor="white", margin="7px 0 9px 3px")
    assert ordered(tree, raw_sources("textLayer", "artboard")) == [
        "backgroundColor", "height", "width", "display", "flexDirection", "justifyContent", "margin",
    ]


def test_one_source_child_expanding_to_several_output_children_is_not_a_single_child_wrapper():
    tree = node(children=[leaf("lanhuimage"), leaf()], backgroundColor="white")
    tree["eleName"] = "Block_misleading"
    tree["props"]["className"] = "text-wrapper_misleading"
    assert ordered(tree, raw_sources("artboard")) == [
        "backgroundColor", "width", "height", "display", "flexDirection", "justifyContent",
    ]


def test_flattened_text_matrix_assigns_width_before_its_absolute_placement():
    rows, raw_texts = [], []
    for row_index in range(2):
        leaves = []
        for column in range(2):
            identity = f"cell-{row_index}-{column}"
            item = leaf()
            item["layerId"] = identity
            leaves.append(item)
            raw_texts.append({"id": identity, "type": "textLayer"})
        row = node(children=leaves, direction="row")
        row["layerId"] = f"inferred-row-{row_index}"
        rows.append(row)
    tree = node(children=rows, position="absolute", left=6, top=0, borderRadius="8px")
    sources = raw_sources("artboard")
    sources["source-container"]["layers"][0]["layers"] = raw_texts
    sources.update({item["id"]: item for item in raw_texts})
    untouched = deepcopy(tree)
    assert ordered(tree, sources) == ["borderRadius", "height", "width", "position", "left", "top",
                                      "display", "flexDirection", "justifyContent"]
    # Global source membership alone cannot prove that these rows came from
    # this wrapper. Unrelated texts keep the ordinary declaration phase.
    sources["source-container"]["layers"][0]["layers"] = []
    assert ordered(untouched, sources)[:6] == ["borderRadius", "position", "left", "top", "width", "height"]


@pytest.mark.parametrize("child_count", [1, 2])
def test_shape_adopting_one_flow_child_delays_placement_but_multi_child_layout_does_not(child_count):
    tree = node(children=[leaf() for _ in range(child_count)], position="absolute", left=0, top=0)
    sources = {"source-container": {"type": "shapeLayer", "layers": []}}
    keys = ordered(tree, sources)
    assert (keys.index("position") > keys.index("flexDirection")) == (child_count == 1)
    assert (keys.index("height") < keys.index("width")) == (child_count == 1)


def test_relative_radius_precedes_position_only_for_dds_mode():
    tree = node(position="relative", borderRadius="4px")
    legacy = deepcopy(tree)
    assert ordered(tree, {})[:2] == ["borderRadius", "position"]
    assert ordered(legacy, None)[:2] == ["position", "borderRadius"]


def test_null_source_child_layers_are_an_empty_collection():
    tree = node(children=[leaf("lanhuimage")])
    sources = raw_sources("artboard")
    sources["source-container"]["layers"][0]["layers"] = None
    expected = deepcopy(sources)
    assert ordered(tree, sources) == ["height", "display", "flexDirection", "justifyContent", "width"]
    assert sources == expected


@pytest.mark.parametrize("children", [[], [leaf()], [leaf("lanhuimage")]])
def test_decorative_leaves_and_synthetic_wrappers_keep_ordinary_dimensions(children):
    tree = node(children=deepcopy(children), backgroundColor="white")
    tree["props"]["className"] = "text-wrapper_misleading"
    assert ordered(tree, {})[:3] == ["backgroundColor", "width", "height"]


@pytest.mark.parametrize("ui_type", ["ImageText", "TextGroup", "UnknownWidget"])
def test_semantic_components_do_not_enter_retained_column_width_rule(ui_type):
    tree = node(children=[leaf()], ui_type=ui_type)
    assert ordered(tree, raw_sources("textLayer")) == [
        "width", "height", "display", "flexDirection", "justifyContent",
    ]


@pytest.mark.parametrize("direction,count,ui_type,flow", [
    ("row", 2, "", ["flexDirection", "display"]),
    ("row", 1, "", ["display", "flexDirection"]),
    ("column", 2, "", ["display", "flexDirection"]),
    ("row", 2, "ImageText", ["flexDirection", "display"]),
    ("column", 2, "ImageText", ["display", "flexDirection"]),
    ("row", 2, "TextGroup", ["display", "flexDirection"]),
    ("row", 2, "UnknownWidget", ["display", "flexDirection"]),
])
def test_ordinary_row_and_explicit_image_text_use_their_final_layout(direction, count, ui_type, flow):
    tree = node(children=[leaf() for _ in range(count)], direction=direction, ui_type=ui_type)
    assert ordered(tree, {}) == ["width", "height", *flow, "justifyContent"]


@pytest.mark.parametrize("margin,value,before_flow", [("marginLeft", 8, True), ("margin", "8px 0 3px 4px", False)])
def test_single_axis_margin_precedes_layout_but_shorthand_follows_it(margin, value, before_flow):
    tree = node(children=[leaf(), leaf()], **{margin: value})
    keys = ordered(tree, {})
    assert (keys.index(margin) < keys.index("justifyContent")) == before_flow
    assert tree["props"]["style"][margin] == value


def test_missing_source_metadata_keeps_legacy_source_mode_order_without_class_name_hints():
    tree = node(children=[leaf()], backgroundColor="white", border="1px solid red", marginTop=4)
    assert ordered(tree, None) == [
        "backgroundColor", "height", "width", "border", "display", "flexDirection", "justifyContent", "marginTop",
    ]
    row = node(children=[leaf(), leaf()], direction="row", marginLeft=3)
    assert ordered(row, None) == ["width", "height", "display", "flexDirection", "justifyContent", "marginLeft"]


def test_unknown_style_values_survive_and_identity_names_are_not_ordering_hints():
    tree = node(children=[leaf()], boxShadow="0 1px 2px black", customProperty="preserved")
    source = raw_sources("textLayer")
    before = deepcopy(tree)
    first = ordered(tree, source)
    renamed = deepcopy(before)
    renamed["layerId"] = "new-id"
    renamed["eleName"] = "section_col_row_image-text"
    renamed["props"]["className"] = "page"
    assert ordered(renamed, {"new-id": source["source-container"]}) == first
    assert tree == before


@pytest.mark.parametrize("schema_path,raw_path", [
    ("official_no_permission/schema.json", "figma_no_permission/v5.json"),
    ("figma_complex/official-schema.json", "figma_complex/raw.json"),
    ("figma_report/official-schema.json", "figma_report/raw.json"),
    ("figma_network/official-schema.json", "figma_network/raw.json"),
    ("figma_application/official-schema.json", "figma_application/raw.json"),
    ("figma_aggregation/official-schema.json", "figma_aggregation/raw.json"),
])
def test_paired_declaration_sequences_are_recovered_after_scrambling_order_and_names(schema_path, raw_path):
    fixtures = Path(__file__).parent / "fixtures"
    reference = json.loads((fixtures / schema_path).read_text())
    raw = json.loads((fixtures / raw_path).read_text())
    sources = {}

    def index_source(item):
        sources[item["id"]] = item
        for child in item.get("layers", []):
            index_source(child)

    def walk(item):
        yield item
        for child in item.get("children", []):
            yield from walk(child)

    index_source(raw["artboard"])
    before = deepcopy(raw)
    actual = deepcopy(reference)
    for item in walk(actual):
        item["props"]["style"] = dict(reversed(item["props"]["style"].items()))
        item["props"]["className"] = "discarded"
        item["eleName"] = "discarded"
    _normalize_dds_properties(actual, source_nodes=sources)
    for expected, observed in zip(walk(reference), walk(actual)):
        assert list(observed["props"]["style"]) == list(expected["props"]["style"])
        assert observed["props"]["style"] == expected["props"]["style"]
    assert raw == before
