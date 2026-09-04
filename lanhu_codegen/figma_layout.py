"""Conservative geometric layout inference for normalized Lanhu DDS nodes.

This reconstructs layout from pixels; it is not Lanhu's unavailable upstream
layout service. Frames are absolute artboard coordinates. Paint boundaries and
ambiguous overlaps survive, while harmless wrappers and separable projections
can be represented using static flex layout. No reference schema is consulted.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
import re
from typing import Callable


_BOX_KEYS = {
    "left", "top", "right", "bottom", "width", "height", "position", "zIndex",
    "boxSizing", "inlineSize", "blockSize", "insetInlineStart", "insetBlockStart",
    "borderRadius", "margin", "marginTop", "marginRight", "marginBottom", "marginLeft",
}
_PLACEMENT_KEYS = {
    "left", "top", "right", "bottom", "position", "zIndex", "inlineSize", "blockSize",
    "insetInlineStart", "insetBlockStart", "margin", "marginTop", "marginRight",
    "marginBottom", "marginLeft", "display", "flexDirection", "justifyContent",
    "alignItems", "alignSelf", "flex", "flexGrow", "flexShrink", "flexBasis",
}
_BLOCKS = {"lanhublock", "lanhupage"}
_EPSILON = 1e-7


def _frame(node: dict) -> dict:
    frame = node.get("rowDims")
    if not isinstance(frame, dict):
        raise ValueError("layout requires a rowDims object on every node")
    for key in ("left", "top", "width", "height"):
        value = frame.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("layout requires finite numeric frame coordinates")
        if key in {"width", "height"} and value < 0:
            raise ValueError("layout requires nonnegative frame sizes")
    return frame


def _end(frame: dict, axis: str) -> float:
    return frame[axis] + frame["width" if axis == "left" else "height"]


def _insets(node: dict) -> dict:
    values = node.get("layoutInsets", {})
    if not isinstance(values, dict) or set(values) - {"top", "right", "bottom", "left"}:
        raise ValueError("layoutInsets must contain CSS border sides")
    result = {}
    for side in ("top", "right", "bottom", "left"):
        value = values.get(side, 0)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError("layoutInsets must contain finite nonnegative numbers")
        result[side] = value
    return result


def _content_frame(node: dict) -> dict:
    frame, insets = _frame(node), _insets(node)
    width = frame["width"] - insets["left"] - insets["right"]
    height = frame["height"] - insets["top"] - insets["bottom"]
    if width < 0 or height < 0:
        raise ValueError("layoutInsets exceed the node's outer dimensions")
    return {"left": frame["left"] + insets["left"], "top": frame["top"] + insets["top"],
            "width": width, "height": height}


def _styles(node: dict) -> dict:
    result = dict(node.get("style") or {})
    result.update((node.get("props") or {}).get("style") or {})
    return result


def _no_effect(key: str, value) -> bool:
    if key == "opacity":
        return value in (1, "1")
    if key in {"overflow", "overflowX", "overflowY"}:
        return value == "visible"
    if key in {"background", "backgroundColor"}:
        return value in {"none", "transparent", "rgba(0,0,0,0)", "rgba(0, 0, 0, 0)"}
    if key in {"transform", "filter", "backdropFilter", "boxShadow", "textShadow", "clipPath", "mask", "maskImage"}:
        return value in (None, "none")
    if key in {"mixBlendMode", "backgroundBlendMode"}:
        return value == "normal"
    return False


def _transparent(node: dict) -> bool:
    """Unknown styles/semantics keep their containing element conservatively."""
    if node.get("type") != "lanhublock" or node.get("uiType"):
        return False
    if any(_insets(node).values()):
        return False
    if any(node.get(key) for key in ("isMask", "clipped", "mask", "condition", "loop", "events")):
        return False
    if node.get("rotation", 0) or node.get("transform") or node.get("opacity", 1) != 1:
        return False
    if node.get("blendMode") not in (None, 0, "normal", "NORMAL", "PASS_THROUGH", "pass-through"):
        return False
    if (node.get("data") or {}).get("value") not in (None, ""):
        return False
    if set(node.get("props") or {}) - {"className", "style"}:
        return False
    for key, value in _styles(node).items():
        if key not in _BOX_KEYS and not _no_effect(key, value):
            return False
    return True


def _union(nodes: list[dict]) -> dict:
    frames = [_frame(node) for node in nodes]
    left = min(frame["left"] for frame in frames)
    top = min(frame["top"] for frame in frames)
    return {"left": left, "top": top,
            "width": max(_end(frame, "left") for frame in frames) - left,
            "height": max(_end(frame, "top") for frame in frames) - top}


def _overlap(a: dict, b: dict) -> bool:
    return all(min(_end(a, axis), _end(b, axis)) - max(a[axis], b[axis]) > _EPSILON
               for axis in ("left", "top"))


def _partition(nodes: list[dict], axis: str) -> list[list[dict]]:
    """Connected interval projections, with touching edges considered separate."""
    ordered = sorted(enumerate(nodes), key=lambda pair: (_frame(pair[1])[axis], pair[0]))
    groups: list[list[dict]] = []
    end = -math.inf
    for _, node in ordered:
        frame = _frame(node)
        if not groups or frame[axis] >= end - _EPSILON:
            groups.append([node])
            end = _end(frame, axis)
        else:
            groups[-1].append(node)
            end = max(end, _end(frame, axis))
    return groups


def _split_css(value: str, *, commas: bool) -> list[str] | None:
    """Split shadow lists/tokens without splitting rgba() or other functions."""
    result, start, depth = [], 0, 0
    for index, char in enumerate(value):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth < 0:
                return None
        elif depth == 0 and (char == "," if commas else char.isspace()):
            if value[start:index].strip():
                result.append(value[start:index].strip())
            start = index + 1
    if depth:
        return None
    if value[start:].strip():
        result.append(value[start:].strip())
    return result


def _shadow_rectangles(value, frame: dict) -> list[dict] | None:
    """Bound ordinary pixel shadows; unresolved units/functions stay unknown.

    Twice the CSS blur radius deliberately overestimates the visible blur
    fringe for ordering decisions. These rectangles are not rasterized pixels.
    """
    if value in (None, "none"):
        return []
    if not isinstance(value, str):
        return None
    shadows = _split_css(value, commas=True)
    if not shadows:
        return None
    result = []
    for shadow in shadows:
        tokens = _split_css(shadow, commas=False)
        if not tokens:
            return None
        lengths, colors, inset = [], 0, False
        for token in tokens:
            number = re.fullmatch(r"([+-]?(?:\d+(?:\.\d*)?|\.\d+))(px)?", token)
            if number and (number[2] or float(number[1]) == 0):
                lengths.append(float(number[1]))
            elif token == "inset" and not inset:
                inset = True
            elif re.fullmatch(r"(?:#[\da-fA-F]{3,8}|[a-zA-Z]+|(?:rgb|hsl)a?\([^()]*\))", token):
                colors += 1
            else:
                return None
        if len(lengths) not in {2, 3, 4} or colors > 1 or not all(math.isfinite(x) for x in lengths):
            return None
        x, y = lengths[:2]
        blur = lengths[2] if len(lengths) > 2 else 0
        spread = lengths[3] if len(lengths) > 3 else 0
        if blur < 0:
            return None
        if inset:
            continue
        expansion = 2 * blur + spread
        width, height = frame["width"] + 2 * expansion, frame["height"] + 2 * expansion
        if width > 0 and height > 0:
            result.append({"left": frame["left"] + x - expansion, "top": frame["top"] + y - expansion,
                           "width": width, "height": height})
    return result


def _rect_union(a: dict, b: dict) -> dict:
    left, top = min(a["left"], b["left"]), min(a["top"], b["top"])
    return {"left": left, "top": top, "width": max(_end(a, "left"), _end(b, "left")) - left,
            "height": max(_end(a, "top"), _end(b, "top")) - top}


def _paint_bounds(node: dict) -> dict | None:
    """Conservative painted rectangle, or None for an unresolved effect.

    A descendant whose ink remains inside its parent's rectangle does not
    enlarge an ancestor's footprint. Overflow clips descendants, whereas an
    element's own outer box shadow still paints outside its border rectangle.
    """
    style = _styles(node)
    if any(key in style and not _no_effect(key, style[key]) for key in
           ("transform", "filter", "backdropFilter", "textShadow")):
        return None
    frame = _frame(node)
    shadows = _shadow_rectangles(style.get("boxShadow"), frame)
    if shadows is None:
        return None
    bounds = dict(frame)
    for shadow in shadows:
        bounds = _rect_union(bounds, shadow)
    for child in node.get("children", []):
        child_bounds = _paint_bounds(child)
        if child_bounds is None:
            return None
        clipped = dict(child_bounds)
        for axis, dimension, overflow in (("left", "width", "overflowX"), ("top", "height", "overflowY")):
            if style.get(overflow, style.get("overflow")) in {"hidden", "clip"}:
                start = max(frame[axis], clipped[axis])
                end = min(_end(frame, axis), _end(clipped, axis))
                clipped[axis], clipped[dimension] = start, max(0, end - start)
        if clipped["width"] > 0 and clipped["height"] > 0:
            bounds = _rect_union(bounds, clipped)
    return bounds


def _paint_extends(node: dict) -> bool:
    bounds = _paint_bounds(node)
    return bounds is None or bounds != _frame(node)


def _simple_image(node: dict) -> bool:
    if node.get("type") != "lanhuimage" or node.get("children"):
        return False
    if not node.get("mergeEligible", True):
        return False
    if set(node.get("props") or {}) - {"className", "style", "src"}:
        return False
    if any(node.get(key) for key in ("condition", "loop", "events")):
        return False
    if any(node.get(key) for key in ("isMask", "clipped", "mask", "rotation", "transform")):
        return False
    if node.get("opacity", 1) != 1 or node.get("blendMode") not in (None, 0, "normal", "NORMAL", "PASS_THROUGH", "pass-through"):
        return False
    # Compositing must not discard independent opacity, transforms, clipping,
    # borders, links or other effects that have not been baked into the bitmap.
    return all(key in _BOX_KEYS or (key == "display" and value == "block") or _no_effect(key, value)
               for key, value in _styles(node).items() if key != "borderRadius") and not _styles(node).get("borderRadius")


def _nearby_icons(a: dict, b: dict) -> bool:
    """A conservative inferred toolbar rule, not a proven official threshold."""
    af, bf = _frame(a), _frame(b)
    size = af["width"]
    return (0 < size <= 32 and size == af["height"] == bf["width"] == bf["height"]
            and af["top"] == bf["top"] and 0 <= bf["left"] - _end(af, "left") <= 1.5 * size)


def _merge_images(nodes: list[dict], composer: Callable | None, parent: dict, *,
                  accept_merge: Callable[[list[dict]], bool] | None = None) -> list[dict]:
    if composer is None:
        return nodes
    result = []
    cursor = 0
    while cursor < len(nodes):
        run = [nodes[cursor]]
        if _simple_image(run[0]):
            while cursor + len(run) < len(nodes):
                candidate = nodes[cursor + len(run)]
                if not _simple_image(candidate):
                    break
                if any(_overlap(_frame(previous), _frame(candidate)) for previous in run) or _nearby_icons(run[-1], candidate):
                    run.append(candidate)
                else:
                    break
        # Nothing else may paint in the new raster's bounding rectangle. This
        # also guards against a later layer between separated toolbar icons.
        bounds = _union(run)
        outside = nodes[:cursor] + nodes[cursor + len(run):]
        if (len(run) > 1 and not any(_overlap(bounds, _frame(other)) for other in outside)
                and (accept_merge is None or accept_merge(run))):
            # Optional image merging must not make a representable design
            # unusable. Importing Pillow is unnecessary without a merge call.
            from .figma_images import FigmaImageCompositionError

            try:
                merged = composer(deepcopy(run))
            except FigmaImageCompositionError as exc:
                warning = {"code": "image_merge_skipped", "layerIds": [node.get("layerId", "") for node in run],
                           "reason": str(exc)}
                warnings = parent.setdefault("layoutWarnings", [])
                if warning not in warnings:
                    warnings.append(warning)
                result.extend(run)
            else:
                if not isinstance(merged, dict) or merged.get("type") != "lanhuimage":
                    raise ValueError("image_composer must return a DDS image node")
                if _frame(merged) != bounds:
                    raise ValueError("image_composer returned incorrect union bounds")
                _clean_style(merged)
                result.append(merged)
        else:
            result.extend(run)
        cursor += len(run)
    return result


def _group(nodes: list[dict], direction: str, *, image_text: bool = False) -> dict:
    frame = _union(nodes)
    prefix = "rect" if image_text else "row" if direction == "row" else "col"
    identity = json.dumps([frame, [node.get("layerId", node.get("id", "")) for node in nodes]], sort_keys=True)
    digest = hashlib.sha256(identity.encode()).hexdigest()[:12]
    name = f"{prefix}_{digest}"
    return {"id": name, "eleName": name, "layerId": name, "rowDims": frame,
            "type": "lanhublock", "componentName": "lanhublock", "data": {"value": ""},
            "uiType": "ImageText" if image_text else "", "uiTypeProb": {}, "alignJustify": {},
            "props": {"style": {"width": frame["width"], "height": frame["height"]}},
            "children": nodes}


def _image_text_pairs(nodes: list[dict], *, accept_image: Callable[[dict], bool] | None = None) -> list[dict]:
    result = []
    consumed: set[int] = set()
    paint_bounds = [_paint_bounds(node) for node in nodes]
    for index, image in enumerate(nodes):
        if index in consumed:
            continue
        af = _frame(image)
        candidates = []
        if (_simple_image(image) and 0 < af["width"] == af["height"] <= 32
                and (accept_image is None or accept_image(image))):
            for other_index, text in enumerate(nodes):
                if other_index <= index or other_index in consumed or text.get("type") != "lanhutext":
                    continue
                bf = _frame(text)
                gap = bf["left"] - _end(af, "left")
                center_delta = abs(af["top"] + af["height"] / 2 - bf["top"] - bf["height"] / 2)
                if 0 <= gap <= af["width"] and af["height"] <= bf["height"] and center_delta <= 1:
                    if paint_bounds[index] is None or paint_bounds[other_index] is None:
                        continue
                    bounds = _rect_union(paint_bounds[index], paint_bounds[other_index])
                    # Grouping moves text next to its icon in painter order.
                    # An intervening layer's shadow/escaped child can cover it
                    # even when that layer's own layout rectangle is distant.
                    if not any(k not in {index, other_index}
                               and (paint is None or _overlap(bounds, paint))
                               for k, paint in enumerate(paint_bounds)):
                        candidates.append((gap, other_index, text))
        if candidates:
            _, other_index, text = min(candidates, key=lambda item: (item[0], item[1]))
            consumed.add(other_index)
            text["uiType"] = "TextGroup"
            group = _group([image, text], "row", image_text=True)
            _place(group, "row")
            result.append(group)
        else:
            result.append(image)
    return result


def _clean_style(node: dict) -> dict:
    style = node.setdefault("props", {}).setdefault("style", {})
    for key in _PLACEMENT_KEYS:
        style.pop(key, None)
    frame = _frame(node)
    style.update(width=frame["width"], height=frame["height"])
    if any(_insets(node).values()):
        style["boxSizing"] = "border-box"
    return style


def _px(value: float) -> str:
    return f"{value:g}px" if value else "0"


def _margins(style: dict, top=0, right=0, bottom=0, left=0) -> None:
    values = [top, right, bottom, left]
    nonzero = [(key, value) for key, value in zip(("Top", "Right", "Bottom", "Left"), values) if abs(value) > _EPSILON]
    if len(nonzero) == 1:
        style["margin" + nonzero[0][0]] = nonzero[0][1]
    elif nonzero:
        style["margin"] = " ".join(_px(value) for value in values)


def _place(node: dict, direction: str | None) -> None:
    """Apply static flex when separable, otherwise preserve absolute geometry."""
    children = node.get("children", [])
    style = _clean_style(node)
    frame = _content_frame(node)
    has_insets = any(_insets(node).values())
    node["alignJustify"] = {}
    if direction is None:
        style["position"] = "relative"
        for index, child in enumerate(children):
            child_style = child["props"]["style"]
            for key in ("margin", "marginTop", "marginRight", "marginBottom", "marginLeft"):
                child_style.pop(key, None)
            cf = _frame(child)
            child_style.update(position="absolute", left=cf["left"] - frame["left"],
                               top=cf["top"] - frame["top"], zIndex=index)
            child["style"] = deepcopy(child_style)
        node["style"] = deepcopy(style)
        return
    style.update(display="flex", flexDirection=direction)
    axis = "left" if direction == "row" else "top"
    main_overflow = any(_frame(child)[axis] < frame[axis] - _EPSILON
                        or _end(_frame(child), axis) > _end(frame, axis) + _EPSILON
                        for child in children)
    first_gap = _frame(children[0])[axis] - frame[axis] if children else 0
    last_gap = _end(frame, axis) - _end(_frame(children[-1]), axis) if children else 0
    gaps = [_frame(current)[axis] - _end(_frame(previous), axis)
            for previous, current in zip(children, children[1:])]
    equal_gaps = all(abs(gap - gaps[0]) < _EPSILON for gap in gaps)
    distribute = len(children) > 1 and abs(first_gap) < _EPSILON and abs(last_gap) < _EPSILON and equal_gaps
    # DDS bordered two-ended controls retain their outer-frame edge margins
    # but distribute the inner gap in the CSS content box. This compatibility
    # convention is explicit; ordinary layoutInsets still preserve source ink.
    if (node.get("ddsBorderOffsets") and direction == "row" and len(children) == 2
            and first_gap >= 0 and abs(first_gap - last_gap) < _EPSILON):
        distribute = True
    if distribute:
        style["justifyContent"] = "space-between"
    elif direction == "row" and len(children) > 1 and first_gap > 0 and abs(first_gap - last_gap) < _EPSILON:
        # Preserve the official serializer's observed literal, although this
        # value itself is ignored by CSS. Pixel margins still fix placement.
        style["justifyContent"] = "flex-center"
    if "justifyContent" in style:
        node["alignJustify"]["justifyContent"] = style["justifyContent"]
    previous = frame[axis]
    for index, child in enumerate(children):
        child_style = child["props"]["style"]
        for key in ("left", "top", "right", "bottom", "zIndex", "margin", "marginTop", "marginRight", "marginBottom", "marginLeft"):
            child_style.pop(key, None)
        if child_style.get("position") == "absolute":
            child_style.pop("position")
        if has_insets or any(_insets(child).values()) or main_overflow:
            # Definite design dimensions must not be compressed by flex's
            # default shrink factor when borders reduce available content or
            # a fixed child intentionally extends past the parent's bounds.
            # Protect every sibling: flex otherwise distributes shrinkage.
            child_style["flexShrink"] = 0
        cf = _frame(child)
        primary = (first_gap if index == 0 else 0) if distribute else cf[axis] - previous
        trailing = last_gap if len(children) > 1 and index == len(children) - 1 else 0
        if direction == "row":
            _margins(child_style, top=cf["top"] - frame["top"], right=trailing, left=primary)
        else:
            _margins(child_style, top=primary, bottom=trailing, left=cf["left"] - frame["left"])
        previous = _end(cf, axis)
        child["style"] = {**deepcopy(child_style), "position": child_style.get("position", "static"),
                          "left": cf["left"], "top": cf["top"]}
    node["style"] = deepcopy(style)


def _has_positioned_descendants(node: dict) -> bool:
    for child in node.get("children", []):
        style = _styles(child)
        if (style.get("position") in {"absolute", "relative", "fixed", "sticky"}
                or style.get("zIndex") not in (None, "auto")
                or _has_positioned_descendants(child)):
            return True
    return False


def _arrange(nodes: list[dict]) -> tuple[list[dict], str | None]:
    if len(nodes) <= 1:
        # A singleton ImageText wrapper retains its semantic horizontal axis.
        return nodes, "row" if nodes and nodes[0].get("uiType") == "ImageText" else "column"
    paint_bounds = [_paint_bounds(node) for node in nodes]
    if any(bounds is None for bounds in paint_bounds):
        return nodes, None
    y_groups, x_groups = _partition(nodes, "top"), _partition(nodes, "left")
    if len(y_groups) > 1:
        groups, direction = y_groups, "column"
    elif len(x_groups) > 1:
        groups, direction = x_groups, "row"
    else:
        return nodes, None
    group_index = {id(member): index for index, members in enumerate(groups) for member in members}
    positioned_descendants = [_has_positioned_descendants(node) for node in nodes]
    for index, before in enumerate(nodes):
        for other_index in range(index + 1, len(nodes)):
            after = nodes[other_index]
            if (_overlap(paint_bounds[index], paint_bounds[other_index])
                    and (group_index[id(before)] > group_index[id(after)]
                         or positioned_descendants[index] or positioned_descendants[other_index])):
                # Preserve overlapping source paint as atomic siblings. Merely
                # keeping DOM order is insufficient when a static flex item's
                # positioned descendants can escape above the next sibling.
                # Absolute siblings receive explicit z-indices in _place.
                return nodes, None
    result = []
    for members in groups:
        if len(members) == 1:
            result.extend(members)
        else:
            # Partition sorting must not change stacking order inside an
            # unresolved overlap cluster.
            identities = {id(member) for member in members}
            members = [member for member in nodes if id(member) in identities]
            arranged, child_direction = _arrange(members)
            group = _group(arranged, child_direction or "column")
            _place(group, child_direction)
            result.append(group)
    return result, direction


def infer_layout(root: dict, *, image_composer: Callable | None = None) -> dict:
    """Return a regrouped copy of a normalized DDS tree.

    ``image_composer(nodes)`` optionally returns one DDS image with the union
    frame, preserving input painter order. Without it images remain separate.
    Every node needs finite absolute ``rowDims``; visual effects must already
    be represented in ``props.style`` (or retained on the node).
    Optional top-level ``layoutInsets`` supplies the rendered CSS border widths
    (top/right/bottom/left). Its rowDims remain the outer border box; child
    positioning uses the smaller content box. Missing sides default to zero.
    ``mergeEligible=False`` excludes an image from inferred raster merging.
    Recoverable composition errors are attached to the parent's layoutWarnings.
    """
    if not isinstance(root, dict) or root.get("type") != "lanhupage":
        raise ValueError("layout root must be a DDS page")
    result = deepcopy(root)

    def flatten(node: dict) -> list[dict]:
        _frame(node)
        _content_frame(node)
        children = node.get("children", [])
        if not isinstance(children, list) or any(not isinstance(child, dict) for child in children):
            raise ValueError("layout children must be DDS objects")
        node["children"] = [descendant for child in children for descendant in flatten(child)]
        return node["children"] if _transparent(node) else [node]

    flatten(result)

    def visit(node: dict) -> None:
        for child in node.get("children", []):
            visit(child)
        if node.get("type") not in _BLOCKS:
            _clean_style(node)
            node["style"] = deepcopy(node["props"]["style"])
            return
        children = _merge_images(node["children"], image_composer, node)
        if node.get("uiType") != "ImageText":
            children = _image_text_pairs(children)
        node["children"], direction = _arrange(children)
        _place(node, direction)

    visit(result)
    result["props"]["style"]["position"] = "relative"
    result["style"] = deepcopy(result["props"]["style"])
    return result
