"""Offline diagnostics for DDS schema iteration; never used by conversion.

Run ``python -m lanhu_codegen.schema_compare reference.json actual.json``.
Matching uses unique source layer IDs first, then unique DDS IDs. Generated
row/col/rect layer IDs are deliberately not source identities. Unresolved
ambiguity is reported as missing/added nodes, not guessed from order or geometry.

Values are compared exactly (no CSS normalization or pixel tolerance). Matching
leaf content and global rowDims alone does not establish render equivalence.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import dataclass
import json
from pathlib import Path
import re
import sys
from typing import Any


_SYNTHETIC_LAYER = re.compile(r"^(?:row|col|rect)_", re.IGNORECASE)
_CSS_URL = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.IGNORECASE)
_LAYOUT_KEYS = {
    "position", "display", "left", "right", "top", "bottom", "width", "height",
    "minWidth", "maxWidth", "minHeight", "maxHeight", "boxSizing", "float", "clear",
    "order", "gap", "rowGap", "columnGap", "justifyContent", "justifyItems",
    "justifySelf", "alignContent", "alignItems", "alignSelf", "placeContent",
    "placeItems", "placeSelf", "inlineSize", "blockSize", "minInlineSize",
    "maxInlineSize", "minBlockSize", "maxBlockSize", "aspectRatio", "verticalAlign",
}
_LAYOUT_PREFIXES = ("margin", "padding", "inset", "flex", "grid")
_RESOURCE_KEYS = {"src", "srcset", "srcSet", "poster", "imageUrl", "svgUrl", "url"}
_TEXT_KEYS = {"text", "lines", "content", "richText", "richtext", "textContent"}
_CATEGORIES = (
    "type", "parent", "order", "rowDims", "visual_style", "layout_style",
    "resources", "text", "identity", "metadata",
)
_MISSING = object()


@dataclass
class _Node:
    value: dict
    path: str
    parent: str | None
    index: int
    leaf: bool


def _pointer(path: str, key: Any) -> str:
    return path + "/" + str(key).replace("~", "~0").replace("/", "~1")


def _nodes(schema: dict) -> list[_Node]:
    result = []

    def walk(value, path, parent, index):
        if not isinstance(value, dict):
            raise ValueError(f"DDS node at {path or '/'} must be an object")
        children = value.get("children", [])
        if not isinstance(children, list):
            raise ValueError(f"DDS children at {path or '/'} must be an array")
        result.append(_Node(value, path, parent, index, not children))
        for child_index, child in enumerate(children):
            walk(child, f"{path}/children/{child_index}", path, child_index)

    walk(schema, "", None, 0)
    return result


def _identifier(node: _Node, field: str) -> str | None:
    value = node.value.get(field)
    if not isinstance(value, str) or not value.strip():
        return None
    if field == "layerId" and _SYNTHETIC_LAYER.match(value):
        return None
    return value


def _index(nodes: list[_Node], field: str) -> dict[str, list[_Node]]:
    result = defaultdict(list)
    for node in nodes:
        value = _identifier(node, field)
        if value is not None:
            result[value].append(node)
    return result


def _describe(node: _Node) -> dict:
    return {
        "path": node.path, "id": deepcopy(node.value.get("id")),
        "layerId": deepcopy(node.value.get("layerId")),
        "type": deepcopy(node.value.get("type")),
        "parent_path": node.parent, "index": node.index, "leaf": node.leaf,
    }


def _field_differences(reference: Any, actual: Any, path: str):
    if isinstance(reference, dict) and isinstance(actual, dict):
        for key in sorted(reference.keys() | actual.keys()):
            yield from _field_differences(reference.get(key, _MISSING), actual.get(key, _MISSING), _pointer(path, key))
    elif reference is _MISSING or actual is _MISSING or reference != actual:
        yield {
            "field": path,
            "reference_present": reference is not _MISSING,
            "actual_present": actual is not _MISSING,
            "reference": None if reference is _MISSING else deepcopy(reference),
            "actual": None if actual is _MISSING else deepcopy(actual),
        }


def _css_resources(style: dict) -> dict:
    return {
        key: [match.group(2).strip() for match in _CSS_URL.finditer(value)]
        for key, value in style.items()
        if isinstance(value, str) and _CSS_URL.search(value)
    }


def _node_differences(reference: _Node, actual: _Node) -> list[dict]:
    result = []

    def add(category, left, right, path):
        for difference in _field_differences(left, right, path):
            result.append({"category": category, **difference})

    def compare_styles(left, right, path):
        if not isinstance(left, dict) or not isinstance(right, dict):
            add("visual_style", left, right, path)
            return
        for key in sorted(left.keys() | right.keys()):
            # Unknown style properties remain visible in the visual report.
            category = "layout_style" if key in _LAYOUT_KEYS or key.startswith(_LAYOUT_PREFIXES) else "visual_style"
            add(category, left.get(key, _MISSING), right.get(key, _MISSING), _pointer(path, key))
        add("resources", _css_resources(left), _css_resources(right), path + "/@urls")

    left, right = reference.value, actual.value
    for key in sorted(left.keys() | right.keys()):
        if key == "children":
            continue
        lv, rv = left.get(key, _MISSING), right.get(key, _MISSING)
        if key == "style":
            compare_styles({} if lv is _MISSING else lv, {} if rv is _MISSING else rv, "/style")
        elif key == "props":
            if not isinstance(lv, dict) or not isinstance(rv, dict):
                add("metadata", lv, rv, "/props")
            left_props = lv if isinstance(lv, dict) else {}
            right_props = rv if isinstance(rv, dict) else {}
            for prop in sorted(left_props.keys() | right_props.keys()):
                lp, rp = left_props.get(prop, _MISSING), right_props.get(prop, _MISSING)
                if prop == "style":
                    compare_styles({} if lp is _MISSING else lp, {} if rp is _MISSING else rp, "/props/style")
                else:
                    category = ("resources" if prop in _RESOURCE_KEYS else "text" if prop in _TEXT_KEYS
                                else "identity" if prop == "className" else "metadata")
                    add(category, lp, rp, _pointer("/props", prop))
        elif key == "data" and (left.get("type") in {"lanhutext", "lanhuimage"}
                                 or right.get("type") in {"lanhutext", "lanhuimage"}):
            category = "resources" if "lanhuimage" in {left.get("type"), right.get("type")} else "text"
            add(category, lv, rv, "/data")
        else:
            category = ("type" if key in {"type", "componentName"} else "rowDims" if key == "rowDims"
                        else "identity" if key in {"id", "layerId", "eleName"}
                        else "resources" if key in _RESOURCE_KEYS else "text" if key in _TEXT_KEYS else "metadata")
            add(category, lv, rv, _pointer("", key))
    return result


def compare_schemas(reference: dict, actual: dict) -> dict:
    """Return a deterministic JSON-serializable report without changing inputs.

    ``structural_equal`` covers matched nodes, types, parent links and sibling
    indices. Leaf equality flags require complete coverage of *both* leaf sets;
    unmatched containers can therefore fail structure while leaves still agree.
    Empty leaf sets or fewer output nodes are never used as a success shortcut.
    ``all_compared_fields_equal`` also covers class names and other metadata.
    """
    ref_nodes, act_nodes = _nodes(reference), _nodes(actual)
    ref_by_path = {node.path: node for node in ref_nodes}
    act_by_path = {node.path: node for node in act_nodes}
    mapping: dict[str, str] = {}
    reverse: dict[str, str] = {}
    basis: dict[str, str] = {}
    duplicates, identity_conflicts = [], []
    ignored_layer_ids = []
    for side, nodes in (("reference", ref_nodes), ("actual", act_nodes)):
        for node in nodes:
            layer_id = node.value.get("layerId")
            if _identifier(node, "layerId") is None:
                ignored_layer_ids.append({"side": side, "path": node.path, "layerId": deepcopy(layer_id),
                                          "reason": "synthetic" if isinstance(layer_id, str) and _SYNTHETIC_LAYER.match(layer_id)
                                          else "empty_or_invalid"})

    for field in ("layerId", "id"):
        ref_index, act_index = _index(ref_nodes, field), _index(act_nodes, field)
        for value in sorted(ref_index.keys() | act_index.keys()):
            refs, acts = ref_index.get(value, []), act_index.get(value, [])
            if len(refs) > 1 or len(acts) > 1:
                duplicates.append({"field": field, "value": value,
                                   "reference_paths": [node.path for node in refs],
                                   "actual_paths": [node.path for node in acts]})
                continue
            if len(refs) != 1 or len(acts) != 1:
                continue
            ref, act = refs[0], acts[0]
            if ref.path in mapping or act.path in reverse:
                continue
            if field == "id":
                ref_layer, act_layer = _identifier(ref, "layerId"), _identifier(act, "layerId")
                if ref_layer is not None and act_layer is not None and ref_layer != act_layer:
                    identity_conflicts.append({"id": value, "reference": _describe(ref), "actual": _describe(act)})
                    continue
            mapping[ref.path], reverse[act.path], basis[ref.path] = act.path, ref.path, field

    missing = [_describe(node) for node in ref_nodes if node.path not in mapping]
    added = [_describe(node) for node in act_nodes if node.path not in reverse]
    matches, differences = [], []
    leaf_pairs = []
    for ref in ref_nodes:
        if ref.path not in mapping:
            continue
        act = act_by_path[mapping[ref.path]]
        matches.append({"reference": _describe(ref), "actual": _describe(act), "matched_by": basis[ref.path]})
        changes = _node_differences(ref, act)
        parents_equal = ((ref.parent is None and act.parent is None)
                         or (ref.parent is not None and ref.parent in mapping and mapping[ref.parent] == act.parent))
        if not parents_equal:
            changes.append({"category": "parent", "field": "/parent",
                            "reference": None if ref.parent is None else _describe(ref_by_path[ref.parent]),
                            "actual": None if act.parent is None else _describe(act_by_path[act.parent])})
        if ref.index != act.index:
            changes.append({"category": "order", "field": "/sibling_index",
                            "reference": ref.index, "actual": act.index,
                            "same_matched_parent": parents_equal})
        if ref.leaf and act.leaf:
            leaf_pairs.append((ref, act, changes))
        for change in changes:
            differences.append({"reference_path": ref.path, "actual_path": act.path, **change})

    counts = Counter(item["category"] for item in differences)
    complete = not missing and not added
    ref_leaves = sum(node.leaf for node in ref_nodes)
    act_leaves = sum(node.leaf for node in act_nodes)
    leaf_complete = len(leaf_pairs) == ref_leaves == act_leaves
    leaf_categories = {change["category"] for _, _, changes in leaf_pairs for change in changes}
    return {
        "report_version": 1,
        "comparison": {
            "values": "exact; no CSS normalization or numeric tolerance",
            "matching": "unique non-synthetic layerId, then unique id without conflicting source layerId",
            "limitations": "Leaf content/rowDims equality does not prove equivalent CSS layout or rendered pixels.",
        },
        "summary": {
            "reference_nodes": len(ref_nodes), "actual_nodes": len(act_nodes), "matched_nodes": len(matches),
            "missing_nodes": len(missing), "added_nodes": len(added),
            "matched_by": {field: sum(value == field for value in basis.values()) for field in ("layerId", "id")},
            "reference_leaves": ref_leaves, "actual_leaves": act_leaves, "matched_leaf_pairs": len(leaf_pairs),
            "matching_complete": complete, "leaf_matching_complete": leaf_complete,
            "structural_equal": complete and not any(counts[key] for key in ("type", "parent", "order")),
            "leaf_content_equal": leaf_complete and not leaf_categories.intersection({"type", "text", "resources"}),
            "leaf_geometry_equal": leaf_complete and "rowDims" not in leaf_categories,
            "leaf_visual_style_equal": leaf_complete and not leaf_categories.intersection({"visual_style", "resources"}),
            "all_compared_fields_equal": complete and not differences,
            "difference_count": len(differences),
            "differences_by_category": {category: counts[category] for category in _CATEGORIES},
            "duplicate_identifier_groups": len(duplicates), "identity_conflicts": len(identity_conflicts),
        },
        "matching_diagnostics": {"duplicate_identifiers": duplicates, "identity_conflicts": identity_conflicts,
                                 "ignored_layer_ids": ignored_layer_ids},
        "missing_nodes": missing, "added_nodes": added, "matches": matches, "differences": differences,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", type=Path, help="Reference DDS schema JSON")
    parser.add_argument("actual", type=Path, help="Actual DDS schema JSON")
    parser.add_argument("--output", "-o", type=Path, help="Write JSON to this file instead of stdout")
    args = parser.parse_args(argv)
    try:
        reference = json.loads(args.reference.read_text(encoding="utf-8"))
        actual = json.loads(args.actual.read_text(encoding="utf-8"))
        report = compare_schemas(reference, actual)
        encoded = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        if args.output:
            args.output.write_text(encoded, encoding="utf-8")
        else:
            sys.stdout.write(encoded)
    except (OSError, ValueError, TypeError) as error:
        sys.stderr.write(json.dumps({"error": str(error)}, ensure_ascii=False) + "\n")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
