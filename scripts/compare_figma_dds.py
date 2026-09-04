#!/usr/bin/env python3
"""Freeze and compare a new Figma/DDS pair without using an oracle in conversion.

Usage:
  python compare.py --raw raw.json --official official-schema.json \
      --assets asset-manifest.json --out baseline --repo /path/to/mcp/lanhu

The cache manifest is either {URL: "path"} or {"assets": {URL: {"path":
"path", "sha256": "optional expected digest"}}}. Relative paths are resolved
against the manifest directory. An assets directory must contain manifest.json.
No downloads occur. Only resource URLs already present in raw.json are allowed.

Output directories are immutable by convention: an existing --out is refused.
Exit 0 means comparison completed, not parity; exit 2 means a conversion/render
stage failed; exit 3 means invalid inputs or an existing output directory.
"""

from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import difflib
import hashlib
from html.parser import HTMLParser
import io
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time
from unittest.mock import patch


SYNTHETIC = re.compile(r"^(?:row|col|rect)_", re.IGNORECASE)
IMG_SRC = re.compile(r'(<img\b[^>]*?\bsrc=")([^"]*)(")', re.IGNORECASE)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def walk(node, child_key="children", path=""):
    yield path, node
    for index, child in enumerate(node.get(child_key, [])):
        yield from walk(child, child_key, f"{path}/{child_key}/{index}")


def urls_in(value):
    if isinstance(value, dict):
        return set().union(*(urls_in(item) for item in value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*(urls_in(item) for item in value)) if value else set()
    return {value} if isinstance(value, str) and value.startswith(("https://", "http://")) else set()


def counts(node, *, raw=False):
    nodes = [value for _, value in walk(node, "layers" if raw else "children")]
    result = {
        "nodes": len(nodes), "types": dict(sorted(Counter(item.get("type", "<missing>") for item in nodes).items())),
        "text_nodes": sum(item.get("type") == ("textLayer" if raw else "lanhutext") for item in nodes),
        "image_nodes": sum(item.get("type") == ("imageLayer" if raw else "lanhuimage") for item in nodes),
        "leaves": sum(not item.get("layers" if raw else "children") for item in nodes),
    }
    if raw:
        result["dds_export_layers"] = sum(bool(item.get("hasExportDDSImage")) for item in nodes)
        result["ordinary_export_layers"] = sum(bool(item.get("hasExportImage")) for item in nodes)
    else:
        result["composite_images"] = sum(bool(item.get("sourceLayerIds")) for item in nodes)
        result["synthetic_layer_ids"] = sum(bool(SYNTHETIC.match(str(item.get("layerId", "")))) for item in nodes)
    return result


def tree_rows(root, *, raw=False):
    return [
        {"path": path, "parent_path": path.rsplit("/", 2)[0] if path else None,
         "id": node.get("id"), "layerId": node.get("layerId"), "name": node.get("name", node.get("eleName")),
         "type": node.get("type"), "uiType": node.get("uiType"),
         "className": node.get("props", {}).get("className"),
         "frame": node.get("frame") if raw else node.get("rowDims"),
         "text": node.get("text", {}).get("value") if raw else node.get("props", {}).get("text"),
         "sourceLayerIds": node.get("sourceLayerIds", [])}
        for path, node in walk(root, "layers" if raw else "children")
    ]


def source_id_report(raw, reference, actual):
    raw_index = {str(node.get("id")): {"path": path, "name": node.get("name"), "type": node.get("type")}
                 for path, node in walk(raw["artboard"], "layers")}
    def collect(root):
        result = {}
        for path, node in walk(root):
            value = node.get("layerId")
            if isinstance(value, str) and value in raw_index:
                result.setdefault(value, []).append({"path": path, "type": node.get("type"),
                                                    "className": node.get("props", {}).get("className")})
        return result
    refs, acts = collect(reference), collect(actual)
    def descriptions(values):
        return [{"layerId": value, "raw": raw_index[value], "reference": refs.get(value, []), "actual": acts.get(value, [])}
                for value in sorted(values)]
    return {"reference_original_ids": len(refs), "actual_original_ids": len(acts),
            "missing_from_actual": descriptions(refs.keys() - acts.keys()),
            "extra_in_actual": descriptions(acts.keys() - refs.keys()),
            "duplicate_original_ids": descriptions({key for key in refs if len(refs[key]) > 1}
                                                    | {key for key in acts if len(acts[key]) > 1}),
            "note": "Source ID membership is diagnostic; pruned or merged source nodes are not automatically defects."}


def positional_contract(reference, actual):
    """Report tree positions separately; these are not identity matches."""
    differences = []
    def compare(left, right, path):
        if left is None or right is None:
            differences.append({"path": path, "field": "node", "reference_present": left is not None, "actual_present": right is not None})
            return
        fields = {
            "type": (left.get("type"), right.get("type")),
            "componentName": (left.get("componentName"), right.get("componentName")),
            "uiType": (left.get("uiType"), right.get("uiType")),
            "rowDims": (left.get("rowDims"), right.get("rowDims")),
            "props.className": (left.get("props", {}).get("className"), right.get("props", {}).get("className")),
            "props.style": (left.get("props", {}).get("style"), right.get("props", {}).get("style")),
        }
        left_id, right_id = str(left.get("layerId", "")), str(right.get("layerId", ""))
        if not (SYNTHETIC.match(left_id) and SYNTHETIC.match(right_id)):
            fields["layerId"] = left.get("layerId"), right.get("layerId")
        elif left_id.split("_", 1)[0] != right_id.split("_", 1)[0]:
            fields["synthetic_kind"] = left_id.split("_", 1)[0], right_id.split("_", 1)[0]
        for field, (expected, observed) in fields.items():
            if expected != observed:
                differences.append({"path": path, "field": field, "reference": expected, "actual": observed})
        lchildren, rchildren = left.get("children", []), right.get("children", [])
        for index in range(max(len(lchildren), len(rchildren))):
            compare(lchildren[index] if index < len(lchildren) else None,
                    rchildren[index] if index < len(rchildren) else None, f"{path}/children/{index}")
    compare(reference, actual, "")
    return {"contract_equal": not differences,
            "note": "Same tree positions only; generated row/col/rect suffixes ignored. Unequal positions must not be treated as matching source nodes.",
            "differences_by_field": dict(Counter(item["field"] for item in differences)), "differences": differences}


def compact_url(value):
    if value.startswith("data:"):
        return {"kind": "data_uri", "prefix": value.split(",", 1)[0], "characters": len(value), "sha256": sha(value.encode())}
    return value


class HTMLImages(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.images = []
        self.feed(text)
    def handle_starttag(self, tag, attrs):
        if tag == "img":
            attrs = dict(attrs)
            self.images.append({"class": attrs.get("class"), "src": compact_url(attrs.get("src", ""))})


def normalize_sources(text):
    index = 0
    def replace(match):
        nonlocal index
        index += 1
        return f"{match.group(1)}__IMAGE_SOURCE_{index}__{match.group(3)}"
    return IMG_SRC.sub(replace, text)


def compare_files(reference, actual, folder):
    results = {}
    diff_dir = folder / "diffs"
    diff_dir.mkdir()
    for name in sorted(reference.keys() | actual.keys()):
        expected, observed = reference.get(name), actual.get(name)
        diff = "".join(difflib.unified_diff((expected or "").splitlines(True), (observed or "").splitlines(True),
                                            fromfile="reference/" + name, tofile="actual/" + name))
        (diff_dir / (name + ".diff")).write_text(diff)
        results[name] = {"byte_equal": expected == observed, "reference_bytes": len(expected.encode()) if expected is not None else None,
                         "actual_bytes": len(observed.encode()) if observed is not None else None,
                         "reference_sha256": sha(expected.encode()) if expected is not None else None,
                         "actual_sha256": sha(observed.encode()) if observed is not None else None,
                         "diff_file": "diffs/" + name + ".diff"}
    if "index.html" in reference and "index.html" in actual:
        left, right = normalize_sources(reference["index.html"]), normalize_sources(actual["index.html"])
        html_diff = "".join(difflib.unified_diff(left.splitlines(True), right.splitlines(True), fromfile="reference/index.html", tofile="actual/index.html"))
        (diff_dir / "index.html.sources-normalized.diff").write_text(html_diff)
        results["html_diagnostics"] = {
            "equal_ignoring_img_src_values": left == right,
            "reference_images": HTMLImages(reference["index.html"]).images,
            "actual_images": HTMLImages(actual["index.html"]).images,
            "note": "Ignoring source values is diagnostic only; equality here does not establish image pixel parity.",
        }
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--official", type=Path, required=True)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--layout", choices=("inferred", "absolute"), default="inferred")
    args = parser.parse_args(argv)
    try:
        repo = args.repo.resolve()
        if not (repo / "lanhu_codegen").is_dir() and (repo / "mcp/lanhu/lanhu_codegen").is_dir():
            repo = repo / "mcp/lanhu"
        if not (repo / "lanhu_codegen").is_dir():
            raise ValueError("--repo must contain lanhu_codegen or mcp/lanhu/lanhu_codegen")
        if args.out.exists():
            raise ValueError(f"Refusing to overwrite frozen output: {args.out}")
        raw_bytes, official_bytes = args.raw.read_bytes(), args.official.read_bytes()
        raw = json.loads(raw_bytes)
        manifest_path = args.assets / "manifest.json" if args.assets.is_dir() else args.assets
        manifest = json.loads(manifest_path.read_text())
        entries = manifest.get("assets", manifest)
        if not isinstance(entries, dict):
            raise ValueError("Asset manifest must contain a URL-to-path object")
        allowed_urls = urls_in(raw)
        output = args.out.resolve()
        output.mkdir(parents=True)
        (output / "raw.json").write_bytes(raw_bytes)
        (output / "official-schema.json").write_bytes(official_bytes)
        (output / "source-cache-manifest.json").write_bytes(manifest_path.read_bytes())
        shutil.copyfile(__file__, output / "compare-frozen.py")
        source_inventory = {}
        for path in sorted((repo / "lanhu_codegen").rglob("*")):
            if path.is_file() and path.suffix in {".py", ".cjs", ".json"}:
                relative = path.relative_to(repo)
                data = path.read_bytes()
                target = output / "converter-sources" / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                source_inventory[str(relative)] = sha(data)
        metadata = {"created_at": datetime.now(timezone.utc).isoformat(), "python": sys.version,
                    "repo": str(repo), "layout": args.layout, "raw_sha256": sha(raw_bytes),
                    "official_schema_sha256": sha(official_bytes), "converter_source_sha256": source_inventory}
        write_json(output / "snapshot.json", metadata)
        sys.path.insert(0, str(repo))
        from lanhu_codegen import generate_design_files
        from lanhu_codegen.figma_schema import figma_to_dds_schema
        from lanhu_codegen.schema_compare import compare_schemas
        requests, cached, errors = [], {}, []
        def load(url):
            requests.append(url)
            if url not in allowed_urls:
                raise ValueError("Requested URL is not an original resource in raw.json: " + url)
            if url in cached:
                return cached[url][0]
            if url not in entries:
                raise FileNotFoundError("Source asset missing from cache manifest: " + url)
            entry = entries[url]
            filename = entry.get("path") if isinstance(entry, dict) else entry
            if not isinstance(filename, str):
                raise ValueError("Asset cache entry needs a path: " + url)
            path = Path(filename)
            path = path if path.is_absolute() else manifest_path.parent / path
            path = path.resolve()
            if path in {args.raw.resolve(), args.official.resolve()}:
                raise ValueError("Source asset entry must not point to an input JSON oracle")
            content = path.read_bytes()
            digest = sha(content)
            if isinstance(entry, dict) and entry.get("sha256") and entry["sha256"] != digest:
                raise ValueError("Cached source SHA256 mismatch: " + url)
            cached[url] = content, str(path), digest
            return content
        forbidden_files = {args.raw.resolve(), args.official.resolve(), output / "raw.json", output / "official-schema.json"}
        import builtins
        def guard(original):
            def opened(file, *positional, **keywords):
                if isinstance(file, (str, bytes, os.PathLike)):
                    path = Path(os.fsdecode(file)).resolve()
                    if path in forbidden_files:
                        raise AssertionError("Conversion attempted to read input/oracle JSON from disk")
                return original(file, *positional, **keywords)
            return opened
        before = deepcopy(raw)
        start = time.monotonic()
        actual = None
        try:
            # No reference schema object has been parsed, and only raw reaches
            # the converter. The cache loader serves original raw URLs only.
            with patch("builtins.open", guard(builtins.open)), patch("io.open", guard(io.open)):
                actual = figma_to_dds_schema(raw, asset_loader=load, layout=args.layout)
        except Exception as error:
            errors.append({"stage": "convert", "type": type(error).__name__, "message": str(error),
                           "layer_id": getattr(error, "layer_id", None), "feature": getattr(error, "feature", None)})
        conversion_seconds = time.monotonic() - start
        unchanged = raw == before
        if not unchanged:
            errors.append({"stage": "convert", "type": "InputMutation", "message": "Converter changed raw input"})
        reference = json.loads(official_bytes)
        summary = {"status": "compared" if actual is not None else "conversion_failed", "layout": args.layout,
                   "counts": {"raw": counts(before["artboard"], raw=True), "reference": counts(reference),
                              "actual": counts(actual) if actual is not None else None},
                   "input_unchanged": unchanged, "conversion_seconds": conversion_seconds, "errors": errors,
                   "note": "Counts and source-normalized HTML are diagnostics, not correctness scores or pixel-equivalence proofs."}
        write_json(output / "raw-tree.json", tree_rows(before["artboard"], raw=True))
        write_json(output / "reference-tree.json", tree_rows(reference))
        if actual is not None:
            write_json(output / "actual-schema.json", actual)
            write_json(output / "actual-tree.json", tree_rows(actual))
            full_diff = compare_schemas(reference, actual)
            write_json(output / "schema-diff.json", full_diff)
            summary["schema_comparison"] = full_diff["summary"]
            source_ids = source_id_report(before, reference, actual)
            write_json(output / "source-layer-id-diff.json", source_ids)
            summary["original_layer_ids"] = {key: len(value) if isinstance(value, list) else value
                                             for key, value in source_ids.items() if key != "note"}
            positional = positional_contract(reference, actual)
            write_json(output / "positional-contract-diff.json", positional)
            summary["positional_contract"] = {key: value for key, value in positional.items() if key != "differences"}
            filters = {"hierarchy-diff.json": lambda item: item["category"] in {"type", "parent", "order"},
                       "row-dims-diff.json": lambda item: item["category"] == "rowDims",
                       "props-style-diff.json": lambda item: item["field"].startswith("/props/style")}
            for filename, predicate in filters.items():
                write_json(output / filename, [item for item in full_diff["differences"] if predicate(item)])
        generated = {}
        for name, schema in (("actual", actual), ("reference", reference)):
            if schema is None:
                continue
            try:
                generated[name] = generate_design_files(schema)
                folder = output / name
                folder.mkdir()
                for filename, text in generated[name].items():
                    (folder / filename).write_text(text, encoding="utf-8")
            except Exception as error:
                errors.append({"stage": name + "_render", "type": type(error).__name__, "message": str(error)})
        if {"reference", "actual"} <= generated.keys():
            files = compare_files(generated["reference"], generated["actual"], output)
            write_json(output / "files-diff.json", files)
            summary["files"] = {name: value for name, value in files.items() if name != "html_diagnostics"}
            summary["html_equal_ignoring_img_src_values"] = files.get("html_diagnostics", {}).get("equal_ignoring_img_src_values")
        used = {}
        cache_dir = output / "used-source-assets"
        cache_dir.mkdir()
        for url, (content, path, digest) in cached.items():
            filename = digest + (".png" if content.startswith(b"\x89PNG") else ".bin")
            (cache_dir / filename).write_bytes(content)
            used[url] = {"path": "used-source-assets/" + filename, "original_path": path,
                         "sha256": digest, "bytes": len(content), "requests": requests.count(url)}
        write_json(output / "used-source-manifest.json", {"assets": used})
        write_json(output / "asset-requests.json", {"requests": requests, "uncached": sorted(set(requests) - cached.keys())})
        summary["assets"] = {"cached_entries_available": len(entries), "requested": len(requests),
                             "loaded_original_resources": len(cached), "uncached": sorted(set(requests) - cached.keys())}
        summary["errors"] = errors
        if errors:
            summary["status"] = "incomplete"
        write_json(output / "summary.json", summary)
        (output / "summary.md").write_text("# Frozen conversion comparison\n\n```json\n" + json.dumps(summary, ensure_ascii=False, indent=2) + "\n```\n")
        print(json.dumps({"output": str(output), **summary}, ensure_ascii=False, indent=2))
        return 2 if errors else 0
    except (OSError, ValueError, TypeError) as error:
        print(json.dumps({"error": type(error).__name__, "message": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
