"""DDS comparison reports identity ambiguity and structural/visual differences."""

from copy import deepcopy
import json

import pytest

from lanhu_codegen.schema_compare import compare_schemas, main


def node(layer_id, *, node_id=None, kind="lanhublock", children=None, text=None):
    result = {"id": node_id if node_id is not None else layer_id, "layerId": layer_id,
              "type": kind, "componentName": kind, "children": children or [],
              "rowDims": {"left": 0, "top": 0, "width": 100, "height": 20},
              "props": {"style": {"color": "#000", "width": 100}}}
    if text is not None:
        result["props"]["text"] = text
        result["data"] = {"value": text}
    return result


def page(*children):
    return node("page-source", node_id="page", kind="lanhupage", children=list(children))


def test_equal_schema_and_report_do_not_mutate_inputs():
    reference = page(node("1:1", text="Hello", kind="lanhutext"))
    actual = deepcopy(reference)
    before = deepcopy((reference, actual))
    report = compare_schemas(reference, actual)
    assert (reference, actual) == before
    assert report["summary"]["structural_equal"]
    assert report["summary"]["leaf_content_equal"]
    assert report["summary"]["leaf_geometry_equal"]
    assert report["summary"]["all_compared_fields_equal"]
    assert not report["differences"]
    report["matches"][0]["reference"]["id"] = "changed report"
    assert (reference, actual) == before


def test_unique_layer_ids_win_over_reused_dds_ids():
    reference = page(node("1:1", node_id="a"), node("1:2", node_id="b"))
    actual = page(node("1:2", node_id="a"), node("1:1", node_id="b"))
    report = compare_schemas(reference, actual)
    first = next(match for match in report["matches"] if match["reference"]["layerId"] == "1:1")
    assert first["actual"]["layerId"] == "1:1"
    assert first["actual"]["path"] == "/children/1"
    assert first["matched_by"] == "layerId"
    assert report["summary"]["differences_by_category"]["order"] == 2
    assert not report["summary"]["structural_equal"]


def test_same_dds_id_does_not_override_conflicting_source_identity():
    report = compare_schemas(page(node("1:1", node_id="same")), page(node("9:9", node_id="same")))
    assert report["summary"]["matched_nodes"] == 1
    assert report["summary"]["identity_conflicts"] == 1
    assert report["missing_nodes"][0]["layerId"] == "1:1"
    assert report["added_nodes"][0]["layerId"] == "9:9"
    assert not report["summary"]["leaf_content_equal"]


def test_duplicate_layer_ids_can_only_match_using_unique_dds_ids():
    reference = page(node("duplicate", node_id="a"), node("duplicate", node_id="b"))
    actual = page(node("duplicate", node_id="b"), node("duplicate", node_id="a"))
    report = compare_schemas(reference, actual)
    assert report["summary"]["matched_by"] == {"layerId": 1, "id": 2}
    assert report["summary"]["duplicate_identifier_groups"] == 1
    assert all(match["reference"]["id"] == match["actual"]["id"] for match in report["matches"])
    assert not report["summary"]["structural_equal"]


def test_duplicate_source_and_dds_ids_remain_ambiguous_even_with_same_geometry():
    reference = page(node("duplicate", node_id="same"), node("duplicate", node_id="same"))
    actual = deepcopy(reference)
    report = compare_schemas(reference, actual)
    assert report["summary"]["matched_nodes"] == 1
    assert report["summary"]["missing_nodes"] == report["summary"]["added_nodes"] == 2
    assert report["summary"]["duplicate_identifier_groups"] == 2
    assert not report["summary"]["structural_equal"]
    assert not report["summary"]["leaf_geometry_equal"]


@pytest.mark.parametrize("layer_id", ["", None, "  ", "row_10_20_30_40_123", "col_10_20_30_40_456", "rect_1_2_3_4_5"])
def test_empty_and_synthetic_layer_ids_do_not_match_unrelated_nodes(layer_id):
    reference = page(node(layer_id, node_id="ref-group"))
    actual = page(node(layer_id, node_id="actual-group"))
    report = compare_schemas(reference, actual)
    assert report["summary"]["matched_nodes"] == 1
    assert report["summary"]["missing_nodes"] == report["summary"]["added_nodes"] == 1
    assert len(report["matching_diagnostics"]["ignored_layer_ids"]) == 2


def test_synthetic_layer_can_still_match_by_unique_dds_id():
    report = compare_schemas(page(node("row_1_2_3_4_5", node_id="group")),
                             page(node("row_9_8_7_6_5", node_id="group")))
    assert report["summary"]["matched_by"] == {"layerId": 1, "id": 1}
    assert report["summary"]["structural_equal"]
    assert not report["summary"]["all_compared_fields_equal"]


def test_regrouped_identical_leaves_have_equal_content_and_geometry_but_different_structure():
    reference = page(node("row_0_0_100_20_1", node_id="group", children=[node("1:1", kind="lanhutext", text="Hi")]))
    actual = page(node("1:1", kind="lanhutext", text="Hi"))
    report = compare_schemas(reference, actual)
    summary = report["summary"]
    assert summary["actual_nodes"] < summary["reference_nodes"]
    assert summary["leaf_content_equal"] and summary["leaf_geometry_equal"]
    assert not summary["structural_equal"]
    assert summary["missing_nodes"] == 1
    assert summary["differences_by_category"]["parent"] == 1


def test_fewer_nodes_does_not_hide_lost_content():
    reference = page(node("1:1", kind="lanhutext", text="Hi"), node("1:2", kind="lanhutext", text="Lost"))
    actual = page(node("1:1", kind="lanhutext", text="Hi"))
    report = compare_schemas(reference, actual)
    assert not report["summary"]["leaf_matching_complete"]
    assert not report["summary"]["leaf_content_equal"]
    assert not report["summary"]["leaf_geometry_equal"]


def test_reports_type_geometry_visual_layout_resource_text_and_metadata_differences():
    reference = page(node("1:1", kind="lanhutext", text="Before"))
    actual = deepcopy(reference)
    changed = actual["children"][0]
    changed["type"] = "lanhuimage"
    changed["componentName"] = "lanhuimage"
    changed["rowDims"]["width"] = 101
    changed["props"]["style"].update(color="#fff", width=101, backgroundImage="url('https://example.com/image.png')")
    changed["props"].update(text="After", src="https://example.com/image.png", custom=None)
    changed["data"]["value"] = "https://example.com/image.png"
    before = deepcopy((reference, actual))
    report = compare_schemas(reference, actual)
    assert (reference, actual) == before
    counts = report["summary"]["differences_by_category"]
    for category in ("type", "rowDims", "visual_style", "layout_style", "resources", "text", "metadata"):
        assert counts[category] > 0
    null_field = next(item for item in report["differences"] if item["field"] == "/props/custom")
    assert not null_field["reference_present"] and null_field["actual_present"]
    assert not report["summary"]["leaf_content_equal"]
    assert not report["summary"]["leaf_geometry_equal"]
    assert not report["summary"]["leaf_visual_style_equal"]


def test_styles_do_not_change_structure_and_global_geometry_flags():
    reference = page(node("1:1"))
    actual = deepcopy(reference)
    actual["children"][0]["props"]["style"].update(position="absolute", left=40, opacity=0.5)
    report = compare_schemas(reference, actual)
    assert report["summary"]["structural_equal"]
    assert report["summary"]["leaf_geometry_equal"]
    assert not report["summary"]["leaf_visual_style_equal"]
    assert not report["summary"]["all_compared_fields_equal"]


def test_removing_entire_props_object_still_reports_lost_rendered_text():
    reference = page(node("1:1", kind="lanhutext", text="Still present in data.value"))
    actual = deepcopy(reference)
    del actual["children"][0]["props"]
    report = compare_schemas(reference, actual)
    assert report["summary"]["structural_equal"]
    assert not report["summary"]["leaf_content_equal"]
    assert not report["summary"]["leaf_visual_style_equal"]
    assert any(item["category"] == "text" and item["field"] == "/props/text" for item in report["differences"])


def test_cli_outputs_machine_readable_json_to_stdout_and_file(tmp_path, capsys):
    reference = tmp_path / "reference.json"
    actual = tmp_path / "actual.json"
    reference.write_text(json.dumps(page(node("1:1"))))
    actual.write_text(json.dumps(page(node("1:2"))))
    assert main([str(reference), str(actual)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["summary"]["missing_nodes"] == 1
    output = tmp_path / "diff.json"
    assert main([str(reference), str(actual), "--output", str(output)]) == 0
    assert json.loads(output.read_text()) == report


def test_cli_rejects_invalid_tree_without_a_success_report(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text('{"children": {}}')
    assert main([str(bad), str(bad)]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "must be an array" in json.loads(captured.err)["error"]
