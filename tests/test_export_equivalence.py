"""Fail-closed, offline acceptance checks using independent tiny snapshots."""

import base64
from copy import deepcopy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import struct
import zlib

from PIL import Image
import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_export_equivalence.py"
SPEC = importlib.util.spec_from_file_location("check_export_equivalence", SCRIPT)
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


def png(color=(40, 80, 120, 255), *, compression=6):
    output = io.BytesIO()
    Image.new("RGBA", (2, 1), color).save(output, format="PNG", compress_level=compression)
    return output.getvalue()


def data_uri(data):
    return "data:image/png;base64," + base64.b64encode(data).decode("ascii")


def write_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def dds(identity, name, kind, frame, children=(), **props):
    return {"layerId": identity, "type": kind, "componentName": kind, "uiType": "",
            "rowDims": dict(zip(("left", "top", "width", "height"), frame)),
            "props": {"className": name, **props}, "children": list(children)}


def snapshot(tmp_path):
    directory = tmp_path / "snapshot"
    directory.mkdir()
    for side in ("actual", "reference"):
        (directory / side).mkdir()
    resource = tmp_path / "reference.png"
    resource.write_bytes(png(compression=0))
    url, actual_src = "https://example.test/reference.png", data_uri(png(compression=9))
    manifest = tmp_path / "assets.json"
    write_json(manifest, {"assets": {url: {"path": resource.name, "sha256": hashlib.sha256(resource.read_bytes()).hexdigest()}}})
    raw = {"artboard": {"id": "page", "layers": [{"id": "label"}, {"id": "image"}]}}
    write_json(directory / "raw.json", raw)
    schemas = {}
    for side, prefix, src in (("actual", "a", actual_src), ("reference", "r", url)):
        label = dds("label", prefix + "_label", "lanhutext", (0, 0, 30, 10), text="a_label")
        image = dds("image", prefix + "_image", "lanhuimage", (50, 0, 2, 1), src=src)
        row = dds("row_" + prefix, prefix + "_row", "lanhublock", (0, 0, 52, 10), [label, image])
        schemas[side] = dds("page", prefix + "_page", "lanhupage", (0, 0, 100, 80), [row])
        markup = (f'<div class="{prefix}_page flex-col">\n'
                  f'  <div class="{prefix}_row flex-row" data-note=\' class="a_label"\'>\n'
                  f'    <span class="{prefix}_label">a_label .a_label {{</span>\n'
                  f'    <img class="{prefix}_image" src="{src}" />\n'
                  '  </div>\n</div>\n'
                  '<!-- <div class="a_label">literal</div> -->\n'
                  '<script>const literal = \'class="a_label"\';</script>\n')
        (directory / side / "index.html").write_text(markup)
        css = ('/*\n.a_label {\n  literal: unchanged;\n}\n*/\n' +
               "".join(f'.{prefix}_{name} {{\n  width: 10px;\n}}\n' for name in ("page", "row", "label", "image")) +
               'body {\n  content: "a_label .a_label {";\n}\n')
        for name in checker.FILES[1:]:
            (directory / side / name).write_text(css if name != "common.css" else '.flex-row {\n  display: flex;\n}\n')
    write_json(directory / "actual-schema.json", schemas["actual"])
    write_json(directory / "official-schema.json", schemas["reference"])
    return directory, manifest


def update_schema(directory, transform, side="actual"):
    path = directory / ("actual-schema.json" if side == "actual" else "official-schema.json")
    value = json.loads(path.read_text())
    transform(value)
    write_json(path, value)


def set_actual_image(directory, content):
    value = json.loads((directory / "actual-schema.json").read_text())
    image = value["children"][0]["children"][1]
    old, image["props"]["src"] = image["props"]["src"], data_uri(content)
    write_json(directory / "actual-schema.json", value)
    path = directory / "actual/index.html"
    path.write_text(path.read_text().replace(old, image["props"]["src"]))


def test_aliases_and_different_png_encoding_pass_without_network_or_snapshot_writes(tmp_path, monkeypatch):
    directory, manifest = snapshot(tmp_path)
    before = {str(path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    import socket
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: pytest.fail("Network access is forbidden"))
    report = checker.check_export_equivalence(directory, manifest)
    assert report["passed"] and report["status"] == "passed"
    assert report["classes"]["count"] == 4
    assert report["normalization"]["html_class_attributes"] == 4
    assert report["normalization"]["html_img_src_attributes"] == 1
    evidence = report["images"]["images"][0]
    assert evidence["reference_png"]["sha256"] != evidence["actual_png"]["sha256"]
    assert evidence["reference_png"]["rgba_sha256"] == evidence["actual_png"]["rgba_sha256"]
    assert evidence["actual_png"]["dimensions"] == [2, 1]
    assert all(result["passed"] for result in report["files"].values())
    assert before == {str(path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}


@pytest.mark.parametrize("field", ["type", "componentName", "uiType", "frame", "original_id", "synthetic_kind", "order", "extra_group"])
def test_complete_tree_contract_rejects_every_structural_mutation(tmp_path, field):
    directory, manifest = snapshot(tmp_path)
    def mutate(root):
        row, label = root["children"][0], root["children"][0]["children"][0]
        if field in ("type", "componentName", "uiType"):
            label[field] = "changed"
        elif field == "frame":
            label["rowDims"]["left"] = 1
        elif field == "original_id":
            label["layerId"] = "unknown-original"
        elif field == "synthetic_kind":
            row["layerId"] = "col_invented"
        elif field == "order":
            row["children"].reverse()
        else:
            row["children"][0] = dds("row_extra", "extra", "lanhublock", (0, 0, 30, 10), [label])
    update_schema(directory, mutate)
    report = checker.check_export_equivalence(directory, manifest)
    assert not report["passed"] and not report["tree"]["passed"]
    assert "skipped" in report["normalization"]


def test_class_mapping_must_be_unique_in_both_schemas(tmp_path):
    directory, manifest = snapshot(tmp_path)
    update_schema(directory, lambda root: root["children"][0]["children"][0]["props"].update(className="a_image"))
    report = checker.check_export_equivalence(directory, manifest)
    assert report["tree"]["passed"] and not report["classes"]["passed"]
    assert report["classes"]["differences"][0]["code"] == "class_name_collision"


@pytest.mark.parametrize("kind", ["text", "attribute", "comment", "script", "css_string", "css_property", "css_order", "src_literal"])
def test_only_actual_class_and_img_src_attributes_and_simple_selectors_may_change(tmp_path, kind):
    directory, manifest = snapshot(tmp_path)
    if kind.startswith("css_"):
        path = directory / "reference/index.css"
        text = path.read_text()
        if kind == "css_string":
            text = text.replace('content: "a_label', 'content: "r_label')
        elif kind == "css_property":
            text = text.replace("width: 10px", "width: 11px", 1)
        else:
            text = text.replace("  width: 10px;", "  height: 10px;\n  width: 10px;", 1)
    else:
        path = directory / "reference/index.html"
        text = path.read_text()
        replacements = {
            "text": ('>a_label .a_label {</span>', '>r_label .a_label {</span>'),
            "attribute": ('data-note=\' class="a_label"\'', 'data-note=\' class="r_label"\''),
            "comment": ('<!-- <div class="a_label">', '<!-- <div class="r_label">'),
            "script": ('const literal = \'class="a_label"\'', 'const literal = \'class="r_label"\''),
        }
        if kind == "src_literal":
            text += '<code>https://example.test/reference.png</code>'
            actual = directory / "actual/index.html"
            src = json.loads((directory / "actual-schema.json").read_text())["children"][0]["children"][1]["props"]["src"]
            actual.write_text(actual.read_text() + '<code>' + src + '</code>')
        else:
            text = text.replace(*replacements[kind])
    path.write_text(text)
    report = checker.check_export_equivalence(directory, manifest)
    assert not report["passed"]
    assert not report["files"][path.name]["passed"]


@pytest.mark.parametrize("color", [(41, 80, 120, 255), (40, 80, 120, 0)])
def test_any_rgba_difference_rejects_resource_alias(tmp_path, color):
    directory, manifest = snapshot(tmp_path)
    set_actual_image(directory, png(color))
    report = checker.check_export_equivalence(directory, manifest)
    assert not report["passed"] and not report["images"]["passed"]
    assert report["normalization"]["html_img_src_attributes"] == 0
    assert "complete RGBA pixels differ" in report["images"]["differences"][0]["reason"]


def test_single_frame_apng_is_rejected_even_when_rgba_matches(tmp_path):
    directory, manifest = snapshot(tmp_path)
    def chunk(kind, payload):
        return len(payload).to_bytes(4, "big") + kind + payload + zlib.crc32(kind + payload).to_bytes(4, "big")
    original = png()
    apng = (original[:33] + chunk(b"acTL", struct.pack(">II", 1, 0))
            + chunk(b"fcTL", struct.pack(">IIIIIHHBB", 0, 2, 1, 0, 0, 1, 100, 0, 0)) + original[33:])
    set_actual_image(directory, apng)
    report = checker.check_export_equivalence(directory, manifest)
    assert not report["passed"]
    assert "APNG" in report["images"]["differences"][0]["reason"]


@pytest.mark.parametrize("mutation", ["missing", "hash", "html_source", "duplicate_src"])
def test_unverified_or_unbound_images_never_receive_aliases(tmp_path, mutation):
    directory, manifest = snapshot(tmp_path)
    if mutation == "missing":
        write_json(manifest, {"assets": {}})
    elif mutation == "hash":
        value = json.loads(manifest.read_text())
        value["assets"]["https://example.test/reference.png"]["sha256"] = "0" * 64
        write_json(manifest, value)
    else:
        path = directory / "actual/index.html"
        replacement = 'src="https://example.test/unverified.png" data-old=' if mutation == "html_source" else 'src="https://example.test/unverified.png" src='
        path.write_text(path.read_text().replace("src=", replacement, 1))
    report = checker.check_export_equivalence(directory, manifest)
    assert not report["passed"] and not report["images"]["passed"]
    assert report["normalization"]["html_img_src_attributes"] == 0


def test_renaming_cannot_merge_with_an_unmapped_css_class(tmp_path):
    directory, manifest = snapshot(tmp_path)
    for side in ("actual", "reference"):
        path = directory / side / "common.css"
        path.write_text(path.read_text() + '.r_label {\n  color: red;\n}\n')
    report = checker.check_export_equivalence(directory, manifest)
    assert not report["passed"]
    assert any(item["code"] == "class_collision_with_unmapped_token" for item in report["differences"])


def test_css_parser_handles_media_but_never_rewrites_literals_or_unsupported_selectors():
    css = '/* .a { } */\n@media (min-width: 1px) {\n.a {\n content: ".a {";\n}\n}\n'
    result, count, namespace = checker.normalize_css(css, {"a": "b"})
    assert result == css.replace("\n.a {", "\n.b {")
    assert count == 1 and namespace == {"a"}
    with pytest.raises(ValueError, match="non-simple"):
        checker.normalize_css('.a:hover { color: red; }', {"a": "b"})


def test_machine_cli_report_and_invalid_input_exit_codes(tmp_path, capsys):
    directory, manifest = snapshot(tmp_path)
    output = tmp_path / "report.json"
    assert checker.main([str(directory), "--asset-manifest", str(manifest), "--output", str(output)]) == 0
    assert json.loads(capsys.readouterr().out)["passed"] is True
    assert json.loads(output.read_text())["images"]["passed"]
    (directory / "raw.json").write_text('{"artboard": {}, "artboard": {}}')
    assert checker.main([str(directory), "--asset-manifest", str(manifest)]) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "failed" and report["input_errors"]
