"""Deterministic semantic CSS names for an already regrouped DDS tree.

This is an inference from observed DDS output, not the unpublished official
naming algorithm. Explicit ImageText/TextGroup markers take priority over node
type; nonempty text-only/image-only wrappers are structural classifications.
An unmarked horizontal image/text pair is not enough to identify ImageText (it
can be an input control). Images observed at 14/16 px are thumbnails and at
24/30/32/44 px are labels. The <24 px cutoff, 64 px label upper bound and 0.5 px
square tolerance retain heuristic behavior for unobserved sizes. Ordinary
block/group/box role progression is also a heuristic, not an official rule.
The two observed official trees use one shared ordinary prefix for each set of
nonempty siblings, but the parent's choice among block/group/box/section remains
unexplained; identical local subtrees can receive different choices. The fallback
below preserves sibling consistency without pretending to recover that choice.
Stable preorder counters are maintained separately for each prefix.

No source IDs, layer names, text content, existing CSS classes or reference
schema are consulted. Only props.className is changed on a deep copy.
"""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
import math
import re


_THUMBNAIL_MAX = 24.0
_LABEL_MAX = 64.0
_SQUARE_TOLERANCE = 0.5
_PIXELS = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:px)?", re.IGNORECASE)


def _number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        if not _PIXELS.fullmatch(value.strip()):
            return None
        value = value.strip()
        value = value[:-2] if value.lower().endswith("px") else value
    if not isinstance(value, (int, float, str)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _kind(node):
    return node.get("type") or node.get("componentName")


def _children(node):
    children = node.get("children", [])
    if not isinstance(children, list) or any(not isinstance(child, dict) for child in children):
        raise ValueError("DDS children must be an array of node objects")
    return children


def _styles(node):
    props = node.get("props") or {}
    if not isinstance(props, dict):
        raise ValueError("DDS props must be an object")
    style = props.get("style") or {}
    return style if isinstance(style, dict) else {}


def _dimension(node, key):
    frame = node.get("rowDims") or {}
    if isinstance(frame, dict) and key in frame:
        return _number(frame[key])
    for style in (_styles(node), node.get("style") or {}):
        if isinstance(style, dict) and key in style:
            return _number(style[key])
    return None


def _image_prefix(node):
    width, height = _dimension(node, "width"), _dimension(node, "height")
    if width is None or height is None or min(width, height) <= 0 or abs(width - height) > _SQUARE_TOLERANCE:
        return "image"
    size = max(width, height)
    return "thumbnail" if size < _THUMBNAIL_MAX else "label" if size <= _LABEL_MAX else "image"


def assign_class_names(root: dict) -> dict:
    """Copy a DDS tree and assign semantic names without changing IDs or order.

    The root is ``page``. Other prefixes receive independent one-based counters.
    Class names describe the inferred roles; they do not assert UI semantics or
    render equivalence with an official schema.
    """
    if not isinstance(root, dict):
        raise ValueError("DDS root must be an object")
    result = deepcopy(root)
    counts = Counter()

    def visit(node, parent_prefix=None):
        children = _children(node)
        kind = _kind(node)
        if parent_prefix is None:
            prefix = "page"
        elif node.get("uiType") in {"ImageText", "TextGroup"}:
            # TextGroup can describe a block containing multiple text nodes,
            # not only a single lanhutext leaf.
            prefix = {"ImageText": "image-text", "TextGroup": "text-group"}[node["uiType"]]
        elif kind == "lanhuimage":
            prefix = _image_prefix(node)
        elif kind == "lanhutext":
            prefix = "text-group" if parent_prefix == "image-text" else "text"
        elif children and all(_kind(child) == "lanhutext" for child in children):
            prefix = "text-wrapper"
        elif children and all(_kind(child) == "lanhuimage" for child in children):
            prefix = "image-wrapper"
        elif not children:
            prefix = "group"
        else:
            prefix = {"page": "block", "block": "group", "group": "box", "box": "group"}.get(parent_prefix, "group")
        props = node.setdefault("props", {})
        if not isinstance(props, dict):
            raise ValueError("DDS props must be an object")
        if parent_prefix is None:
            props["className"] = "page"
        else:
            counts[prefix] += 1
            props["className"] = f"{prefix}_{counts[prefix]}"
        for child in children:
            visit(child, prefix)

    visit(result)
    return result
