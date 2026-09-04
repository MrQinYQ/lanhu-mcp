#!/usr/bin/env python3
"""Check a frozen compare_figma_dds snapshot under export acceptance v2.

Usage:
  python check_export_equivalence.py SNAPSHOT --asset-manifest assets.json \
      --output acceptance.json

Only a bijective class rename and pixel-identical static PNG img sources may
change. Tree identity/order/semantics/frames and every other byte of the five
exports must match. No renderer, converter, downloaded code or network is used.
The manifest supports {URL: "path"} and {"assets": {URL: {"path": "path",
"sha256": "optional digest"}}}; paths are relative to the manifest directory.
Exit codes: 0 passed, 1 failed equivalence, 2 unreadable/invalid inputs. Without
--output the complete JSON report goes to stdout; with it stdout is a summary.
"""

from __future__ import annotations

import argparse
from collections import Counter
import difflib
import hashlib
import html
from html.parser import HTMLParser
import io
import json
import math
from pathlib import Path
import re
import sys


FILES = ("index.html", "index.css", "common.css", "index.rem.css", "index.response.css")
CLASS_NAME = re.compile(r"-?[_A-Za-z][_A-Za-z0-9-]*\Z")
SYNTHETIC = re.compile(r"(row|col|rect)_.+\Z")
ATTRIBUTE = re.compile(r'''\s+([^\s/>=]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?''')
SIMPLE_SELECTOR = re.compile(r"\s*\.(-?[_A-Za-z][_A-Za-z0-9-]*)\s*\Z")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def compact_source(value: str):
    if value.startswith("data:"):
        return {"kind": "data_uri", "prefix": value.split(",", 1)[0],
                "characters": len(value), "sha256": sha(value.encode("utf-8"))}
    return value


def load_json(path: Path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result

    def constant(value):
        raise ValueError(f"Non-finite JSON value: {value}")

    def floating(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("Non-finite JSON number")
        return number

    data = path.read_bytes()
    return json.loads(data, object_pairs_hook=pairs, parse_constant=constant, parse_float=floating), {
        "path": str(path.resolve()), "bytes": len(data), "sha256": sha(data),
    }


def nodes(root, child_key="children", path=""):
    if not isinstance(root, dict):
        raise ValueError(f"Node {path or '/'} must be an object")
    children = root.get(child_key, [])
    if not isinstance(children, list):
        raise ValueError(f"Node {path or '/'} {child_key} must be an array")
    yield path, root
    for index, child in enumerate(children):
        yield from nodes(child, child_key, f"{path}/{child_key}/{index}")


def compare_trees(raw, reference, actual):
    raw_nodes = list(nodes(raw["artboard"], "layers"))
    raw_ids = [node.get("id") for _, node in raw_nodes]
    if any(not isinstance(value, str) or not value for value in raw_ids) or len(set(raw_ids)) != len(raw_ids):
        raise ValueError("Raw source layer IDs must be nonempty, unique strings")
    source_ids = set(raw_ids)
    sides = {"reference": dict(nodes(reference)), "actual": dict(nodes(actual))}
    differences, identities = [], {}
    for side, items in sides.items():
        originals = []
        identities[side] = {}
        for path, node in items.items():
            for field in ("type", "componentName"):
                if not isinstance(node.get(field), str) or not node[field]:
                    differences.append({"side": side, "path": path, "field": "invalid_" + field})
            if not isinstance(node.get("uiType", ""), str) or not isinstance(node.get("props"), dict):
                differences.append({"side": side, "path": path, "field": "invalid_uiType_or_props"})
            identity = node.get("layerId")
            if isinstance(identity, str) and identity in source_ids:
                identities[side][path] = ["original", identity]
                originals.append(identity)
            elif isinstance(identity, str) and (match := SYNTHETIC.fullmatch(identity)):
                identities[side][path] = ["synthetic", match[1]]
            else:
                identities[side][path] = ["unknown", identity]
                differences.append({"side": side, "path": path, "field": "unknown_layer_id", "value": identity})
            frame = node.get("rowDims")
            valid = isinstance(frame, dict) and all(
                isinstance(frame.get(key), (int, float)) and not isinstance(frame[key], bool)
                and math.isfinite(frame[key]) and (key not in {"width", "height"} or frame[key] >= 0)
                for key in ("left", "top", "width", "height"))
            if not valid:
                differences.append({"side": side, "path": path, "field": "invalid_frame", "value": frame})
        for identity, count in Counter(originals).items():
            if count > 1:
                differences.append({"side": side, "field": "duplicate_original_id", "layerId": identity, "count": count})
    for path in sorted(sides["reference"].keys() | sides["actual"].keys()):
        left, right = sides["reference"].get(path), sides["actual"].get(path)
        if left is None or right is None:
            differences.append({"path": path, "field": "node_presence", "reference": left is not None, "actual": right is not None})
            continue
        fields = {key: (left.get(key), right.get(key)) for key in ("type", "componentName", "rowDims")}
        fields["uiType"] = left.get("uiType", ""), right.get("uiType", "")
        fields["identity"] = identities["reference"][path], identities["actual"][path]
        fields["children_count"] = len(left.get("children", [])), len(right.get("children", []))
        for key, (expected, observed) in fields.items():
            if expected != observed:
                differences.append({"path": path, "field": key, "reference": expected, "actual": observed})
    report = {"passed": not differences, "reference_nodes": len(sides["reference"]),
              "actual_nodes": len(sides["actual"]), "source_nodes": len(source_ids),
              "differences": differences}
    pairs = [(path, node, sides["actual"][path]) for path, node in sides["reference"].items()] if not differences else []
    return report, pairs


def class_mapping(pairs):
    mapping, reverse, evidence, errors = {}, {}, [], []
    for path, reference, actual in pairs:
        left, right = reference.get("props", {}).get("className"), actual.get("props", {}).get("className")
        if not isinstance(left, str) or not isinstance(right, str) or not CLASS_NAME.fullmatch(left) or not CLASS_NAME.fullmatch(right):
            errors.append({"path": path, "code": "invalid_class_name", "reference": left, "actual": right})
        elif right in mapping or left in reverse:
            errors.append({"path": path, "code": "class_name_collision", "reference": left, "actual": right})
        else:
            mapping[right], reverse[left] = left, right
            evidence.append({"path": path, "actual": right, "reference": left})
    return {"passed": not errors, "count": len(mapping), "mapping": evidence, "differences": errors}, mapping


class HTMLDocument(HTMLParser):
    """Locate real attribute value spans without reserializing other bytes."""

    def __init__(self, text):
        super().__init__(convert_charrefs=False)
        self.text, self.tags = text, []
        self.line_offsets = [0, *(match.end() for match in re.finditer("\n", text))]
        self.feed(text)
        self.close()

    def handle_starttag(self, tag, attrs):
        source = self.get_starttag_text()
        line, column = self.getpos()
        start = self.line_offsets[line - 1] + column
        name = re.match(r"<[^\s/>]+", source)
        position, attributes = name.end(), []
        while position < len(source):
            if re.fullmatch(r"\s*/?>", source[position:]):
                break
            match = ATTRIBUTE.match(source, position)
            if not match:
                raise ValueError("Unsupported HTML attribute syntax at offset " + str(start + position))
            group = next((group for group in (2, 3, 4) if match[group] is not None), None)
            attributes.append({"name": match[1].lower(), "value": html.unescape(match[group]) if group else None,
                               "raw": match[group] if group else None,
                               "start": start + match.start(group) if group else None,
                               "end": start + match.end(group) if group else None})
            position = match.end()
        self.tags.append({"tag": tag, "attributes": attributes, "offset": start})

    handle_startendtag = handle_starttag


def bind_html(document, schema_nodes, side):
    names = {node["props"]["className"]: node for _, node in schema_nodes}
    bindings, errors, namespace = {}, [], set()
    for tag in document.tags:
        classes = [attr for attr in tag["attributes"] if attr["name"] == "class"]
        if len(classes) > 1:
            errors.append({"side": side, "code": "duplicate_class_attribute", "offset": tag["offset"]})
        tokens = (classes[0]["value"] or "").split() if classes else []
        namespace.update(tokens)
        primary = [token for token in tokens if token in names]
        if len(primary) > 1:
            errors.append({"side": side, "code": "multiple_schema_classes_on_element", "classes": primary})
        for name in primary:
            if name in bindings:
                errors.append({"side": side, "code": "duplicate_schema_class_in_html", "className": name})
            bindings[name] = tag
        if tag["tag"] == "img" and not primary:
            errors.append({"side": side, "code": "unbound_image_element", "offset": tag["offset"]})
    for name in names.keys() - bindings.keys():
        errors.append({"side": side, "code": "schema_class_missing_from_html", "className": name})
    return bindings, errors, namespace


def png_resource(source, manifest, manifest_path, *, allow_data_uri):
    evidence = {"source": compact_source(source)}
    if source.startswith("data:"):
        if not allow_data_uri or not source.startswith("data:image/png;base64,"):
            raise ValueError("Only actual static PNG base64 data URIs are allowed")
        import base64
        data = base64.b64decode(source.split(",", 1)[1], validate=True)
        evidence["storage"] = "data_uri"
    else:
        if source not in manifest:
            raise ValueError("Image URL is missing from the offline asset manifest")
        entry = manifest[source]
        filename = entry.get("path") if isinstance(entry, dict) else entry
        if not isinstance(filename, str) or not filename:
            raise ValueError("Asset entry must provide a local path")
        path = Path(filename)
        path = path if path.is_absolute() else manifest_path.parent / path
        data = path.read_bytes()
        evidence.update(storage="cache", path=str(path.resolve()))
        if isinstance(entry, dict) and entry.get("sha256") and entry["sha256"] != sha(data):
            raise ValueError("Cached image SHA256 differs from asset manifest")
    evidence.update(bytes=len(data), sha256=sha(data))
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("Image is not a PNG")
    cursor = 8
    while cursor + 12 <= len(data):
        length = int.from_bytes(data[cursor:cursor + 4], "big")
        kind = data[cursor + 4:cursor + 8]
        if cursor + length + 12 > len(data):
            raise ValueError("Truncated PNG chunk")
        if kind == b"acTL":
            raise ValueError("APNG is not a static PNG, including single-frame APNG")
        cursor += length + 12
        if kind == b"IEND":
            break
    from PIL import Image
    with Image.open(io.BytesIO(data)) as image:
        if image.format != "PNG" or image.n_frames != 1 or getattr(image, "is_animated", False):
            raise ValueError("Image must be a static single-frame PNG")
        image.load()
        rgba = image.convert("RGBA")
        pixels, dimensions = rgba.tobytes(), list(rgba.size)
    evidence.update(format="PNG", frames=1, dimensions=dimensions, rgba_sha256=sha(pixels), rgba_bytes=len(pixels))
    return evidence, pixels


def verify_images(pairs, reference_bindings, actual_bindings, manifest, manifest_path):
    evidence, errors, replacements = [], [], []
    for path, reference, actual in pairs:
        if reference["type"] != "lanhuimage":
            continue
        item = {"path": path, "actual_class": actual["props"]["className"],
                "reference_class": reference["props"]["className"]}
        sources, attributes = {}, {}
        for side, node, bindings in (("reference", reference, reference_bindings), ("actual", actual, actual_bindings)):
            source = node.get("props", {}).get("src")
            tag = bindings.get(node["props"]["className"])
            attrs = [attr for attr in tag["attributes"] if attr["name"] == "src"] if tag else []
            if (not isinstance(source, str) or not source or not tag or tag["tag"] != "img"
                    or len(attrs) != 1 or attrs[0]["value"] != source):
                errors.append({"path": path, "side": side, "code": "image_schema_html_source_mismatch"})
                continue
            sources[side], attributes[side] = source, attrs[0]
        if len(sources) != 2:
            item["passed"] = False
            evidence.append(item)
            continue
        item.update(actual_source=compact_source(sources["actual"]), reference_source=compact_source(sources["reference"]))
        if sources["actual"] == sources["reference"]:
            item.update(passed=True, basis="identical_source_string")
        else:
            try:
                left, expected = png_resource(sources["reference"], manifest, manifest_path, allow_data_uri=False)
                right, observed = png_resource(sources["actual"], manifest, manifest_path, allow_data_uri=True)
                item.update(reference_png=left, actual_png=right, basis="all_static_png_rgba_pixels")
                equal = left["dimensions"] == right["dimensions"] and expected == observed
                if not equal:
                    raise ValueError("PNG dimensions or complete RGBA pixels differ")
            except (ValueError, OSError, ImportError) as exc:
                item.update(passed=False, error=str(exc))
                errors.append({"path": path, "code": "image_equivalence_unproven", "reason": str(exc)})
            else:
                item["passed"] = True
                attribute = attributes["actual"]
                replacements.append((attribute["start"], attribute["end"], attributes["reference"]["raw"]))
        evidence.append(item)
    return {"passed": not errors, "count": len(evidence), "images": evidence, "differences": errors}, replacements


def apply_spans(text, replacements):
    previous = len(text)
    for start, end, value in sorted(replacements, reverse=True):
        if end > previous or start < 0 or start > end:
            raise ValueError("Overlapping normalization spans")
        text = text[:start] + value + text[end:]
        previous = start
    return text


def normalize_html(document, mapping, image_replacements):
    replacements = list(image_replacements)
    for tag in document.tags:
        for attr in tag["attributes"]:
            if attr["name"] != "class" or attr["raw"] is None:
                continue
            value = re.sub(r"\S+", lambda token: mapping.get(token[0], token[0]), attr["raw"])
            if value != attr["raw"]:
                replacements.append((attr["start"], attr["end"], value))
    return apply_spans(document.text, replacements), len(replacements) - len(image_replacements)


def normalize_css(text, mapping):
    """Rename only simple class rule preludes, never comments/string values."""
    masked, replacements, selectors = list(text), [], set()
    index, segment, parentheses = 0, 0, 0
    stack = []
    while index < len(text):
        if text.startswith("/*", index):
            end = text.find("*/", index + 2)
            if end < 0:
                raise ValueError("Unterminated CSS comment")
            for position in range(index, end + 2):
                if not masked[position].isspace():
                    masked[position] = " "
            index = end + 2
            continue
        char = text[index]
        if char in "\"'":
            quote = char
            string_start = index
            index += 1
            while index < len(text) and text[index] != quote:
                index += 2 if text[index] == "\\" else 1
            if index >= len(text):
                raise ValueError("Unterminated CSS string")
            for position in range(string_start, index + 1):
                if not masked[position].isspace():
                    masked[position] = " "
        elif char == "(":
            parentheses += 1
        elif char == ")":
            parentheses = max(0, parentheses - 1)
        elif not parentheses and char == "{":
            prelude = "".join(masked[segment:index])
            selector_context = all(kind == "at-rule" for kind in stack) and not prelude.lstrip().startswith("@")
            match = SIMPLE_SELECTOR.fullmatch(prelude) if selector_context else None
            if selector_context:
                referenced = set(re.findall(r"\.(-?[_A-Za-z][_A-Za-z0-9-]*)", prelude))
                selectors.update(referenced)
                if not match and any(mapping.get(name, name) != name for name in referenced):
                    raise ValueError("A renamed class occurs in an unsupported non-simple CSS selector")
            if match:
                name = match[1]
                selectors.add(name)
                changed = mapping.get(name, name)
                if changed != name:
                    replacements.append((segment + match.start(1), segment + match.end(1), changed))
            stack.append("at-rule" if prelude.lstrip().startswith("@") else "rule")
            segment = index + 1
        elif not parentheses and char == "}":
            if not stack:
                raise ValueError("Unbalanced CSS closing brace")
            stack.pop()
            segment = index + 1
        elif not parentheses and char == ";":
            segment = index + 1
        index += 1
    if stack or parentheses:
        raise ValueError("Unbalanced CSS blocks or parentheses")
    return apply_spans(text, replacements), len(replacements), selectors


def file_comparison(expected, actual, normalized, name):
    equal = expected == normalized
    result = {"passed": equal, "reference_bytes": len(expected), "actual_bytes": len(actual),
              "normalized_bytes": len(normalized), "reference_sha256": sha(expected),
              "actual_sha256": sha(actual), "normalized_sha256": sha(normalized)}
    if not equal:
        result["first_different_byte"] = next((i for i, (left, right) in enumerate(zip(expected, normalized)) if left != right), min(len(expected), len(normalized)))
        diff = "".join(difflib.unified_diff(expected.decode("utf-8").splitlines(True), normalized.decode("utf-8").splitlines(True),
                                             fromfile="reference/" + name, tofile="normalized-actual/" + name))
        result["unified_diff"] = diff[:20000]
        result["diff_truncated"] = len(diff) > 20000
    return result


def check_export_equivalence(snapshot_dir, asset_manifest):
    snapshot, manifest_path = Path(snapshot_dir).resolve(), Path(asset_manifest).resolve()
    report = {"report_version": 1, "contract": "export-equivalence-v2", "status": "failed", "passed": False,
              "inputs": {"snapshot": str(snapshot)}, "input_errors": [], "differences": []}
    try:
        values = {}
        for name in ("raw.json", "official-schema.json", "actual-schema.json"):
            values[name], report["inputs"][name] = load_json(snapshot / name)
        manifest, report["inputs"]["asset_manifest"] = load_json(manifest_path)
        if not isinstance(manifest, dict):
            raise ValueError("Asset manifest must be a JSON object")
        entries = manifest.get("assets", manifest)
        if not isinstance(entries, dict):
            raise ValueError("Asset manifest must map URLs to local paths")
        if (snapshot / "snapshot.json").exists():
            metadata, report["inputs"]["snapshot.json"] = load_json(snapshot / "snapshot.json")
            for field, name in (("raw_sha256", "raw.json"), ("official_schema_sha256", "official-schema.json")):
                if field in metadata and metadata[field] != report["inputs"][name]["sha256"]:
                    report["differences"].append({"code": "snapshot_input_hash_mismatch", "file": name})
        data = {}
        for side in ("actual", "reference"):
            directory = snapshot / side
            inventory = sorted(str(path.relative_to(directory)) for path in directory.rglob("*") if path.is_file())
            if set(inventory) != set(FILES):
                report["differences"].append({"code": "export_file_inventory", "side": side, "expected": list(FILES), "actual": inventory})
            data[side] = {name: (directory / name).read_bytes() for name in FILES}
            for content in data[side].values():
                content.decode("utf-8")
        tree, pairs = compare_trees(values["raw.json"], values["official-schema.json"], values["actual-schema.json"])
        report["tree"] = tree
    except (OSError, ValueError, KeyError, TypeError) as exc:
        report["input_errors"].append({"code": "invalid_input", "reason": str(exc)})
        return report
    normalized = dict(data["actual"])
    if pairs:
        classes, mapping = class_mapping(pairs)
        report["classes"] = classes
        if classes["passed"]:
            try:
                reference_html, actual_html = HTMLDocument(data["reference"]["index.html"].decode()), HTMLDocument(data["actual"]["index.html"].decode())
                refs, re, _ = bind_html(reference_html, [(path, ref) for path, ref, _ in pairs], "reference")
                acts, ae, namespace = bind_html(actual_html, [(path, act) for path, _, act in pairs], "actual")
                report["html_bindings"] = {"passed": not (re or ae), "differences": re + ae}
                images, replacements = verify_images(pairs, refs, acts, entries, manifest_path)
                report["images"] = images
                text, class_count = normalize_html(actual_html, mapping, replacements)
                normalized["index.html"] = text.encode("utf-8")
                stats = {"html_class_attributes": class_count, "html_img_src_attributes": len(replacements), "css_simple_selectors": {}}
                for name in FILES[1:]:
                    text, count, selectors = normalize_css(data["actual"][name].decode("utf-8"), mapping)
                    namespace.update(selectors)
                    normalized[name] = text.encode("utf-8")
                    stats["css_simple_selectors"][name] = count
                reverse = {}
                for token in sorted(namespace):
                    renamed = mapping.get(token, token)
                    if renamed in reverse and reverse[renamed] != token:
                        report["differences"].append({"code": "class_collision_with_unmapped_token", "actual": [reverse[renamed], token], "reference": renamed})
                    reverse[renamed] = token
                report["normalization"] = stats
            except (ValueError, OSError) as exc:
                report["differences"].append({"code": "normalization_error", "reason": str(exc)})
    else:
        report["normalization"] = {"skipped": "Full tree contract failed; no class or image aliases are trusted"}
    report["files"] = {name: file_comparison(data["reference"][name], data["actual"][name], normalized[name], name) for name in FILES}
    report["passed"] = (tree["passed"] and not report["differences"]
                        and all(report.get(stage, {}).get("passed", False) for stage in ("classes", "html_bindings", "images"))
                        and all(item["passed"] for item in report["files"].values()))
    report["status"] = "passed" if report["passed"] else "failed"
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--asset-manifest", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = check_export_equivalence(args.snapshot, args.asset_manifest)
    serialized = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.write_text(serialized, encoding="utf-8")
        print(json.dumps({"status": report["status"], "passed": report["passed"], "report": str(args.output.resolve())}))
    else:
        print(serialized, end="")
    return 2 if report["input_errors"] else 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
