"""Empirical DDS semantic boundaries derived from source export metadata.

Ordinary image exports are designer-authored boundaries, whereas DDS-only
exports can be small constituent icons. Keep that distinction during layout
inference rather than guessing roles from layer IDs or literal text content.
"""

from __future__ import annotations

from collections import Counter
from copy import deepcopy

from .figma_layout import (
    _BOX_KEYS, _EPSILON, _PLACEMENT_KEYS, _content_frame, _end, _frame, _group, _no_effect,
    _margins, _overlap, _paint_bounds, _place, _styles,
)


def _plain_group(node: dict) -> bool:
    if node.get("type") != "lanhublock" or node.get("uiType") not in (None, "", "TextGroup"):
        return False
    if any(node.get(key) for key in ("isMask", "clipped", "condition", "loop", "events")):
        return False
    if any(node.get("layoutInsets", {}).values()):
        return False
    safe = _BOX_KEYS | _PLACEMENT_KEYS
    return all(key in safe or _no_effect(key, value) for key, value in _styles(node).items())


def _text_column(node: dict) -> bool:
    children = node.get("children", [])
    return (len(children) >= 2 and _plain_group(node)
            and _styles(node).get("flexDirection") == "column"
            and all(child.get("type") == "lanhutext" for child in children))


def _center(frame: dict, axis: str) -> float:
    return frame[axis] + frame["width" if axis == "left" else "height"] / 2


def _ordinary_anchor(node: dict) -> bool:
    frame = _frame(node)
    return (node.get("type") == "lanhuimage" and node.get("sourceHasOrdinaryImage")
            and 0 < frame["width"] == frame["height"] and not node.get("children"))


def _clear_group(members: list[dict], siblings: list[dict]) -> bool:
    bounds = [_paint_bounds(node) for node in members]
    if any(frame is None for frame in bounds):
        return False
    left, top = min(frame["left"] for frame in bounds), min(frame["top"] for frame in bounds)
    union = {"left": left, "top": top,
             "width": max(_end(frame, "left") for frame in bounds) - left,
             "height": max(_end(frame, "top") for frame in bounds) - top}
    for other in siblings:
        if any(other is member for member in members):
            continue
        paint = _paint_bounds(other)
        if paint is None or _overlap(union, paint):
            return False
    return True


def _reflow(node: dict, direction: str) -> None:
    # Replacing a node's children must not discard the placement assigned to
    # that node by its already-laid-out parent.
    keys = {"position", "left", "top", "right", "bottom", "zIndex", "margin",
            "marginTop", "marginRight", "marginBottom", "marginLeft",
            "alignSelf", "flexGrow", "flexShrink", "flexBasis"}
    previous = {key: value for key, value in node["props"]["style"].items() if key in keys}
    centered_column = direction == "column" and _styles(node).get("justifyContent") == "flex-center"
    _place(node, direction)
    children = node.get("children", [])
    if centered_column and len(children) > 1:
        frame = _content_frame(node)
        first_gap = _frame(children[0])["top"] - frame["top"]
        last_gap = _end(frame, "top") - _end(_frame(children[-1]), "top")
        if first_gap > 0 and abs(first_gap - last_gap) < _EPSILON:
            # Semantic regrouping retains DDS's already-established centered
            # column convention when its outer insets still agree.
            node["props"]["style"]["justifyContent"] = "flex-center"
            node["alignJustify"]["justifyContent"] = "flex-center"
    node["props"]["style"].update(previous)
    node["style"] = deepcopy(node["props"]["style"])


def _place_text_group(node: dict) -> None:
    node["uiType"] = "TextGroup"
    # Semantic rectangles share the rect identity category with ImageText.
    # Only rename our generated geometric group, never an original layer.
    identity = node.get("id", "")
    if (identity.startswith("col_") and node.get("layerId") == identity
            and node.get("eleName") == identity):
        for key in ("id", "layerId", "eleName"):
            node[key] = "rect_" + identity[4:]
    _place(node, "column")
    frame, previous = _frame(node), _frame(node)["top"]
    for child in node["children"]:
        cf, style = _frame(child), child["props"]["style"]
        for key in list(style):
            if key.startswith("margin"):
                del style[key]
        # DDS text groups retain line separation even with space-between.
        _margins(style, top=cf["top"] - previous, left=cf["left"] - frame["left"])
        child["style"] = deepcopy(style)
        previous = _end(cf, "top")


def _text_header(node: dict) -> bool:
    children = node.get("children", [])
    if node.get("type") == "lanhutext":
        return not children
    return (node.get("type") == "lanhublock" and bool(children)
            and all(_text_header(child) for child in children))


def is_multicolumn_text_header(node: dict) -> bool:
    """Recognize equal, disjoint text panels defining several canvas columns.

    A title and subtitle inside one panel do not define separate body columns.
    This distinction is observed across the paired multi-panel canvases.
    """
    children = node.get("children", [])
    if len(children) == 1 and _plain_group(node):
        return is_multicolumn_text_header(children[0])
    if (_styles(node).get("flexDirection") != "row" or len(children) < 2
            or not all(child.get("type") == "lanhublock" and _text_header(child)
                       and _paint_bounds(child) is not None for child in children)):
        return False
    frames = sorted((_frame(child) for child in children), key=lambda frame: frame["left"])
    first = frames[0]
    return (first["width"] > 0 and first["height"] > 0
            and all((frame["top"], frame["width"], frame["height"])
                    == (first["top"], first["width"], first["height"]) for frame in frames)
            and all(_end(left, "left") <= right["left"] for left, right in zip(frames, frames[1:])))


def _unwrap_text_row(node: dict) -> dict | None:
    """Unwrap only a paint-free singleton whose bounds equal its text leaf."""
    if node.get("type") == "lanhutext" and not node.get("children"):
        return node
    children = node.get("children", [])
    if not _plain_group(node) or len(children) != 1:
        return None
    text = _unwrap_text_row(children[0])
    return text if text is not None and _frame(node) == _frame(text) else None


def _extend_ordinary_icon_description(node: dict) -> None:
    """Keep a marked ordinary status icon with its entire text description.

    Initial flat pairing may consume the title before the following detail
    line is considered. Recover the two-line semantic column when the export
    marker and aligned, unobstructed geometry independently support it.
    """
    if _styles(node).get("flexDirection") != "column":
        return
    children = node.get("children", [])
    for index in range(len(children) - 1):
        heading, following = children[index:index + 2]
        members = heading.get("children", [])
        if heading.get("uiType") != "ImageText" or len(members) != 2:
            continue
        icon, title = members
        detail = _unwrap_text_row(following)
        if (not _ordinary_anchor(icon) or title.get("type") != "lanhutext"
                or title.get("children") or detail is None):
            continue
        image_frame, title_frame, detail_frame = _frame(icon), _frame(title), _frame(detail)
        if (image_frame["height"] > title_frame["height"]
                or title_frame["left"] != detail_frame["left"]
                or title_frame["width"] != detail_frame["width"]
                or not 0 <= detail_frame["top"] - _end(title_frame, "top") <= title_frame["height"]
                or not _clear_group([heading, following], children)):
            continue
        title["uiType"] = ""
        text_group = _group([title, detail], "column")
        _place_text_group(text_group)
        pair = _group([icon, text_group], "row", image_text=True)
        _place(pair, "row")
        children[index:index + 2] = [pair]
        _reflow(node, "column")
        break


def _canvas_remainder(root: dict) -> None:
    """Recover the observed page-height body following a separate text header.

    DDS uses an inclusive final pixel for this region. This compatibility
    convention is limited to several disjoint content rows; a single section
    below a title keeps its original page placement.
    """
    children = root.get("children", [])
    if (root.get("type") != "lanhupage" or len(children) < 3
            or _styles(root).get("flexDirection") != "column"
            or not _text_header(children[0]) or is_multicolumn_text_header(children[0])):
        return
    page, header = _frame(root), _frame(children[0])
    frames = [_frame(child) for child in children[1:]]
    if (header["left"] < page["left"] or _end(header, "left") > _end(page, "left")
            or header["top"] < page["top"]
            or any(frame["left"] < header["left"] or _end(frame, "left") > _end(header, "left")
                   or frame["top"] < _end(header, "top") or _end(frame, "top") > _end(page, "top")
                   for frame in frames)
            or any(right["top"] < _end(left, "top") for left, right in zip(frames, frames[1:]))):
        return
    group = _group(children[1:], "column")
    group["rowDims"] = {"left": page["left"], "top": _end(header, "top"),
                        "width": page["width"], "height": _end(page, "top") - _end(header, "top") + 1}
    group["ddsCanvasRemainder"] = True
    _place(group, "column")
    root["children"] = [children[0], group]
    shrink = [_styles(child).get("flexShrink") for child in root["children"]]
    _reflow(root, "column")
    for child, previous in zip(root["children"], shrink):
        if previous is None:
            child["props"]["style"].pop("flexShrink", None)
    # The observed DDS serializer stores the inclusive edge as a positive gap.
    # common.css already fixes flex-shrink to zero for every rendered element.
    group["props"]["style"]["marginBottom"] = 1
    for child in root["children"]:
        child["style"] = deepcopy(child["props"]["style"])


def refine_dds_semantics(root: dict) -> dict:
    """Copy a laid-out DDS tree and restore groups adjacent to ordinary slices.

    The rule is deliberately limited to separate exported square anchors and
    adjacent text-only columns; it does not relabel arbitrary input controls.
    It never reads another schema or any design fixture.
    """
    result = deepcopy(root)

    def images(node):
        if node.get("type") == "lanhuimage" and not node.get("children"):
            frame = _frame(node)
            yield node.get("props", {}).get("src"), frame["width"], frame["height"]
        for child in node.get("children", []):
            yield from images(child)

    image_uses = Counter(images(result))

    def repeated_caption(node):
        # Repeated square-image cards expose a stable description-column role
        # in the paired export. This is an empirical reuse/geometry hypothesis,
        # never a lookup of a particular image, title, or component identity.
        if _styles(node).get("flexDirection") != "row":
            return
        children = node.get("children", [])
        changed = False
        for anchor, texts in zip(children, children[1:]):
            if anchor.get("type") != "lanhuimage" or anchor.get("children") or not _text_column(texts):
                continue
            af, tf = _frame(anchor), _frame(texts)
            key = anchor.get("props", {}).get("src"), af["width"], af["height"]
            if (not key[0] or image_uses[key] < 2 or not 0 < af["width"] == af["height"]
                    or af["top"] != tf["top"] or af["height"] != tf["height"]
                    or not 0 <= tf["left"] - _end(af, "left") <= af["width"] / 2
                    or not _clear_group([anchor, texts], children)):
                continue
            _place_text_group(texts)
            changed = True
        if changed:
            _reflow(node, "row")

    def visit(node: dict) -> None:
        for child in node.get("children", []):
            visit(child)
        _extend_ordinary_icon_description(node)
        repeated_caption(node)
        children = node.get("children", [])
        direction = _styles(node).get("flexDirection")
        if direction == "row":
            for index in range(len(children) - 2):
                anchor, texts, arrow = children[index:index + 3]
                if not _ordinary_anchor(anchor) or not _text_column(texts):
                    continue
                if arrow.get("type") != "lanhuimage" or arrow.get("sourceHasOrdinaryImage"):
                    continue
                af, tf, rf = _frame(anchor), _frame(texts), _frame(arrow)
                if (0 < rf["width"] == rf["height"] <= af["width"]
                        and 0 <= tf["left"] - _end(af, "left") <= af["width"] / 2
                        and 0 <= rf["left"] - _end(tf, "left") <= rf["width"]
                        and abs(_center(af, "top") - _center(tf, "top")) <= 1
                        and abs(_center(rf, "top") - _center(tf, "top")) <= 1
                        and _clear_group([texts, arrow], children)):
                    _place_text_group(texts)
                    pair = _group([texts, arrow], "row", image_text=True)
                    _place(pair, "row")
                    children[index + 1:index + 3] = [pair]
                    _reflow(node, "row")
                    break
        elif direction == "column":
            for index, anchor in enumerate(children):
                if not _ordinary_anchor(anchor):
                    continue
                texts = []
                for following in children[index + 1:]:
                    if following.get("type") != "lanhutext":
                        break
                    texts.append(following)
                if len(texts) < 2:
                    continue
                af = _frame(anchor)
                frames = [_frame(text) for text in texts]
                if (0 <= frames[0]["top"] - _end(af, "top") <= af["height"] / 2
                        and all(abs(_center(frame, "left") - _center(af, "left")) <= 1 for frame in frames)
                        and all(0 <= right["top"] - _end(left, "top") <= min(left["height"], right["height"])
                                for left, right in zip(frames, frames[1:]))
                        and _clear_group(texts, children)):
                    group = _group(texts, "column")
                    _place_text_group(group)
                    children[index + 1:index + 1 + len(texts)] = [group]
                    _reflow(node, "column")
                    break

    visit(result)
    _canvas_remainder(result)
    return result
