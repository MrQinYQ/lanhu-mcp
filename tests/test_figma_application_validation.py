"""Fifth paired sample: preserve the failed first run and validate repairs."""
from collections import Counter
from copy import deepcopy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from lanhu_codegen import generate_design_files
from lanhu_codegen.figma_schema import figma_to_dds_schema


FIXTURE = Path(__file__).parent / "fixtures" / "figma_application"
SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_export_equivalence.py"
spec = importlib.util.spec_from_file_location("application_export_equivalence", SCRIPT)
equivalence = importlib.util.module_from_spec(spec)
spec.loader.exec_module(equivalence)


def walk(node, key="children"):
    yield node
    for child in node.get(key, []):
        yield from walk(child, key)


@pytest.fixture(scope="module")
def paired():
    raw = json.loads((FIXTURE / "raw.json").read_text())
    reference = json.loads((FIXTURE / "official-schema.json").read_text())
    manifest = json.loads((FIXTURE / "image-resources.json").read_text())
    resources = {url: (FIXTURE / entry["path"]).read_bytes() for url, entry in manifest["sources"].items()}
    input_urls = {n["ddsImage"]["imageUrl"] for n in walk(raw["artboard"], "layers")
                  if isinstance(n.get("ddsImage"), dict) and n["ddsImage"].get("imageUrl")}

    def loader(url):
        assert url in input_urls, "Only resources actually present in raw JSON may enter conversion"
        return resources[url]

    def guarded(original):
        def open_file(file, *args, **kwargs):
            if isinstance(file, (str, bytes, os.PathLike)):
                path = os.path.abspath(os.fsdecode(file))
                assert not path.startswith(str(FIXTURE.parent.resolve()) + os.sep), "Converter read a fixture oracle"
            return original(file, *args, **kwargs)
        return open_file

    import builtins
    before = deepcopy(raw)
    with patch("builtins.open", guarded(builtins.open)), patch("io.open", guarded(io.open)):
        actual = figma_to_dds_schema(raw, asset_loader=loader)
    assert raw == before
    return {"raw": raw, "reference": reference, "actual": actual,
            "actual_files": generate_design_files(actual), "reference_files": generate_design_files(reference)}


def test_fifth_version_and_first_run_failure_are_preserved():
    metadata = json.loads((FIXTURE / "metadata.json").read_text())
    assert metadata["version"]["id"] == "6244237b-28b5-4421-9788-7a0b77cb9b4f"
    assert metadata["initial_run"]["passed"] is False
    assert metadata["initial_run"]["actual_schema_generated"] is False
    for name, expected in metadata["sha256"].items():
        assert hashlib.sha256((FIXTURE / name).read_bytes()).hexdigest() == expected, name


def test_all_original_layers_text_and_image_sources_are_preserved(paired):
    source_ids = {n["id"] for n in walk(paired["raw"]["artboard"], "layers")}
    refs = {n["layerId"]: n for n in walk(paired["reference"]) if n["layerId"] in source_ids}
    nodes = [n for n in walk(paired["actual"]) if n["layerId"] in source_ids]
    actual = {n["layerId"]: n for n in nodes}
    assert len(refs) == len(nodes) == len(actual) == 323
    assert actual.keys() == refs.keys()
    kinds = Counter(n["type"] for n in walk(paired["actual"]))
    assert kinds["lanhutext"] == 151 and kinds["lanhuimage"] == 59
    for layer_id, reference in refs.items():
        node = actual[layer_id]
        assert (node["type"], node["rowDims"]) == (reference["type"], reference["rowDims"]), layer_id
        if reference["type"] == "lanhutext":
            assert node["props"]["text"] == reference["props"]["text"], layer_id
            assert node["props"]["lines"] == reference["props"]["lines"], layer_id
        if reference["type"] == "lanhuimage":
            assert node["props"]["src"] == reference["props"]["src"], layer_id


@pytest.mark.parametrize("name", equivalence.FILES)
def test_official_schema_matches_independently_captured_editor_files(paired, name):
    assert paired["reference_files"][name].encode() == (FIXTURE / "official-ui" / name).read_bytes()


def test_fifth_design_passes_export_equivalence_v2(paired, tmp_path):
    for name, value in (("raw.json", paired["raw"]), ("actual-schema.json", paired["actual"]),
                        ("official-schema.json", paired["reference"])):
        (tmp_path / name).write_text(json.dumps(value, ensure_ascii=False))
    for kind in ("actual", "reference"):
        (tmp_path / kind).mkdir()
        for name, content in paired[kind + "_files"].items():
            (tmp_path / kind / name).write_text(content)
    report = equivalence.check_export_equivalence(tmp_path, FIXTURE / "image-resources.json")
    (tmp_path / "equivalence.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    assert report["passed"], f"Fifth design differs; report: {tmp_path / 'equivalence.json'}"
    assert report["tree"]["actual_nodes"] == report["tree"]["reference_nodes"] == 400
