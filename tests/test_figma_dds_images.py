"""DDS composition must preserve resources reused by independent instances."""

from copy import deepcopy

import pytest

from lanhu_codegen.figma_dds_images import build_dds_image_merge_policy
from lanhu_codegen.figma_layout import _merge_images


def image(identifier, src, x=0, y=0, size=16):
    dims = {"left": x, "top": y, "width": size, "height": size}
    return {"id": identifier, "layerId": identifier, "type": "lanhuimage", "children": [],
            "rowDims": dims, "props": {"src": src, "style": dict(dims)}}


def page(*nodes):
    return {"type": "lanhupage", "children": list(nodes)}


def composite_spy(calls):
    def compose(nodes):
        calls.append(deepcopy(nodes))
        frames = [node["rowDims"] for node in nodes]
        left = min(frame["left"] for frame in frames)
        top = min(frame["top"] for frame in frames)
        dims = {"left": left, "top": top,
                "width": max(frame["left"] + frame["width"] for frame in frames) - left,
                "height": max(frame["top"] + frame["height"] for frame in frames) - top}
        merged = deepcopy(nodes[-1])
        merged["rowDims"] = dims
        merged["props"].update(src="data:image/png;base64,composed", style=dict(dims))
        merged["sourceLayerIds"] = [node["layerId"] for node in nodes]
        return merged
    return compose


@pytest.mark.parametrize("size,gap", [(13, 5), (16, 20), (24, 16), (31, 7)])
def test_identical_local_geometry_merges_only_when_source_resources_are_unique(size, gap):
    first = image("first", "asset://first", size=size)
    second = image("second", "asset://second", x=size + gap, size=size)
    run = [first, second]
    unique = page(*run)
    reused = page(*deepcopy(run), image("unrelated-instance", "asset://first", x=800, y=500, size=size))
    original_run, original_unique, original_reused = deepcopy(run), deepcopy(unique), deepcopy(reused)
    calls = []
    assert len(_merge_images(run, composite_spy(calls), unique,
                             accept_merge=build_dds_image_merge_policy(unique))) == 1
    assert len(calls) == 1
    calls.clear()
    assert _merge_images(run, composite_spy(calls), reused,
                         accept_merge=build_dds_image_merge_policy(reused)) == run
    assert calls == []
    assert run == original_run and unique == original_unique and reused == original_reused


def test_repeated_four_icon_rows_stay_independent_without_raster_calls():
    rows = [[image(f"row-{row}-item-{column}", f"asset://{column}",
                   x=column * 40, y=row * 60, size=24) for column in range(4)] for row in range(2)]
    root = page(*(node for row in rows for node in row))
    policy = build_dds_image_merge_policy(root)
    calls = []
    for row in rows:
        assert _merge_images(row, composite_spy(calls), root, accept_merge=policy) == row
    assert calls == []


def test_unique_overlapping_fragments_are_still_eligible():
    nodes = [image("ground", "asset://ground", size=70), image("object", "asset://object", x=18, y=21, size=40)]
    root = page(*nodes)
    calls = []
    result = _merge_images(nodes, composite_spy(calls), root, accept_merge=build_dds_image_merge_policy(root))
    assert result[0]["sourceLayerIds"] == ["ground", "object"]
    assert len(calls) == 1


def test_usage_snapshot_does_not_depend_on_earlier_mutation_of_the_layout_tree():
    first = image("a", "asset://shared")
    second = image("b", "asset://other", x=36)
    duplicate = image("a-copy", "asset://shared", x=500)
    root = page(first, second, duplicate)
    policy = build_dds_image_merge_policy(root)
    root["children"].remove(duplicate)
    assert policy([first, second]) is False


def test_distinct_asset_identity_is_not_inferred_from_names_ids_or_geometry():
    first = image("same-id", "asset://one")
    second = image("same-id", "asset://two", x=36)
    root = page(first, second)
    policy = build_dds_image_merge_policy(root)
    for node in (first, second):
        node["name"] = "renamed"
        node["id"] = node["layerId"] = "new-id"
        node["rowDims"]["left"] += 500
    assert policy([first, second]) is True


def test_non_image_url_references_do_not_count_as_rendered_resource_instances():
    first, second = image("a", "asset://a"), image("b", "asset://b", x=36)
    text = {"type": "lanhutext", "props": {"text": "asset://a", "src": "asset://a"}, "children": []}
    root = page(first, second, text)
    assert build_dds_image_merge_policy(root)([first, second]) is True


def test_unknown_sources_and_duplicate_proposal_members_are_not_eligible():
    first, second = image("a", "asset://a"), image("b", "asset://b", x=36)
    policy = build_dds_image_merge_policy(page(first, second))
    assert policy([first, image("unknown", "asset://unknown")]) is False
    assert policy([first, first]) is False
    assert policy([]) is False
    assert policy([first]) is False


def test_default_merge_behavior_is_unchanged_for_conservative_layout_callers():
    first = image("first", "asset://same")
    second = image("second", "asset://same", x=36)
    root = page(first, second)
    calls = []
    assert len(_merge_images([first, second], composite_spy(calls), root)) == 1
    assert len(calls) == 1


def block(identifier, x, y, width, height, *children, **style):
    dims = {"left": x, "top": y, "width": width, "height": height}
    return {"id": identifier, "layerId": identifier, "type": "lanhublock",
            "rowDims": dims, "props": {"style": {**dims, **style}}, "children": list(children)}


def ancestor_scope(*later, earlier=()):
    run = [image("a", "asset://a", x=100, y=100), image("b", "asset://b", x=136, y=100)]
    icons = block("icons", 100, 96, 80, 24, *run)
    header = block("header", 80, 80, 200, 60, icons)
    root = page(*earlier, header, *later)
    return root, run, icons


@pytest.mark.parametrize("style", [
    {"backgroundColor": "rgba(0,0,0,0.45)"},
    {"backgroundColor": "white"},
])
def test_later_ancestor_sibling_paint_blocks_local_merge(style):
    root, run, parent = ancestor_scope(block("overlay", 70, 70, 240, 120, **style))
    before, calls = deepcopy(root), []
    assert _merge_images(run, composite_spy(calls), parent,
                         accept_merge=build_dds_image_merge_policy(root)) == run
    assert calls == [] and root == before


@pytest.mark.parametrize("style", [{"filter": "blur(1px)"}, {"boxShadow": "var(--shadow)"}])
def test_unknown_later_ancestor_paint_is_not_assumed_disjoint(style):
    root, run, _ = ancestor_scope(block("unresolved", 900, 800, 20, 20, **style))
    before = deepcopy(root)
    assert build_dds_image_merge_policy(root)(run) is False
    assert root == before


def test_ancestor_sibling_shadow_can_reach_icons_outside_its_layout_rectangle():
    root, run, _ = ancestor_scope(block("shadow", 180, 100, 20, 20,
                                      boxShadow="-40px 0 0 0 black"))
    assert build_dds_image_merge_policy(root)(run) is False


@pytest.mark.parametrize("later", [
    block("distant-fill", 300, 100, 20, 20, backgroundColor="black"),
    block("distant-shadow", 300, 100, 20, 20, boxShadow="-30px 0 4px 0 black"),
    block("touching", 152, 100, 20, 20, backgroundColor="black"),
])
def test_known_disjoint_ancestor_paint_does_not_disable_composition(later):
    root, run, parent = ancestor_scope(later)
    before, calls = deepcopy(root), []
    assert len(_merge_images(run, composite_spy(calls), parent,
                             accept_merge=build_dds_image_merge_policy(root))) == 1
    assert len(calls) == 1 and root == before


def test_earlier_ancestor_background_is_not_a_later_occluder():
    background = block("background", 0, 0, 400, 300, backgroundColor="white")
    root, run, _ = ancestor_scope(earlier=(background,))
    assert build_dds_image_merge_policy(root)(run) is True


def test_ancestor_paint_snapshot_survives_layout_reparenting_and_style_mutation():
    overlay = block("overlay", 70, 70, 240, 120, backgroundColor="black")
    root, run, _ = ancestor_scope(overlay)
    policy = build_dds_image_merge_policy(root)
    root["children"].remove(overlay)
    overlay["rowDims"]["left"] = 900
    assert policy(run) is False


def test_ancestor_guard_uses_resource_paths_without_source_ids_or_names():
    root, run, _ = ancestor_scope(block("overlay", 70, 70, 240, 120, backgroundColor="black"))

    def change(node):
        node["id"] = node["layerId"] = node["name"] = "same-value"
        if "rowDims" in node:
            node["rowDims"]["left"] += 501
            node["rowDims"]["top"] -= 93
            node["props"]["style"]["left"] += 501
            node["props"]["style"]["top"] -= 93
        for child in node.get("children", []):
            change(child)

    change(root)
    assert build_dds_image_merge_policy(root)(deepcopy(run)) is False
