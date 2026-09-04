"""Scrim pairing boundaries inferred from independent component evidence.

The source-role rules only remove a contextual veto. Geometry, paint order,
checkboxes and repeated-view scopes retain their independent vetoes.
"""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from lanhu_codegen.figma_dds_pairing import (
    checkbox_layer_ids, contextual_pairing_exclusions, pair_dds_image_text,
    repeated_view_layer_ids,
)
from tests.test_figma_dds_pairing import node, pairs, scrim_view, source_index, source_node


def boundary_source(*, size=19, exported=True, group=None):
    view = scrim_view()
    icon = source_node("independent-pixels", (112, 120, size, size), paint=True, raster=exported)
    icon["style"]["borders"] = [{
        "isEnabled": True, "opacity": 1, "lineAlignment": "inside", "style": "solid",
        "widths": dict.fromkeys(("top", "right", "bottom", "left"), 1), "color": {"a": 1},
    }]
    parent = source_node("independent-source-wrapper", (108, 116, size + 8, size + 8), children=[icon])
    if group is not None:
        parent["componentGroup"] = group
        icon["style"] = {"isEnabled": True, "fills": []}
    view["layers"][2]["layers"].append(parent)
    return source_index(view)


@pytest.mark.parametrize("size", [11, 19, 27])
@pytest.mark.parametrize("export_kind", ["dds", "ordinary"])
def test_opaque_fully_bordered_export_is_an_independent_boundary_without_multiline_children(size, export_kind):
    source = boundary_source(size=size)
    if export_kind == "ordinary":
        source["independent-pixels"].update(hasExportDDSImage=False, hasExportImage=True)
    before = deepcopy(source)
    excluded = contextual_pairing_exclusions(source)
    assert "independent-pixels" not in excluded
    assert "view-body-a-icon" in excluded
    assert source == before


@pytest.mark.parametrize("mutation", [
    "missing-fill", "translucent-fill", "partial-border", "outside-border", "disabled-border",
    "translucent-border", "dashed-border", "no-export", "clip", "opacity", "rotation", "effect",
])
def test_border_exception_requires_a_complete_opaque_exported_boundary(mutation):
    source = boundary_source()
    icon = source["independent-pixels"]
    style, border = icon["style"], icon["style"]["borders"][0]
    if mutation == "missing-fill":
        style["fills"] = []
    elif mutation == "translucent-fill":
        style["fills"][0]["color"]["a"] = 0.6
    elif mutation == "partial-border":
        border["widths"]["right"] = 0
    elif mutation == "outside-border":
        border["lineAlignment"] = "outside"
    elif mutation == "disabled-border":
        border["isEnabled"] = False
    elif mutation == "translucent-border":
        border["color"]["a"] = 0.6
    elif mutation == "dashed-border":
        border["style"] = "dashed"
    elif mutation == "no-export":
        icon["hasExportDDSImage"] = False
        icon["layers"] = [source_node("nested-pixels", (114, 122, 12, 12), raster=True)]
    elif mutation == "clip":
        icon["clipped"] = True
    elif mutation == "opacity":
        icon["opacity"] = 0.6
    elif mutation == "rotation":
        icon["transform"] = [[0, -1, 0], [1, 0, 0]]
    else:
        style["shadows"] = [{"isEnabled": True}]
    target = "nested-pixels" if mutation == "no-export" else "independent-pixels"
    assert target in contextual_pairing_exclusions(source)


def test_explicit_link_role_preserves_nested_export_under_scrim():
    source = boundary_source(group="Link")
    before = deepcopy(source)
    assert "independent-pixels" not in contextual_pairing_exclusions(source)
    assert source == before


def covered_button_source():
    source = boundary_source(group="Button")
    foreground = source["foreground"]
    foreground["frame"] = {"left": 100, "top": 100, "width": 70, "height": 70}
    foreground["layers"] = []
    return source


def test_button_exception_requires_the_later_opaque_foreground_to_cover_the_complete_control():
    source = covered_button_source()
    before = deepcopy(source)
    assert "independent-pixels" not in contextual_pairing_exclusions(source)
    assert source == before


@pytest.mark.parametrize("mutation", ["outside", "partial", "translucent", "rounded-corner", "escaping-child", "shadow"])
def test_button_coverage_does_not_mean_any_scrim_or_intersection_is_enough(mutation):
    source = covered_button_source()
    cover = source["foreground"]
    if mutation == "outside":
        cover["frame"]["left"] = 180
    elif mutation == "partial":
        cover["frame"]["left"] = 120
    elif mutation == "translucent":
        # Retain another opaque foreground so a genuine scrim context remains.
        other = source_node("other-foreground", (200, 100, 60, 60), paint=True)
        source["view"]["layers"].append(other)
        cover["style"]["fills"][0].update(opacity=0.7, color={"a": 0.7})
    elif mutation == "rounded-corner":
        cover["radius"] = dict.fromkeys(("topLeft", "topRight", "bottomLeft", "bottomRight"), 20)
    elif mutation == "escaping-child":
        source["independent-source-wrapper"]["layers"].append(
            source_node("escaped", (175, 120, 8, 8), kind="textLayer"))
    else:
        source["independent-source-wrapper"]["style"]["shadows"] = [{"isEnabled": True}]
    assert "independent-pixels" in contextual_pairing_exclusions(source)


@pytest.mark.parametrize("group", [None, "select", "search-box"])
def test_display_names_and_unrelated_component_roles_do_not_establish_a_link(group):
    source = boundary_source(group="Link")
    parent = source["independent-source-wrapper"]
    parent.pop("componentGroup")
    if group is not None:
        parent["componentGroup"] = group
    parent.update(name="Link", componentName="Link", componentProperties={"label": {"value": "Link"}})
    assert "independent-pixels" in contextual_pairing_exclusions(source)


@pytest.mark.parametrize("scale", [0.5, 2])
def test_boundary_classification_survives_renaming_translation_scaling_and_mapping_order(scale):
    source = boundary_source(group="Link")
    for index, item in enumerate(source.values()):
        item.update(id=f"renamed-{index}", name=f"unrelated-{index}")
        item["frame"] = {key: value * scale + (700 if key == "left" else -90 if key == "top" else 0)
                         for key, value in item["frame"].items()}
        for path in item.get("paths", []):
            path["frame"] = deepcopy(item["frame"])
    image_id = source["independent-pixels"]["id"]
    ordinary_id = source["view-body-a-icon"]["id"]
    source = {item["id"]: item for item in reversed(list(source.values()))}
    before = deepcopy(source)
    excluded = contextual_pairing_exclusions(source)
    assert image_id not in excluded
    assert ordinary_id in excluded
    assert source == before


def test_context_exception_still_obeys_geometry_and_paint_obstacles():
    excluded = contextual_pairing_exclusions(boundary_source())
    items = [node("independent-pixels", (0, 0, 24, 24), "lanhuimage"),
             node("caption", (32, 1, 56, 22), "lanhutext")]
    assert pairs(pair_dds_image_text(items, excluded_image_ids=excluded))
    obstacle = node("intervening-paint", (26, 8, 4, 4))
    assert not pairs(pair_dds_image_text([items[0], obstacle, items[1]], excluded_image_ids=excluded))
    items[0]["rowDims"]["height"] = 26
    items[0]["props"]["style"]["height"] = 26
    assert not pairs(pair_dds_image_text(items, excluded_image_ids=excluded))


def wrapped_button_source():
    control = source_node("control", (20, 30, 100, 32), paint=True, children=[
        source_node("glyph", (36, 39, 14, 14), raster=True),
        source_node("label", (58, 35, 46, 22), kind="textLayer"),
    ])
    control["componentGroup"] = "Button"
    parent = source_node("single-wrapper", (20, 30, 100, 32), children=[control])
    return source_index(parent)


def test_explicit_opaque_button_filling_its_single_transparent_wrapper_keeps_one_semantic_boundary():
    source = wrapped_button_source()
    before = deepcopy(source)
    assert contextual_pairing_exclusions(source) == {"glyph"}
    assert source == before
    items = [node("glyph", (36, 39, 14, 14), "lanhuimage"),
             node("label", (58, 35, 46, 22), "lanhutext")]
    assert not pairs(pair_dds_image_text(items, excluded_image_ids=contextual_pairing_exclusions(source)))
    assert pairs(pair_dds_image_text(items))


@pytest.mark.parametrize("mutation", [
    "larger-wrapper", "shifted-wrapper", "second-child", "painted-wrapper", "clipped-wrapper",
    "opacity-wrapper", "unknown-effect", "transformed-wrapper", "raster-wrapper", "link", "display-name",
    "unpainted-control", "translucent-control", "shadow-control", "third-control-leaf", "painted-nested-leaf",
])
def test_single_wrapper_rule_requires_the_explicit_tight_safe_button_context(mutation):
    source = wrapped_button_source()
    parent, control = source["single-wrapper"], source["control"]
    if mutation == "larger-wrapper":
        parent["frame"]["width"] += 1
    elif mutation == "shifted-wrapper":
        parent["frame"]["left"] += 1
    elif mutation == "second-child":
        parent["layers"].append(source_node("other", (150, 30, 10, 10), kind="textLayer"))
    elif mutation == "painted-wrapper":
        parent["style"]["fills"] = deepcopy(control["style"]["fills"])
    elif mutation == "clipped-wrapper":
        parent["clipped"] = True
    elif mutation == "opacity-wrapper":
        parent["opacity"] = 0.5
    elif mutation == "unknown-effect":
        parent["style"]["filter"] = "blur(var(--unknown))"
    elif mutation == "transformed-wrapper":
        parent["transform"] = [[1, 0.1, 0], [0, 1, 0]]
    elif mutation == "raster-wrapper":
        parent["hasExportImage"] = True
    elif mutation == "link":
        control["componentGroup"] = "Link"
    elif mutation == "display-name":
        control.pop("componentGroup")
        control["name"] = "Button"
    elif mutation == "unpainted-control":
        control["style"]["fills"] = []
    elif mutation == "translucent-control":
        control["style"]["fills"][0]["color"]["a"] = 0.5
    elif mutation == "shadow-control":
        control["style"]["shadows"] = [{"isEnabled": True}]
    elif mutation == "third-control-leaf":
        control["layers"].append(source_node("suffix", (108, 40, 8, 8), raster=True))
    else:
        control["layers"][0] = source_node("nested", (36, 39, 14, 14), paint=True, children=[control["layers"][0]])
    assert contextual_pairing_exclusions(source) == set()


def source_table_column(*, image_size=20, row_height=56):
    def border():
        return [{"isEnabled": True, "opacity": 1, "lineAlignment": "inside", "style": "solid",
                 "widths": {"top": 0, "right": 0, "bottom": 1, "left": 0}, "color": {"a": 1}}]

    header = source_node("table-header", (10, 20, 150, 30), paint=True, children=[
        source_node("table-heading", (18, 24, 110, 22), kind="textLayer")])
    header["style"]["borders"] = border()
    rows = [header]
    for index in range(2):
        top = 50 + index * row_height
        center = top + row_height / 2 - 0.5
        row = source_node(f"cell-{index}", (10, top, 150, row_height), children=[
            source_node(f"table-image-{index}", (18, center - image_size / 2, image_size, image_size), raster=True),
            source_node(f"table-text-{index}", (26 + image_size, center - (image_size - 2) / 2, 70, image_size - 2), kind="textLayer"),
        ])
        row["style"]["borders"] = border()
        rows.append(row)
    column = source_node("column", (10, 20, 150, 30 + 2 * row_height), children=rows)
    return source_index(column)


@pytest.mark.parametrize("image_size,row_height", [(14, 40), (20, 56), (24, 64), (30, 78)])
def test_table_leading_icon_extension_requires_centered_dds_outer_frame(image_size, row_height):
    # Native content is half a pixel above the raw center in both cases. Ceil
    # normalization centers the even-height DDS cell but not the odd-height one.
    centered = source_table_column(image_size=image_size, row_height=row_height)
    offset = source_table_column(image_size=image_size, row_height=row_height + 1)
    before = deepcopy(offset)
    assert contextual_pairing_exclusions(centered) == set()
    assert contextual_pairing_exclusions(offset) == {"table-image-0", "table-image-1"}
    assert offset == before


def test_half_pixel_leaf_shift_changes_the_normalized_table_center_without_changing_pair_spacing():
    source = source_table_column()
    assert contextual_pairing_exclusions(source) == set()
    for key in ("table-image-0", "table-text-0"):
        source[key]["frame"]["top"] -= 0.5
    assert contextual_pairing_exclusions(source) == {"table-image-0"}


@pytest.mark.parametrize("mutation", [
    "no-header-fill", "image-header", "only-two-rows", "gap", "different-width", "full-border",
    "outside-border", "transparent-border", "painted-column", "clipped-column", "unknown-row-effect",
    "extra-leaf", "same-height-caption", "trailing-image",
])
def test_table_alignment_rule_needs_a_complete_source_column_and_the_taller_leading_icon_case(mutation):
    source = source_table_column(row_height=57)
    parent, header, cell = source["column"], source["table-header"], source["cell-0"]
    if mutation == "no-header-fill":
        header["style"]["fills"] = []
    elif mutation == "image-header":
        source["table-heading"].update(type="artboard", hasExportDDSImage=True)
    elif mutation == "only-two-rows":
        parent["layers"].pop()
    elif mutation == "gap":
        cell["frame"]["top"] += 1
    elif mutation == "different-width":
        cell["frame"]["width"] += 1
    elif mutation == "full-border":
        cell["style"]["borders"][0]["widths"] = dict.fromkeys(("top", "right", "bottom", "left"), 1)
    elif mutation == "outside-border":
        cell["style"]["borders"][0]["lineAlignment"] = "outside"
    elif mutation == "transparent-border":
        cell["style"]["borders"][0]["opacity"] = 0.5
    elif mutation == "painted-column":
        parent["style"]["fills"] = deepcopy(header["style"]["fills"])
    elif mutation == "clipped-column":
        parent["clipped"] = True
    elif mutation == "unknown-row-effect":
        cell["style"]["filter"] = "blur(var(--unknown))"
    elif mutation == "extra-leaf":
        cell["layers"].append(source_node("extra-text", (130, 52, 10, 10), kind="textLayer"))
    elif mutation == "same-height-caption":
        source["table-text-0"]["frame"].update(top=source["table-image-0"]["frame"]["top"], height=20)
    else:
        cell["layers"].reverse()
    excluded = contextual_pairing_exclusions(source)
    assert "table-image-0" not in excluded
    if mutation in {"extra-leaf", "same-height-caption", "trailing-image"}:
        assert excluded == {"table-image-1"}
    else:
        assert excluded == set()


def test_table_alignment_inference_ignores_names_text_values_and_identifier_spelling():
    source = source_table_column(row_height=57)
    expected = set()
    for index, item in enumerate(source.values()):
        old_id = item["id"]
        item.update(id=f"renamed-{index}", name="unrelated", text={"value": "any caption"})
        item["frame"]["left"] += 310
        item["frame"]["top"] -= 200
        if old_id in {"table-image-0", "table-image-1"}:
            expected.add(item["id"])
    source = {item["id"]: item for item in reversed(list(source.values()))}
    assert contextual_pairing_exclusions(source) == expected


def source_borderless_field(*, image_size=24, suffix=True):
    height = image_size + 8
    center = 30 + height / 2
    body = source_node("field-body", (22, 33, 280, image_size + 2), children=[
        source_node("field-image", (22, center - image_size / 2, image_size, image_size), raster=True),
        source_node("field-text", (30 + image_size, center - (image_size - 2) / 2, 44, image_size - 2), kind="textLayer"),
    ])
    field = source_node("field", (10, 30, 320, height), paint=True, children=[body])
    if suffix:
        field["layers"].append(source_node("field-suffix", (310, center - 6, 12, 12), raster=True))
    return source_index(field)


@pytest.mark.parametrize("size", [18, 24, 30])
@pytest.mark.parametrize("suffix", [False, True])
@pytest.mark.parametrize("color", [(1, 1, 1), (0.8, 0.1, 0.4)])
def test_borderless_padded_wide_field_preserves_its_original_leaf_row_without_using_gray_color(size, suffix, color):
    source = source_borderless_field(image_size=size, suffix=suffix)
    source["field"]["style"]["fills"][0]["color"].update(zip(("r", "g", "b"), color))
    before = deepcopy(source)
    assert contextual_pairing_exclusions(source) == {"field-image"}
    assert source == before


@pytest.mark.parametrize("mutation", [
    "border", "no-fill", "translucent", "tight-body", "no-vertical-body-padding", "un-padded-field",
    "extra-field-child", "text-suffix", "overlapping-suffix", "body-shadow", "parent-clip",
    "unknown-parent-effect", "same-height-caption", "multiline-caption", "shifted-content",
])
def test_field_boundary_rule_does_not_replace_bordered_select_or_tight_icon_text_units(mutation):
    source = source_borderless_field()
    field, body = source["field"], source["field-body"]
    if mutation == "border":
        field["style"]["borders"] = [{"isEnabled": True, "width": 1}]
    elif mutation == "no-fill":
        field["style"]["fills"] = []
    elif mutation == "translucent":
        field["style"]["fills"][0]["color"]["a"] = 0.5
    elif mutation == "tight-body":
        body["frame"]["width"] = 76
    elif mutation == "no-vertical-body-padding":
        body["frame"].update(top=34, height=24)
    elif mutation == "un-padded-field":
        field["frame"] = deepcopy(body["frame"])
    elif mutation == "extra-field-child":
        field["layers"].append(source_node("third", (326, 40, 3, 3), raster=True))
    elif mutation == "text-suffix":
        source["field-suffix"].update(type="textLayer", hasExportDDSImage=False)
    elif mutation == "overlapping-suffix":
        source["field-suffix"]["frame"]["left"] = 290
    elif mutation == "body-shadow":
        body["style"]["shadows"] = [{"isEnabled": True}]
    elif mutation == "parent-clip":
        field["clipped"] = True
    elif mutation == "unknown-parent-effect":
        field["style"]["filter"] = "blur(var(--unknown))"
    elif mutation == "same-height-caption":
        source["field-text"]["frame"].update(top=34, height=24)
    elif mutation == "multiline-caption":
        source["field-text"]["frame"].update(top=32, height=28)
    else:
        source["field-image"]["frame"]["top"] += 0.5
        source["field-text"]["frame"]["top"] += 0.5
    assert contextual_pairing_exclusions(source) == set()


def source_menu_footer():
    option = source_node("option", (10, 10, 200, 32), paint=True, children=[
        source_node("option-text", (22, 15, 80, 22), kind="textLayer")])
    option["componentGroup"] = "components/dropdown/menu-item"
    body = source_node("footer-body", (22, 47, 176, 22), children=[
        source_node("footer-image", (22, 50, 16, 16), raster=True),
        source_node("footer-text", (46, 47, 100, 22), kind="textLayer"),
    ])
    footer = source_node("footer", (10, 42, 200, 36), paint=True, children=[body])
    footer["componentGroup"] = "components/dropdown/menu-item"
    footer["style"]["borders"] = [{"isEnabled": True, "opacity": 1, "lineAlignment": "inside", "style": "solid",
                                    "widths": {"top": 1, "right": 0, "bottom": 0, "left": 0}, "color": {"a": 1}}]
    menu = source_node("menu", (10, 10, 200, 72), paint=True, children=[option, footer])
    menu["componentGroup"] = "dropdown-menu"
    menu["style"]["shadows"] = [{"isEnabled": True, "x": 0, "y": 4, "blur": 10, "spread": 0, "color": {"a": 0.1}}]
    return source_index(menu)


def test_explicit_terminal_menu_item_with_top_separator_retains_its_existing_content_boundary():
    source = source_menu_footer()
    before = deepcopy(source)
    assert contextual_pairing_exclusions(source) == {"footer-image"}
    assert source == before


@pytest.mark.parametrize("mutation", [
    "detached-artboard", "display-name", "not-menu", "not-last", "no-top-border", "full-border",
    "transparent-border", "outside-border", "translucent-footer", "clip", "unknown-effect", "malformed-style",
    "escaping-leaf", "third-leaf", "different-width",
])
def test_menu_footer_exception_needs_the_explicit_terminal_component_and_separator(mutation):
    source = source_menu_footer()
    menu, footer = source["menu"], source["footer"]
    if mutation in {"detached-artboard", "display-name"}:
        footer.pop("componentGroup")
        footer.update(type="artboard", name="components/dropdown/menu-item")
    elif mutation == "not-menu":
        menu.pop("componentGroup")
    elif mutation == "not-last":
        menu["layers"].reverse()
    elif mutation == "no-top-border":
        footer["style"]["borders"] = []
    elif mutation == "full-border":
        footer["style"]["borders"][0]["widths"] = dict.fromkeys(("top", "right", "bottom", "left"), 1)
    elif mutation == "transparent-border":
        footer["style"]["borders"][0]["color"]["a"] = 0.5
    elif mutation == "outside-border":
        footer["style"]["borders"][0]["lineAlignment"] = "outside"
    elif mutation == "translucent-footer":
        footer["style"]["fills"][0]["color"]["a"] = 0.5
    elif mutation == "clip":
        menu["clipped"] = True
    elif mutation == "unknown-effect":
        menu["style"]["filter"] = "blur(var(--unknown))"
    elif mutation == "malformed-style":
        menu["style"] = ["unknown"]
    elif mutation == "escaping-leaf":
        source["footer-text"]["frame"]["left"] = 150
    elif mutation == "third-leaf":
        source["footer-body"]["layers"].append(source_node("extra", (170, 52, 8, 8), raster=True))
    else:
        footer["frame"]["width"] -= 1
    assert contextual_pairing_exclusions(source) == set()


def walk(node, child_key):
    yield node
    for child in node.get(child_key, []):
        yield from walk(child, child_key)


@pytest.mark.parametrize("folder", ["figma_application", "figma_aggregation"])
def test_paired_sample_image_roles_are_not_vetoed_by_source_context(folder):
    fixture = Path(__file__).parent / "fixtures" / folder
    raw = json.loads((fixture / "raw.json").read_text())
    official = json.loads((fixture / "official-schema.json").read_text())
    source = {n["id"]: n for n in walk(raw["artboard"], "layers")}
    before = deepcopy(raw)
    excluded = (checkbox_layer_ids(source) | repeated_view_layer_ids(source)
                | contextual_pairing_exclusions(source))
    expected = {n["layerId"] for group in walk(official, "children") if group.get("uiType") == "ImageText"
                for n in walk(group, "children") if n.get("type") == "lanhuimage"}
    assert expected
    assert not expected & excluded
    assert raw == before
    if folder == "figma_application":
        # Existing plain AD-copy and iOS-detail controls carry no Link role or
        # independent full border, even though their icon geometry is similar.
        assert {"248:28321", "248:28334"} <= contextual_pairing_exclusions(source)
