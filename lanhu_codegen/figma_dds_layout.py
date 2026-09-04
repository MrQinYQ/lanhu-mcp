"""Frame-based layout hypotheses for the Lanhu DDS compatibility pipeline.

This is an independently inferred compatibility mode, not Lanhu's unavailable
upstream layout service. Its partitions use exported layout rectangles rather
than shadow extents, matching the observed DDS output. The separate
``figma_layout.infer_layout`` remains the source-paint-preserving alternative.

Containment, local overlays and one-cell matrix rows are inferred without layer
names, IDs, text contents, class names or access to a reference schema. Original
source IDs only join optional raw metadata such as types and raster rotation.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
import math
import re

from .figma_layout import (
    _BLOCKS, _BOX_KEYS, _EPSILON, _PLACEMENT_KEYS, _clean_style, _content_frame, _end, _frame, _group,
    _margins, _merge_images, _no_effect, _overlap, _paint_bounds,
    _partition, _place, _simple_image, _styles, _transparent, _union,
)
from .figma_dds_pairing import (
    checkbox_layer_ids, compact_source_pairs, contextual_pairing_exclusions, pair_dds_image_text,
    repeated_view_layer_ids,
)
from .figma_dds_images import build_dds_image_merge_policy
from .figma_dds_semantics import is_multicolumn_text_header


def _walk(node: dict):
    yield node
    for child in node.get("children", []):
        yield from _walk(child)


def _validate(root: dict) -> None:
    if not isinstance(root, dict) or root.get("type") != "lanhupage":
        raise ValueError("layout root must be a DDS page")
    for node in _walk(root):
        _frame(node)
        _content_frame(node)
        children = node.get("children", [])
        if not isinstance(children, list) or any(not isinstance(child, dict) for child in children):
            raise ValueError("layout children must be DDS objects")


def _contains(parent: dict, child: dict) -> bool:
    return all(parent[axis] <= child[axis] + _EPSILON
               and _end(parent, axis) >= _end(child, axis) - _EPSILON
               for axis in ("left", "top"))


def _safe_container(node: dict) -> bool:
    if node.get("type") != "lanhublock" or node.get("uiType"):
        return False
    if any(node.get(key) for key in ("clipped", "isMask", "mask", "loop", "condition", "events", "transform", "rotation")):
        return False
    if node.get("opacity", 1) != 1 or node.get("blendMode") not in (None, 0, "normal", "NORMAL", "PASS_THROUGH", "pass-through"):
        return False
    if set(node.get("props") or {}) - {"className", "style"}:
        return False
    style = _styles(node)
    return all(key not in style or _no_effect(key, style[key]) for key in (
        "overflow", "overflowX", "overflowY", "opacity", "clipPath", "mask", "maskImage",
        "filter", "backdropFilter", "transform", "mixBlendMode",
    ))


def _painted_cell(node: dict) -> bool:
    if node.get("type") != "lanhublock":
        return False
    style = _styles(node)
    return (any(style.get(key) and not _no_effect(key, style[key]) for key in ("background", "backgroundColor"))
            or any(style.get(key) for key in ("border", "borderWidth", "borderTopWidth", "borderRightWidth", "borderBottomWidth", "borderLeftWidth")))


def _column_cells(children: list[dict]) -> bool:
    if len(children) < 2 or not all(_painted_cell(child) for child in children):
        return False
    frames = [_frame(child) for child in children]
    return (frames[0]["width"] > 0 and all(frame["height"] > 0 and frame["left"] == frames[0]["left"]
                                          and frame["width"] == frames[0]["width"] for frame in frames)
            and all(abs(_end(before, "top") - after["top"]) < _EPSILON for before, after in zip(frames, frames[1:])))


def _lift_overflow_columns(root: dict, column_cohorts: list[list[dict]]) -> dict[int, list[dict]]:
    """Lift a matrix's crossing edge column once, preserving its paint panel.

    Cohorts originate in harmless source column wrappers. Every crossing cell
    also needs an in-panel neighbor with the same row band and a touching edge;
    a vertical stack of unrelated decorations does not establish a matrix.
    Plans use the original retained parents, so a one-pixel overshoot of the
    receiving ancestor cannot recursively promote the same column again.
    """
    parents = {id(child): node for node in _walk(root) for child in node.get("children", [])}
    plans, seen, claimed = [], set(), set()
    # Nested harmless wrappers can describe both a prefix and the full column.
    # Prefer the largest valid cohort and never render a claimed cell twice.
    for cells in sorted(column_cohorts, key=len, reverse=True):
        identity = tuple(id(cell) for cell in cells)
        if identity in seen or any(cell_id in claimed for cell_id in identity):
            continue
        seen.add(identity)
        panel = parents.get(id(cells[0]))
        if (panel is None or not _safe_container(panel) or not _painted_cell(panel)
                or any(parents.get(id(cell)) is not panel for cell in cells)):
            continue
        target = parents.get(id(panel))
        if target is None or target.get("type") not in _BLOCKS:
            continue
        frame, union = _frame(panel), _union(cells)
        if union["top"] < frame["top"] or _end(union, "top") > _end(frame, "top"):
            continue
        crossing_right = frame["left"] <= union["left"] < _end(frame, "left") < _end(union, "left")
        crossing_left = union["left"] < frame["left"] < _end(union, "left") <= _end(frame, "left")
        if not (crossing_right or crossing_left):
            continue
        neighbors = []
        for cell in cells:
            cf = _frame(cell)
            matches = [other for other in panel["children"] if other not in cells and _painted_cell(other)
                       and _contains(frame, _frame(other)) and _frame(other)["top"] == cf["top"]
                       and _frame(other)["height"] == cf["height"]
                       and (abs(_end(_frame(other), "left") - cf["left"]) < _EPSILON if crossing_right
                            else abs(_frame(other)["left"] - _end(cf, "left")) < _EPSILON)]
            if len(matches) != 1:
                break
            neighbors.extend(matches)
        if len(neighbors) == len(cells) and _column_cells(neighbors):
            plans.append((cells, panel, target))
            claimed.update(identity)
    external_overlays: dict[int, list[dict]] = {}
    for cells, panel, target in plans:
        panel["children"] = [child for child in panel["children"] if child not in cells]
        group = _group(cells, "column")
        target["children"].insert(target["children"].index(panel), group)
        overlays = external_overlays.setdefault(id(target), [])
        if not any(overlay is panel for overlay in overlays):
            overlays.append(panel)
    return external_overlays


def _attach_external_overlays(node: dict, overlays: list[dict], original_nodes: set[str]) -> None:
    for overlay in overlays:
        candidates = [candidate for candidate in _walk(node)
                      if candidate.get("type") in _BLOCKS and (candidate is node or candidate.get("layerId") not in original_nodes)
                      and not candidate.get("uiType") and _contains(_frame(candidate), _frame(overlay))]
        target = min(candidates, key=lambda candidate: _frame(candidate)["width"] * _frame(candidate)["height"]) if candidates else node
        target["props"]["style"]["position"] = "relative"
        style, frame, parent_frame = overlay["props"]["style"], _frame(overlay), _content_frame(target)
        # Keep the panel's own flex layout; only replace its placement in the
        # surrounding flow. It intentionally paints after the promoted column.
        for key in ("left", "top", "right", "bottom", "position", "zIndex", "flexShrink",
                    "margin", "marginTop", "marginRight", "marginBottom", "marginLeft"):
            style.pop(key, None)
        style.update(position="absolute", left=frame["left"] - parent_frame["left"], top=frame["top"] - parent_frame["top"])
        overlay["style"] = deepcopy(style)
        target["children"].append(overlay)
        target["style"] = deepcopy(target["props"]["style"])


def _attach_terminal_backdrops(root: dict, source_nodes: Mapping) -> dict[int, list[dict]]:
    """Recognize a source frame's terminal alpha backdrop and contained dialog.

    A translucent fill is not an opacity scope. Only a full-size, effect-free
    source shape immediately followed by a contained painted container is
    eligible. A backdrop crossing its source frame moves one retained level,
    using the original parent map rather than recursively lifting it again.
    """
    parents = {id(child): node for node in _walk(root) for child in node.get("children", [])}
    plans = []
    for parent in list(_walk(root)):
        children = parent.get("children", [])
        if len(children) < 3 or not _safe_container(parent):
            continue
        backdrop, dialog = children[-2:]
        raw = source_nodes.get(backdrop.get("layerId"), {})
        if (not isinstance(raw, Mapping) or raw.get("type") != "shapeLayer"
                or backdrop.get("children") or not _safe_container(backdrop)
                or not _safe_container(dialog) or not _painted_cell(dialog)):
            continue
        alpha = re.fullmatch(r"rgba\(\s*[\d.]+\s*,\s*[\d.]+\s*,\s*[\d.]+\s*,\s*([\d.]+)\s*\)",
                             str(_styles(backdrop).get("backgroundColor", "")))
        if alpha is None or not 0 < float(alpha.group(1)) < 1:
            continue
        pf, bf = _frame(parent), _frame(backdrop)
        if (any(abs(pf[key] - bf[key]) > _EPSILON for key in ("width", "height"))
                or not _overlap(pf, bf) or _paint_bounds(backdrop) != bf):
            continue
        paint = _paint_bounds(dialog)
        if paint is None or not _contains(_content_frame(backdrop), paint):
            continue
        target = parent if _contains(pf, bf) else parents.get(id(parent))
        if target is None or (target.get("type") != "lanhupage" and not _safe_container(target)):
            continue
        if target is not parent:
            # Promotion appends the overlay after the receiving parent's flow.
            # It may not jump above later source siblings that paint into it.
            # Plan this before either moving the backdrop or adopting dialog.
            following = target["children"][target["children"].index(parent) + 1:]
            following_bounds = [_paint_bounds(sibling) for sibling in following]
            if any(bound is None or _overlap(bf, bound) for bound in following_bounds):
                continue
        plans.append((parent, backdrop, dialog, target))
    overlays: dict[int, list[dict]] = {}
    for parent, backdrop, dialog, target in plans:
        parent["children"].remove(dialog)
        backdrop["children"] = [dialog]
        if target is not parent:
            parent["children"].remove(backdrop)
            target["children"].append(backdrop)
        overlays.setdefault(id(target), []).append(backdrop)
    return overlays


def _lift_crossing_row_labels(root: dict) -> dict[int, list[dict]]:
    """Promote a terminal text crossing a cell into its adjacent matrix cell.

    The source cell must have a separable, contained horizontal prefix and an
    immediately touching cell covering the same label row. An intervening painted
    object, inherited effects, or an unrelated overflow is not a matrix label.
    """
    parents = {id(child): node for node in _walk(root) for child in node.get("children", [])}
    plans = []
    for cell in list(_walk(root)):
        children = cell.get("children", [])
        target = parents.get(id(cell))
        if (len(children) < 2 or not _safe_container(cell) or not _painted_cell(cell)
                or target is None or not _safe_container(target)):
            continue
        label = children[-1]
        if label.get("type") != "lanhutext" or label.get("children"):
            continue
        cf, lf = _frame(cell), _frame(label)
        if not (cf["left"] <= lf["left"] < _end(cf, "left") < _end(lf, "left")
                and cf["top"] <= lf["top"] and _end(lf, "top") <= _end(cf, "top")):
            continue
        bounds = [_paint_bounds(child) for child in children]
        if (any(bound is None for bound in bounds) or not _contains(_content_frame(target), bounds[-1])
                or any(not _contains(_content_frame(cell), bound) for bound in bounds[:-1])
                or any(_end(_frame(before), "left") > _frame(after)["left"]
                       for before, after in zip(children, children[1:]))
                or len(_partition(children, "top")) != 1):
            continue
        neighbors = [other for other in target["children"] if other is not cell and _painted_cell(other)
                     and _frame(other)["top"] == cf["top"] and _end(_frame(other), "top") >= _end(lf, "top")
                     and abs(_frame(other)["left"] - _end(cf, "left")) < _EPSILON]
        if len(neighbors) != 1:
            continue
        others = [_paint_bounds(other) for other in target["children"] if other is not cell and other is not neighbors[0]]
        if any(bound is None or _overlap(bounds[-1], bound) for bound in others):
            continue
        plans.append((cell, label, target))
    lifted: dict[int, list[dict]] = {}
    for cell, label, target in plans:
        cell["children"].remove(label)
        target["children"].insert(target["children"].index(cell) + 1, label)
        lifted.setdefault(id(target), []).append(label)
    return lifted


def _attach_inline_labels(node: dict, labels: list[dict], original_nodes: set[str]) -> None:
    def geometry_wrappers(parent: dict):
        yield parent
        for child in parent.get("children", []):
            # A synthetic row nested inside an original sibling still belongs
            # to that sibling's paint/effect scope. Do not cross that boundary.
            if child.get("layerId") not in original_nodes and _safe_container(child):
                yield from geometry_wrappers(child)

    for label in labels:
        candidates = [candidate for candidate in geometry_wrappers(node)
                      if _styles(candidate).get("flexDirection") == "row" and not candidate.get("uiType")
                      and _contains(_frame(candidate), _frame(label))]
        if not candidates:
            # An independent unknown layout effect can still prevent a row;
            # retain the promoted label's known geometry without losing it.
            style = _clean_style(label)
            frame, parent = _frame(label), _content_frame(node)
            style.update(position="absolute", left=frame["left"] - parent["left"], top=frame["top"] - parent["top"])
            label["style"] = deepcopy(style)
            node["props"]["style"]["position"] = "relative"
            node["children"].append(label)
            node["style"] = deepcopy(node["props"]["style"])
            continue
        target = min(candidates, key=lambda candidate: _frame(candidate)["width"] * _frame(candidate)["height"])
        # Top-level ``style`` also carries DDS bookkeeping such as global
        # coordinates and position=static. Only CSS props belong back in CSS.
        outer_style = deepcopy(target.get("props", {}).get("style", {}))
        target["children"].append(label)
        target["children"].sort(key=lambda child: _frame(child)["left"])
        _place_dds(target, "row")
        # Placing the row's contents must not clear its placement in its parent.
        for key in ("margin", "marginTop", "marginRight", "marginBottom", "marginLeft", "position", "left", "top",
                    "right", "bottom", "zIndex", "alignSelf", "flex", "flexGrow", "flexShrink", "flexBasis",
                    "inlineSize", "blockSize", "insetInlineStart", "insetBlockStart"):
            if key in outer_style:
                target["props"]["style"][key] = outer_style[key]
        target["style"] = deepcopy(target["props"]["style"])


def _reparent_contained_images(root: dict, *, include_envelope_projections: bool = False,
                               source_nodes: Mapping | None = None) -> set[int]:
    """Attach safe late image or explicitly projected leaves to a container."""
    moved: set[int] = set()
    nodes = list(_walk(root))
    order = {id(node): index for index, node in enumerate(nodes)}
    parents = {id(child): node for node in nodes for child in node.get("children", [])}
    source_nodes = source_nodes or {}
    raw_parents = {child.get("id"): raw.get("id") for raw in source_nodes.values()
                   for child in raw.get("layers", []) if isinstance(child, Mapping)}
    for image in nodes:
        envelope = (include_envelope_projections and image.get("ddsRectEnvelopeProjection") is True
                    and not image.get("children") and _safe_container(image)
                    and (image.get("data") or {}).get("value") in (None, ""))
        shape_text = image.get("type") == "lanhutext" and not image.get("children") and bool(source_nodes)
        if not (_simple_image(image) or envelope or shape_text):
            continue
        leaf_bounds = _paint_bounds(image)
        if leaf_bounds is None:
            continue
        parent = parents.get(id(image))
        if parent is None:
            continue
        candidates = []
        for candidate in _walk(parent):
            if candidate is parent or not _safe_container(candidate):
                continue
            if shape_text:
                # A transparent rounded background and its text originate in
                # the same source component. Its explicit DDS marker avoids
                # treating arbitrary containing shapes as semantic text boxes.
                if candidate.get("ddsTransparentRectProjection") is not True or candidate.get("children"):
                    continue
                component = raw_parents.get(candidate.get("layerId"))
                ancestor_id = raw_parents.get(image.get("layerId"))
                visited = set()
                while ancestor_id is not None and ancestor_id != component and ancestor_id not in visited:
                    visited.add(ancestor_id)
                    ancestor_id = raw_parents.get(ancestor_id)
                if component is None or ancestor_id != component:
                    continue
            if not _contains(_content_frame(candidate), leaf_bounds):
                continue
            # Every newly entered ancestor must be free of inherited clipping,
            # opacity, transforms and behavior, not just the final container.
            ancestor = parents.get(id(candidate))
            while ancestor is not None and ancestor is not parent and _safe_container(ancestor):
                ancestor = parents.get(id(ancestor))
            if ancestor is not parent:
                continue
            descendants = list(_walk(candidate))
            last = max(order[id(node)] for node in descendants)
            if last >= order[id(image)]:
                continue
            # Entering an earlier container must not jump below intervening
            # paint. Unlike row partitioning, this move crosses a paint scope.
            frame = _frame(candidate)
            candidates.append((frame["width"] * frame["height"], candidate, last))
        candidates.sort(key=lambda pair: pair[0])
        if candidates and (len(candidates) == 1 or candidates[0][0] < candidates[1][0]):
            _, target, last = candidates[0]
            intervening = [node for node in nodes if last < order[id(node)] < order[id(image)]]
            bounds = [_paint_bounds(node) for node in intervening]
            if any(bound is None or _overlap(leaf_bounds, bound) for bound in bounds):
                continue
            parent["children"].remove(image)
            target["children"].append(image)
            parents[id(image)] = target
            if not shape_text:
                moved.add(id(image))
    return moved


def _lift_fully_outside_children(root: dict) -> None:
    """Lift wholly detached contents one safe retained level, in source order."""
    nodes = list(_walk(root))
    parents = {id(child): node for node in nodes for child in node.get("children", [])}
    plans = []
    for parent in nodes:
        target = parents.get(id(parent))
        if (target is None or not _safe_container(parent)
                or (target.get("type") != "lanhupage" and not _safe_container(target))):
            continue
        moving = []
        children = parent.get("children", [])
        for index, child in enumerate(children):
            frame, paint = _frame(child), _paint_bounds(child)
            if (frame["width"] <= 0 or frame["height"] <= 0 or _overlap(_frame(parent), frame)
                    or paint is None or not _contains(_content_frame(target), paint)):
                continue
            following = [_paint_bounds(later) for later in children[index + 1:]]
            if any(bound is None or _overlap(paint, bound) for bound in following):
                continue
            moving.append(child)
        if moving:
            plans.append((parent, target, moving))
    # Plans use the initial ancestry, preventing repeated upward promotion.
    # Reversed traversal also leaves nested plans' original parent reachable.
    for parent, target, moving in reversed(plans):
        parent["children"] = [child for child in parent["children"] if child not in moving]
        offset = target["children"].index(parent) + 1
        target["children"][offset:offset] = moving


def _adopt_bottom_bands(root: dict) -> None:
    """Attach a same-bottom band with symmetric overflow to its content panel."""
    for parent in list(_walk(root)):
        if not _safe_container(parent):
            continue
        children = list(parent.get("children", []))
        plans = []
        for index, band in enumerate(children):
            if not _safe_container(band) or not _painted_cell(band) or not band.get("children"):
                continue
            frame, paint = _frame(band), _paint_bounds(band)
            if paint is None or not _contains(_content_frame(parent), paint):
                continue
            matches = []
            for target_index, panel in enumerate(children[:index]):
                if not _safe_container(panel) or not _painted_cell(panel) or not panel.get("children"):
                    continue
                pf = _frame(panel)
                left, right = pf["left"] - frame["left"], _end(frame, "left") - _end(pf, "left")
                if (left <= 0 or abs(left - right) > _EPSILON or pf["width"] <= frame["width"] / 2
                        or pf["top"] >= frame["top"] or abs(_end(pf, "top") - _end(frame, "top")) > _EPSILON
                        or not _contains(_frame(parent), pf)):
                    continue
                intervening = [_paint_bounds(item) for item in children[target_index + 1:index]]
                if any(bound is None or _overlap(paint, bound) for bound in intervening):
                    continue
                matches.append(panel)
            if len(matches) == 1:
                plans.append((band, matches[0]))
        for band, panel in plans:
            parent["children"].remove(band)
            panel["children"].append(band)


def _promote_crossing_shadow_overlays(root: dict, trailing_overlays: Mapping | None = None) -> set[str]:
    """Move crossing shadowed popups once without crossing later source paint."""
    nodes = list(_walk(root))
    parents = {id(child): node for node in nodes for child in node.get("children", [])}
    trailing_overlays = trailing_overlays or {}
    plans = []
    for parent in nodes:
        target = parents.get(id(parent))
        if (target is None or not _safe_container(parent)
                or (target.get("type") != "lanhupage" and not _safe_container(target))):
            continue
        for index, child in enumerate(parent.get("children", [])):
            shadow = _styles(child).get("boxShadow")
            if (not _safe_container(child) or not child.get("children") or not shadow
                    or _no_effect("boxShadow", shadow)):
                continue
            frame, paint = _frame(child), _paint_bounds(child)
            if (paint is None or _contains(_frame(parent), frame) or not _overlap(_frame(parent), frame)
                    or not _contains(_content_frame(target), frame)):
                continue
            following = [_paint_bounds(later) for later in parent["children"][index + 1:]]
            if any(bound is None or _overlap(paint, bound) for bound in following):
                continue
            after_parent = target["children"][target["children"].index(parent) + 1:]
            # Existing terminal backdrops remain after local overlays. Every
            # other later target sibling would be crossed when this popup is
            # positioned after target flow, and must therefore be disjoint.
            following = [_paint_bounds(later) for later in after_parent
                         if later not in trailing_overlays.get(id(target), [])]
            if any(bound is None or _overlap(paint, bound) for bound in following):
                continue
            plans.append((parent, target, child))
    promoted = set()
    for parent, target, child in reversed(plans):
        parent["children"].remove(child)
        target["children"].insert(target["children"].index(parent) + 1, child)
        promoted.add(child["layerId"])
    return promoted


def _attach_pointer_popovers(root: dict, source_nodes: Mapping, excluded: set[str]) -> set[str]:
    """Use an exported terminal pointer to locate a popup's original cell."""
    nodes = list(_walk(root))
    parents = {id(child): node for node in nodes for child in node.get("children", [])}
    order = {id(node): index for index, node in enumerate(nodes)}
    adopted = set()
    for popup in nodes:
        children = popup.get("children", [])
        shadow = _styles(popup).get("boxShadow")
        if (popup.get("layerId") in excluded or not _safe_container(popup) or len(children) != 2
                or not shadow or _no_effect("boxShadow", shadow)):
            continue
        body, pointer = children
        raw = source_nodes.get(pointer.get("layerId"), {})
        source_frame = raw.get("frame", {})
        widths = [source_frame.get(key) for key in ("width", "height")]
        if (not _painted_cell(body) or not _safe_container(body) or not _simple_image(pointer)
                or raw.get("hasExportDDSImage") is not True
                or not all(isinstance(value, (int, float)) and not isinstance(value, bool)
                           and math.isfinite(value) and value > 0 for value in widths)
                or min(widths) > 1):
            continue
        bf, pf, frame, paint = _frame(body), _frame(pointer), _frame(popup), _paint_bounds(popup)
        if (pf["top"] < _end(bf, "top") or _end(pf, "top") != _end(frame, "top")
                or not bf["left"] <= pf["left"] <= _end(bf, "left") or paint is None):
            continue
        parent = parents.get(id(popup))
        if parent is None or not _contains(_content_frame(parent), paint):
            continue
        candidates = []
        for candidate in _walk(parent):
            if candidate is parent or not _safe_container(candidate) or not _painted_cell(candidate):
                continue
            if not _contains(_content_frame(candidate), pf):
                continue
            last = max(order[id(node)] for node in _walk(candidate))
            if last >= order[id(popup)]:
                continue
            ancestor = parents.get(id(candidate))
            while (ancestor is not None and ancestor is not parent and _safe_container(ancestor)
                   and _contains(_content_frame(ancestor), paint)):
                ancestor = parents.get(id(ancestor))
            if ancestor is not parent:
                continue
            cf = _frame(candidate)
            candidates.append((cf["width"] * cf["height"], candidate, last))
        candidates.sort(key=lambda item: item[0])
        if not candidates or (len(candidates) > 1 and candidates[0][0] == candidates[1][0]):
            continue
        _, target, last = candidates[0]
        crossed = [_paint_bounds(node) for node in nodes if last < order[id(node)] < order[id(popup)]]
        if any(bound is None or _overlap(paint, bound) for bound in crossed):
            continue
        parent["children"].remove(popup)
        target["children"].append(popup)
        parents[id(popup)] = target
        adopted.add(popup["layerId"])
    return adopted


def _attach_cursor_menus(root: dict, source_nodes: Mapping,
                         forced_overlays: set[str] | None = None) -> set[str]:
    """Associate a shadow menu and its later cursor with a common control.

    A crossed overlapping subtree must be provably static. The new positioned
    control and menu still paint after it in CSS's positioned phase. Unknown
    effects, escaped descendants and positioned clusters cannot use this rule.
    """
    attached = set()

    def static_tree(node: dict) -> bool:
        if (node.get("ddsRotatedHairlineProjection") is True
                or node.get("layerId") in (forced_overlays or set()) | attached):
            # These layers become positioned even without a geometric overlap;
            # a containing sibling can consequently enter the positioned paint
            # phase after the adopted menu. Frame separation cannot prove it
            # remains a static subtree.
            return False
        bound = _paint_bounds(node)
        if bound is None or not _contains(_frame(node), bound):
            return False
        if node.get("type") == "lanhublock" and not _safe_container(node):
            return False
        if any(_styles(node).get(key) and not _no_effect(key, _styles(node)[key])
               for key in ("boxShadow", "opacity", "transform", "filter", "isolation", "mixBlendMode")):
            return False
        children = node.get("children", [])
        if any(_overlap(_frame(a), _frame(b)) for i, a in enumerate(children) for b in children[i + 1:]):
            return False
        if children and _arrange_frames(deepcopy(children), source_nodes)[1] is None:
            return False
        return all(static_tree(child) for child in children)

    for parent in list(_walk(root)):
        if parent.get("type") != "lanhupage" and not _safe_container(parent):
            continue
        siblings = list(parent.get("children", []))
        for menu_index, menu in enumerate(siblings):
            mf, menu_paint = _frame(menu), _paint_bounds(menu)
            if (not _safe_container(menu) or not menu.get("children") or not _painted_cell(menu)
                    or not _styles(menu).get("boxShadow") or menu_paint is None
                    or not _contains(_content_frame(parent), menu_paint)):
                continue
            cursors = [cursor for cursor in siblings[menu_index + 1:]
                       if _simple_image(cursor) and source_nodes.get(cursor.get("layerId"), {}).get("hasExportDDSImage") is True
                       and _overlap(_frame(cursor), mf)]
            if len(cursors) != 1:
                continue
            cursor = cursors[0]
            all_nodes = [descendant for sibling in siblings for descendant in _walk(sibling)]
            order = {id(item): i for i, item in enumerate(all_nodes)}
            parents = {id(child): item for item in all_nodes for child in item.get("children", [])}
            candidates = []
            for target in all_nodes[:order[id(menu)]]:
                tf = _frame(target)
                if (not _safe_container(target) or not _painted_cell(target) or not target.get("children")
                        or not _contains(tf, _frame(cursor)) or _contains(tf, mf)
                        or not (tf["left"] <= mf["left"] < _end(tf, "left")
                                and tf["top"] <= mf["top"] < _end(tf, "top"))
                        or not static_tree(target)):
                    continue
                ancestor, safe = parents.get(id(target), parent), True
                while ancestor is not parent:
                    if not _safe_container(ancestor) or not _contains(_content_frame(ancestor), menu_paint):
                        safe = False
                        break
                    ancestor = parents.get(id(ancestor), parent)
                if safe:
                    candidates.append(target)
            candidates.sort(key=lambda target: _frame(target)["width"] * _frame(target)["height"])
            if not candidates:
                continue
            target = candidates[0]
            if (len(candidates) > 1 and _frame(target)["width"] * _frame(target)["height"]
                    == _frame(candidates[1])["width"] * _frame(candidates[1])["height"]):
                continue
            last_target = max(order[id(item)] for item in _walk(target))
            menu_ids = {id(item) for item in _walk(menu)}
            crossed = [item for item in all_nodes[last_target + 1:order[id(cursor)]]
                       if id(item) not in menu_ids
                       and (id(parents.get(id(item))) not in order
                            or order[id(parents[id(item)])] <= last_target)]
            valid = True
            for other in crossed:
                bound = _paint_bounds(other)
                if bound is None:
                    valid = False
                    break
                if _overlap(menu_paint, bound) or _overlap(_frame(cursor), bound):
                    if (_overlap(_frame(target), bound) or not static_tree(other)
                            or order[id(other)] > order[id(menu)]):
                        valid = False
                        break
            if not valid or any(item not in parent.get("children", []) for item in (menu, cursor)):
                continue
            parent["children"] = [item for item in parent["children"] if item is not menu and item is not cursor]
            target["children"].extend([menu, cursor])
            attached.update((menu.get("layerId"), cursor.get("layerId")))
    return attached


def reparent_contained_images(root: dict) -> dict:
    """Return a copy with unambiguously contained late image leaves attached.

    This helper preserves existing wrappers and styles. ``infer_dds_layout``
    additionally removes harmless wrappers before applying the same operation.
    """
    _validate(root)
    result = deepcopy(root)
    _reparent_contained_images(result)
    return result


def _attach_empty_shape_cohorts(root: dict, cohorts: list[list[dict]]) -> set[str]:
    """Adopt source-linked overlays into an unambiguous empty DDS anchor.

    The center selects an anchor only; full paint bounds must fit every newly
    entered original ancestor. The anchor itself has no clipping or paint and
    its adopted children retain absolute geometry, including negative offsets.
    """
    nodes = list(_walk(root))
    order = {id(node): index for index, node in enumerate(nodes)}
    parents = {id(child): node for node in nodes for child in node.get("children", [])}
    adopted, claimed = set(), set()
    for members in sorted(cohorts, key=len, reverse=True):
        if len(members) < 2 or any(id(member) in claimed for member in members):
            continue
        parent = parents.get(id(members[0]))
        if parent is None or any(parents.get(id(member)) is not parent for member in members):
            continue
        paints = [_paint_bounds(member) for member in members]
        if any(paint is None for paint in paints):
            continue
        paint_union = _union([{"rowDims": paint} for paint in paints])
        frame = _union(members)
        center = {"left": frame["left"] + frame["width"] / 2,
                  "top": frame["top"] + frame["height"] / 2, "width": 0, "height": 0}
        first = min(order[id(member)] for member in members)
        candidates = []
        for anchor in _walk(parent):
            if (anchor.get("ddsEmptyShapeProjection") is not True or anchor.get("children")
                    or not _safe_container(anchor) or order[id(anchor)] >= first
                    or not _contains(_frame(anchor), center)):
                continue
            ancestor = parents.get(id(anchor))
            while (ancestor is not None and ancestor is not parent and _safe_container(ancestor)
                   and _contains(_content_frame(ancestor), paint_union)):
                ancestor = parents.get(id(ancestor))
            if ancestor is not parent:
                continue
            candidates.append(anchor)
        # Competing empty frames have no source identity tying this cohort to
        # either one, even when one candidate happens to have smaller area.
        if len(candidates) != 1:
            continue
        anchor = candidates[0]
        intervening = [_paint_bounds(node) for node in nodes if order[id(anchor)] < order[id(node)] < first]
        if any(paint is None or _overlap(paint_union, paint) for paint in intervening):
            continue
        for member in members:
            parent["children"].remove(member)
            parents[id(member)] = anchor
        anchor["children"] = list(members)
        claimed.update(id(member) for member in members)
        adopted.add(anchor["layerId"])
    return adopted


def _place_dds(node: dict, direction: str | None) -> None:
    """Apply the observed DDS spacing conventions after ordinary placement.

    DDS keeps explicit gaps on distributed columns and rows with three or
    more children. Two-ended text/image controls distribute only their
    interior space, retaining symmetric outer insets. The literal flex-center
    is emitted on either axis; the explicit margins carry its geometry.
    """
    _place(node, direction)
    children = node.get("children", [])
    if direction is None or len(children) < 2:
        return
    frame = _content_frame(node)
    axis = "left" if direction == "row" else "top"
    first_gap = _frame(children[0])[axis] - frame[axis]
    last_gap = _end(frame, axis) - _end(_frame(children[-1]), axis)
    symmetric_insets = first_gap > 0 and abs(first_gap - last_gap) < _EPSILON
    overflow = any(_frame(child)[axis] < frame[axis] or _end(_frame(child), axis) > _end(frame, axis)
                   for child in children)
    if overflow and not any(any(item.get("layoutInsets", {}).values()) for item in [node, *children]):
        # The official common stylesheet already fixes every element's shrink
        # factor. Source layout keeps its explicit protection in its own path.
        for child in children:
            child["props"]["style"].pop("flexShrink", None)
    if last_gap < 0:
        # DDS serializes the final outer-edge distance as a positive gap even
        # when a fixed child extends past the container. Interior overlaps
        # retain their signed margins.
        last_gap = -last_gap
        child, cf = children[-1], _frame(children[-1])
        primary = cf[axis] - _end(_frame(children[-2]), axis)
        if node["props"]["style"].get("justifyContent") == "space-between":
            primary = 0
        child_style = child["props"]["style"]
        for key in ("margin", "marginTop", "marginRight", "marginBottom", "marginLeft"):
            child_style.pop(key, None)
        if direction == "column":
            _margins(child_style, top=primary, bottom=last_gap, left=cf["left"] - frame["left"])
        else:
            _margins(child_style, top=cf["top"] - frame["top"], right=last_gap, left=primary)
    for child in children:
        child["style"] = deepcopy(child["props"]["style"])
    style = node["props"]["style"]
    background = any(style.get(key) and not _no_effect(key, style[key])
                     for key in ("background", "backgroundColor"))

    def image_end(child: dict) -> bool:
        if child.get("type") == "lanhuimage" and not child.get("children"):
            return True
        contents = child.get("children", [])
        if not _safe_container(child) or len(contents) != 1 or not _simple_image(contents[0]):
            return False
        paint = _paint_bounds(contents[0])
        return paint is not None and _contains(_content_frame(child), paint)

    opposite_ends = (len(children) == 2 and (
        (children[0].get("type") == "lanhutext" and image_end(children[1]))
        or (image_end(children[0]) and children[1].get("type") == "lanhutext")))
    two_ended_control = (direction == "row" and symmetric_insets and background
                         and opposite_ends
                         and _end(_frame(children[0]), axis) <= _frame(children[1])[axis])
    illustrated_caption = (direction == "column" and not overflow and len(children) == 2 and _simple_image(children[0])
                           and children[1].get("type") == "lanhutext" and not children[1].get("children")
                           and _styles(children[1]).get("textAlign") == "center"
                           and abs((_frame(children[0])["left"] + _frame(children[0])["width"] / 2)
                                   - (_frame(children[1])["left"] + _frame(children[1])["width"] / 2)) < _EPSILON
                           and first_gap > 0 and last_gap > 0 and abs(first_gap - last_gap) == 1)
    if two_ended_control:
        style["justifyContent"] = "space-between"
    elif direction == "column" and (symmetric_insets or illustrated_caption):
        style["justifyContent"] = "flex-center"
    elif first_gap > 0 and last_gap == 0:
        style["justifyContent"] = "flex-end"
    if "justifyContent" in style:
        node["alignJustify"]["justifyContent"] = style["justifyContent"]
    # Column gaps are explicit even with only two children. This holds across
    # text, painted panels and mixed collections; horizontal two-ended controls
    # retain the distinct space-between convention above.
    retain_distributed_gaps = (style.get("justifyContent") == "space-between"
                               and (len(children) >= 3 or direction == "column"))
    if two_ended_control or retain_distributed_gaps:
        previous = frame[axis]
        for index, child in enumerate(children):
            child_style, child_frame = child["props"]["style"], _frame(child)
            for key in ("margin", "marginTop", "marginRight", "marginBottom", "marginLeft"):
                child_style.pop(key, None)
            primary = child_frame[axis] - previous if retain_distributed_gaps else first_gap if index == 0 else 0
            trailing = last_gap if index == len(children) - 1 else 0
            if direction == "row":
                _margins(child_style, top=child_frame["top"] - frame["top"], right=trailing, left=primary)
            else:
                _margins(child_style, top=primary, bottom=trailing, left=child_frame["left"] - frame["left"])
            previous = _end(child_frame, axis)
            child["style"] = {**deepcopy(child_style), "position": child_style.get("position", "static"),
                              "left": child_frame["left"], "top": child_frame["top"]}
    node["style"] = deepcopy(style)


def _partition_columns(nodes: list[dict], source_nodes: Mapping) -> list[list[dict]]:
    """Split rounded cell/leaf overlaps when their source edges are disjoint.

    The DDS frame rounds position and size separately, so two touching source
    columns can overlap after rounding. This refines an existing projection;
    it never merges separate groups or relaxes an actual source overlap.
    """
    result = []
    for members in _partition(nodes, "left"):
        proxies, originals = [], {}
        for member in members:
            raw = source_nodes.get(member.get("layerId"), {})
            frame = raw.get("frame") if isinstance(raw, Mapping) else None
            eligible = (_painted_cell(member) or _simple_image(member)
                        or (member.get("type") == "lanhutext" and not member.get("children")
                            and isinstance(member.get("props", {}).get("text"), str)))
            if (not eligible or _paint_bounds(member) is None or not isinstance(frame, Mapping)
                    or any(isinstance(frame.get(key), bool) or not isinstance(frame.get(key), (int, float))
                           or not math.isfinite(frame[key]) or math.ceil(frame[key]) != _frame(member)[key]
                           for key in ("left", "top", "width", "height"))):
                break
            proxy = {"rowDims": dict(frame)}
            proxies.append(proxy)
            originals[id(proxy)] = member
        if len(proxies) != len(members):
            result.append(members)
        else:
            result.extend([[originals[id(proxy)] for proxy in group] for group in _partition(proxies, "left")])
    return result


def _projected_vertical_groups(nodes: list[dict]) -> list[list[dict]]:
    groups = _partition(nodes, "top")
    joined = []
    for group in groups:
        touching = False
        if joined:
            for before in joined[-1]:
                for after in group:
                    projection_text = ((before.get("ddsHalfTurnRectProjection") is True and _safe_container(before)
                                        and after.get("type") == "lanhutext")
                                       or (after.get("ddsHalfTurnRectProjection") is True and _safe_container(after)
                                           and before.get("type") == "lanhutext"))
                    bf, af = _frame(before), _frame(after)
                    if (projection_text and abs(_end(bf, "top") - af["top"]) < _EPSILON
                            and min(_end(bf, "left"), _end(af, "left")) > max(bf["left"], af["left"])):
                        touching = True
        if touching:
            joined[-1].extend(group)
        else:
            joined.append(group)
    return joined


def _rounded_following_columns(groups: list[list[dict]], source_nodes: Mapping) -> tuple[list[list[dict]], set[frozenset[str]]]:
    """Retain DDS's local table collision grouping, backed by unrounded edges.

    This is an observed compatibility convention: a ceil-only collision with
    the preceding column joins the next equal-width integer columns. It does
    not apply to equal columns generally, or to actual source intersections.
    Only matching row bands in the current vertical partition participate.
    """
    def column(members: list[dict]):
        if len(members) < 2:
            return None
        ordered = sorted(members, key=lambda item: _frame(item)["top"])
        frames = []
        for member in ordered:
            raw = source_nodes.get(member.get("layerId"), {}).get("frame")
            paint = _paint_bounds(member)
            if (not _safe_container(member) or not _painted_cell(member) or paint is None
                    or not _contains(_frame(member), paint) or not isinstance(raw, Mapping)
                    or any(isinstance(raw.get(key), bool) or not isinstance(raw.get(key), (int, float))
                           or not math.isfinite(raw[key]) or math.ceil(raw[key]) != _frame(member)[key]
                           for key in ("left", "top", "width", "height"))):
                return None
            frames.append(raw)
        if (any((f["left"], f["width"]) != (frames[0]["left"], frames[0]["width"]) for f in frames)
                or any(abs(_end(a, "top") - b["top"]) > _EPSILON for a, b in zip(frames, frames[1:]))):
            return None
        return ordered, frames

    output, special, index = [], set(), 0
    while index < len(groups):
        match = False
        if index > 0 and index + 1 < len(groups):
            before, left, right = (column(groups[i]) for i in (index - 1, index, index + 1))
            if before and left and right:
                bf, lf, rf = before[1][0], left[1][0], right[1][0]
                bands = lambda value: [(f["top"], f["height"]) for f in value[1]]
                match = (bands(before) == bands(left) == bands(right)
                         and lf["width"] == rf["width"]
                         and all(float(f[key]).is_integer() for f in (lf, rf) for key in ("left", "width"))
                         and abs(_end(bf, "left") - lf["left"]) < _EPSILON
                         and abs(_end(lf, "left") - rf["left"]) < _EPSILON
                         and 0 < _end(_frame(before[0][0]), "left") - _frame(left[0][0])["left"] <= 1)
        if match:
            members = sorted([*groups[index], *groups[index + 1]],
                             key=lambda item: (_frame(item)["top"], -_frame(item)["left"]))
            output.append(members)
            special.add(frozenset(item.get("layerId") for item in members))
            index += 2
        else:
            output.append(groups[index])
            index += 1
    return output, special


def _projected_header_row(nodes: list[dict]) -> dict | None:
    if not any(node.get("ddsHalfTurnRectProjection") is True and _safe_container(node) for node in nodes):
        return None
    if len(_projected_vertical_groups(nodes)) != 1 or any(_paint_bounds(node) is None for node in nodes):
        return None
    overlays = []
    for index, image in enumerate(nodes):
        if not _simple_image(image):
            continue
        overlaps = [(i, other) for i, other in enumerate(nodes) if other is not image
                    and _overlap(_frame(image), _frame(other))]
        if (len(overlaps) == 1 and overlaps[0][0] < index
                and overlaps[0][1].get("ddsRectEnvelopeProjection") is True
                and _safe_container(overlaps[0][1])):
            overlays.append(image)
    flow = [node for node in nodes if node not in overlays]
    if not overlays or any(_overlap(_frame(left), _frame(right)) for i, left in enumerate(flow) for right in flow[i + 1:]):
        return None
    # Build bounds before removing the baked pointer; its slight overhang is
    # part of the observed row rectangle. Only layout frames connect the row,
    # never the projected rectangle's shadow expansion into the following row.
    row = _group(nodes, "row")
    row["children"] = sorted(flow, key=lambda child: _frame(child)["left"])
    _place_with_overlays(row, "row", overlays)
    return row


def _arrange_frames(nodes: list[dict], source_nodes: Mapping | None = None) -> tuple[list[dict], str | None]:
    if len(nodes) <= 1:
        return nodes, "row" if nodes and nodes[0].get("uiType") == "ImageText" else "column"
    # Known shadows do not participate in DDS layout projections. An unresolved
    # transform/filter still prevents inferring coordinates we do not possess.
    if any(_paint_bounds(node) is None for node in nodes):
        return nodes, None
    projected = _projected_header_row(nodes)
    if projected is not None:
        return [projected], "column"
    y_groups, x_groups = _projected_vertical_groups(nodes), _partition_columns(nodes, source_nodes or {})
    rounded_columns = set()
    if len(y_groups) > 1:
        groups, direction = y_groups, "column"
    elif len(x_groups) > 1:
        groups, rounded_columns = _rounded_following_columns(x_groups, source_nodes or {})
        direction = "row"
    else:
        return nodes, None
    result = []
    for members in groups:
        if len(members) == 1:
            result.extend(members)
        elif frozenset(member.get("layerId") for member in members) in rounded_columns:
            group = _group(members, "column")
            _place_dds(group, "column")
            result.append(group)
        else:
            identities = {id(member) for member in members}
            original_order = [node for node in nodes if id(node) in identities]
            projected = _projected_header_row(original_order)
            if projected is not None:
                result.append(projected)
                continue
            children, child_direction = _arrange_frames(original_order, source_nodes)
            group = _group(children, child_direction or "column")
            _place_dds(group, child_direction)
            result.append(group)
    return result, direction


def _projected_column_overlays(node: dict, children: list[dict]) -> set[str]:
    """Keep later cards above an earlier projected hairline's raw envelope."""
    if node.get("type") != "lanhupage" and not _safe_container(node):
        return set()

    def lines(current: dict):
        if current.get("ddsRotatedHairlineProjection") is True and _safe_container(current):
            yield current
        elif _safe_container(current):
            for child in current.get("children", []):
                yield from lines(child)

    candidates = []
    for index, child in enumerate(children):
        if not _safe_container(child) or not _painted_cell(child):
            continue
        frame = _frame(child)
        if not _contains(_frame(node), frame) or _paint_bounds(child) is None:
            continue
        for earlier in children[:index]:
            ef = _frame(earlier)
            same_column = ef["left"] == frame["left"] and ef["width"] == frame["width"]
            if (_safe_container(earlier) and _painted_cell(earlier)
                    and (same_column or node.get("type") == "lanhupage")
                    and _end(ef, "top") <= frame["top"]
                    and any(not _contains(ef, _frame(line)) and _overlap(_frame(line), frame)
                            for line in lines(earlier))):
                candidates.append(child)
                break
    candidate_ids = {child.get("layerId") for child in candidates}
    # All candidates retain source order as final absolute layers. Reject the
    # cohort if that movement crosses any other later, unresolved or painted
    # sibling, including descendants extending beyond their own layout frames.
    for candidate in candidates:
        index, paint = children.index(candidate), _paint_bounds(candidate)
        for later in children[index + 1:]:
            if later.get("layerId") in candidate_ids:
                continue
            bound = _paint_bounds(later)
            if bound is None or _overlap(paint, bound):
                return set()
    return candidate_ids


def _local_overlays(node: dict, children: list[dict], source_nodes: Mapping,
                    adopted_anchors: set[str] | None = None) -> list[dict]:
    result = []
    parent_frame = _frame(node)
    projected_cards = _projected_column_overlays(node, children)
    for index, image in enumerate(children):
        frame = _frame(image)
        if image.get("layerId") in (adopted_anchors or set()) | projected_cards:
            result.append(image)
            continue
        if (image.get("ddsRotatedHairlineProjection") is True and not image.get("children")
                and _safe_container(image) and _paint_bounds(image) is not None):
            # This explicit compatibility projection retains a quarter-turned
            # separator's raw envelope, which can exceed its original card.
            # DDS keeps it at that original scope as a final absolute layer.
            result.append(image)
            continue
        if index == 1 and len(children) == 2 and _safe_container(image) and _painted_cell(image):
            pointer = children[0]
            raw = source_nodes.get(pointer.get("layerId"), {})
            rotation, raw_frame = raw.get("rotation"), raw.get("frame", {})
            rotated_pointer = (isinstance(rotation, (int, float)) and not isinstance(rotation, bool)
                               and math.isfinite(rotation) and abs(rotation / 90 - round(rotation / 90)) < 1e-6
                               and round(rotation / 90) % 2 == 1)
            source_short = [raw_frame.get(key) for key in ("width", "height")]
            thin = (all(isinstance(value, (int, float)) and not isinstance(value, bool)
                        and math.isfinite(value) and value > 0 for value in source_short)
                    and min(source_short) <= 1)
            paint = _paint_bounds(image)
            if (_simple_image(pointer) and raw.get("hasExportDDSImage") is True and rotated_pointer and thin
                    and _contains(frame, _frame(pointer)) and frame["top"] == parent_frame["top"]
                    and frame["height"] == parent_frame["height"] and frame["width"] > parent_frame["width"] / 2
                    and paint is not None and _contains(_content_frame(node), paint)):
                # The exported pointer retains its raw, rounded layout frame.
                # DDS keeps it in flow and overlays the following full-height
                # body, preserving their original sibling paint order.
                result.append(image)
                continue
        projected = (_safe_container(image) and bool(image.get("children"))
                     and all(child.get("ddsRectEnvelopeProjection") is True
                             and not child.get("children") and _safe_container(child)
                             for child in image["children"]))
        shadow_overlay = (_safe_container(image) and bool(image.get("children"))
                          and bool(_styles(image).get("boxShadow"))
                          and not _no_effect("boxShadow", _styles(image)["boxShadow"]))
        bottom_overlay = (_safe_container(image) and bool(image.get("children")) and _painted_cell(image)
                          and any(_styles(image).get(key) for key in ("border", "borderWidth", "borderTopWidth"))
                          and frame["left"] == parent_frame["left"]
                          and frame["width"] == parent_frame["width"]
                          and _end(frame, "top") == _end(parent_frame, "top"))
        caret_text = False
        if image.get("type") == "lanhutext" and not image.get("children"):
            for caret in children[:index]:
                raw = source_nodes.get(caret.get("layerId"), {})
                raw_width = raw.get("frame", {}).get("width")
                cf = _frame(caret)
                if (_simple_image(caret) and raw.get("hasExportDDSImage") is True
                        and isinstance(raw_width, (int, float)) and not isinstance(raw_width, bool)
                        and math.isfinite(raw_width) and 0 < raw_width < 1 and cf["width"] == 1
                        and cf["left"] == frame["left"] and cf["height"] < frame["height"]
                        and _contains(frame, cf)):
                    caret_text = True
        anchor_text = (image.get("type") == "lanhutext" and not image.get("children")
                       and any(other.get("ddsEmptyShapeProjection") is True and _overlap(frame, _frame(other))
                               for other in children[:index]))
        if not (_simple_image(image) or projected or shadow_overlay or bottom_overlay or anchor_text or caret_text) or not _contains(parent_frame, frame):
            continue
        # A local decoration is smaller than the parent in both dimensions and
        # occupies less than a quarter of its area; full backgrounds remain flow.
        short_side = min(parent_frame["width"], parent_frame["height"])
        if not (shadow_overlay or bottom_overlay or caret_text) and not (0 < frame["width"] <= short_side and 0 < frame["height"] <= short_side
                and frame["width"] * frame["height"] < parent_frame["width"] * parent_frame["height"] / 4):
            continue
        overlaps = [(other_index, other) for other_index, other in enumerate(children)
                    if other is not image and _overlap(frame, _frame(other))]
        if not overlaps or any(other_index > index for other_index, _ in overlaps):
            continue
        if (_simple_image(image) and len(overlaps) == 1
                and overlaps[0][1].get("ddsHalfTurnRectProjection") is True
                and _safe_container(overlaps[0][1])):
            later_paint = [_paint_bounds(other) for other in children[index + 1:]]
            if all(bound is not None and not _overlap(frame, bound) for bound in later_paint):
                result.append(image)
                continue
        if projected or shadow_overlay or bottom_overlay or anchor_text or caret_text:
            paint = _paint_bounds(image)
            other_bounds = [(i, other, _paint_bounds(other)) for i, other in enumerate(children) if other is not image]
            shadow_only = []
            if anchor_text and paint is not None:
                for i, other, bound in other_bounds:
                    if (i > index and bound is not None and _overlap(paint, bound)
                            and not any(_overlap(paint, _frame(descendant)) for descendant in _walk(other))
                            and any(_styles(descendant).get("boxShadow")
                                    and not _no_effect("boxShadow", _styles(descendant)["boxShadow"])
                                    for descendant in _walk(other))):
                        shadow_only.append(other)
            if (paint is None or not _contains(_content_frame(node), paint)
                    or any(bound is None for _, _, bound in other_bounds)
                    or any(_overlap(paint, bound) and ((i > index and other not in shadow_only)
                                                     or (projected and not _simple_image(other)))
                           for i, other, bound in other_bounds)):
                continue
            if shadow_only:
                # DDS groups by layout frames: this explicit annotation/empty
                # shape case paints above a later control's shadow extension.
                # It is compatibility behavior, not source paint preservation.
                image.setdefault("conversionWarnings", []).append({
                    "code": "dds_annotation_shadow_order",
                    "reason": "DDS annotation placement moves it above a later sibling's shadow-only paint extension",
                    "layerIds": [other.get("layerId") for other in shadow_only],
                })
            result.append(image)
            continue
        raw = source_nodes.get(image.get("layerId"), {})
        rotation = raw.get("rotation", 0) if isinstance(raw, Mapping) else 0
        rotated = (isinstance(rotation, (int, float)) and not isinstance(rotation, bool)
                   and math.isfinite(rotation) and abs(rotation / 90 - round(rotation / 90)) > 1e-6)
        if rotated or len(overlaps) > 1:
            result.append(image)
    return result


def _wrap_single_text_rows(node: dict, *, original_nodes: set[str] | None = None,
                           singleton_cells: set[str] | None = None,
                           source_text_frames: Mapping | None = None) -> bool:
    """Keep a lone text cell as a row beside homogeneous multi-cell rows."""
    if _styles(node).get("flexDirection") != "column":
        return False
    children = node.get("children", [])

    def matrix_row(child: dict) -> bool:
        cells = child.get("children", [])
        homogeneous = (_styles(child).get("flexDirection") == "row" and not child.get("uiType")
                and (original_nodes is None or child.get("layerId") not in original_nodes)
                and len(cells) >= 2 and len({cell.get("type") for cell in cells}) == 1)
        if not homogeneous or original_nodes is None or cells[0].get("type") != "lanhublock":
            return homogeneous
        return (any(cell.get("layerId") in original_nodes and cell.get("children") for cell in cells)
                or all(cell.get("layerId") in original_nodes and _painted_cell(cell) for cell in cells))

    contained_rows = [child for child in children if _styles(child).get("flexDirection") == "row"
                      and _contains(_frame(node), _frame(child))]
    if not any(matrix_row(child) for child in contained_rows):
        return False
    content_span = _union(contained_rows)
    result = []
    changed = False
    for index, child in enumerate(children):
        if (child.get("type") == "lanhutext" or child.get("layerId") in (singleton_cells or set())) \
                and _styles(child).get("position") != "absolute":
            frame = _frame(child)
            source_frame = (source_text_frames or {}).get(child.get("layerId"), frame)
            parent_frame = _content_frame(node)
            left_inset = frame["left"] - parent_frame["left"]
            right_inset = _end(parent_frame, "left") - _end(frame, "left")
            # A leading full-inset text box can anchor the content width even
            # when the matrix's cell rectangles overrun its right edge.
            inset_anchor = (index == 0 and left_inset > 0 and abs(left_inset - right_inset) < _EPSILON
                            and abs(frame["left"] - content_span["left"]) < _EPSILON)
            if inset_anchor or (source_frame["left"] <= content_span["left"] + _EPSILON
                                and _end(source_frame, "left") >= _end(content_span, "left") - _EPSILON):
                result.append(child)
                continue
            group = _group([child], "row")
            _place_dds(group, "row")
            result.append(group)
            changed = True
        else:
            result.append(child)
    node["children"] = result
    return changed


def _place_with_overlays(node: dict, direction: str | None, overlays: list[dict]) -> None:
    """Place only flow children; append local decorations without flex sizing."""
    _place_dds(node, direction)
    if overlays:
        node["props"]["style"]["position"] = "relative"
        parent_frame = _content_frame(node)
        for image in overlays:
            # A projected badge retains its own child flex layout; only its
            # placement in the parent changes. Images have no inner layout.
            if image.get("type") == "lanhublock":
                style = image["props"]["style"]
                for key in ("left", "top", "right", "bottom", "position", "zIndex", "flexShrink",
                            "margin", "marginTop", "marginRight", "marginBottom", "marginLeft"):
                    style.pop(key, None)
            else:
                style = _clean_style(image)
            frame = _frame(image)
            style.update(position="absolute", left=frame["left"] - parent_frame["left"],
                         top=frame["top"] - parent_frame["top"])
            image["style"] = deepcopy(style)
        node["children"].extend(overlays)
    node["style"] = deepcopy(node["props"]["style"])


def wrap_single_text_rows(root: dict) -> dict:
    """Return a laid-out copy with one-cell rows in a matrix context.

    Standalone text columns and heterogeneous image/text rows do not establish
    a matrix. Existing semantic groups and absolute decorations are preserved.
    """
    _validate(root)
    result = deepcopy(root)

    def visit(node: dict) -> None:
        for child in node.get("children", []):
            visit(child)
        if _styles(node).get("flexDirection") != "column":
            return
        children = node["children"]
        overlays = [child for child in children if _styles(child).get("position") == "absolute"]
        node["children"] = [child for child in children if child not in overlays]
        if _wrap_single_text_rows(node):
            _place_with_overlays(node, "column", overlays)
        else:
            node["children"] = children

    visit(result)
    result["props"]["style"]["position"] = "relative"
    result["style"] = deepcopy(result["props"]["style"])
    return result


def infer_dds_layout(root: dict, *, image_composer: Callable | None = None,
                     source_nodes: Mapping[str, dict] | None = None) -> dict:
    """Infer DDS-compatible structure from normalized, absolute DDS frames.

    ``source_nodes`` optionally maps each source layer ID to its raw export.
    Types and geometry establish backdrop/repeated-view context; raw rotation
    identifies previously rasterized decorations and component ancestry keeps
    checkbox graphics out of image/text semantic pairing.
    ``image_composer`` has the same contract as the conservative layout helper.
    Input objects are never mutated, and unknown top-level metadata (including
    ``sourceHasOrdinaryImage``) survives on every retained image node.
    """
    _validate(root)
    if source_nodes is not None and not isinstance(source_nodes, Mapping):
        raise ValueError("source_nodes must map layer IDs to source objects")
    source_nodes = source_nodes or {}
    excluded_images = (checkbox_layer_ids(source_nodes) | repeated_view_layer_ids(source_nodes)
                       | contextual_pairing_exclusions(source_nodes))
    compact_pairs = compact_source_pairs(source_nodes)
    result = deepcopy(root)
    accept_merge = build_dds_image_merge_policy(result)
    column_cohorts = []
    source_cohorts = []
    source_text_frames = {}

    def flatten(node: dict) -> list[dict]:
        node["children"] = [descendant for child in node.get("children", []) for descendant in flatten(child)]
        if (_transparent(node) and node.get("ddsEmptyShapeProjection") is not True
                and node.get("ddsTransparentRectProjection") is not True):
            if len(node["children"]) == 1 and node["children"][0].get("type") == "lanhutext":
                text = node["children"][0]
                outer, inner = _frame(node), _frame(text)
                if (all(outer[key] == inner[key] for key in ("left", "top", "height"))
                        and outer["width"] > inner["width"]):
                    previous = source_text_frames.get(text.get("layerId"), inner)
                    if outer["width"] > previous["width"]:
                        source_text_frames[text.get("layerId")] = outer
            if len(node["children"]) >= 2:
                source_cohorts.append(list(node["children"]))
            if _column_cells(node["children"]):
                column_cohorts.append(list(node["children"]))
            return node["children"]
        return [node]

    flatten(result)
    # Semantic pairing copies subtrees. Layer IDs retain node identity across
    # that pure transformation; Python object identities intentionally do not.
    original_nodes = {node.get("layerId") for node in _walk(result)}
    _adopt_bottom_bands(result)
    external_overlays = _lift_overflow_columns(result, column_cohorts)
    for target, overlays in _attach_terminal_backdrops(result, source_nodes).items():
        external_overlays.setdefault(target, []).extend(overlays)
    _lift_fully_outside_children(result)
    promoted_popups = _promote_crossing_shadow_overlays(result, external_overlays)
    pointer_popups = _attach_pointer_popovers(result, source_nodes, promoted_popups)
    forced_overlays = promoted_popups | pointer_popups | {
        overlay.get("layerId") for overlays in external_overlays.values() for overlay in overlays}
    cursor_menus = _attach_cursor_menus(result, source_nodes, forced_overlays)
    lifted_labels = _lift_crossing_row_labels(result)
    adopted_anchors = _attach_empty_shape_cohorts(result, source_cohorts)
    reparented_objects = _reparent_contained_images(result, include_envelope_projections=True,
                                                    source_nodes=source_nodes)
    reparented = {node.get("layerId") for node in _walk(result) if id(node) in reparented_objects}

    def visit(node: dict) -> None:
        for child in node.get("children", []):
            visit(child)
        if node.get("type") not in _BLOCKS:
            _clean_style(node)
            node["style"] = deepcopy(node["props"]["style"])
            return
        if node.get("layerId") in adopted_anchors:
            _place_dds(node, None)
            for child in node["children"]:
                child["props"]["style"].pop("zIndex", None)
                child["style"] = deepcopy(child["props"]["style"])
            node["props"]["style"].update(display="flex", flexDirection="column")
            node["style"] = deepcopy(node["props"]["style"])
            return
        children = _merge_images(node["children"], image_composer, node, accept_merge=accept_merge)
        if node.get("uiType") != "ImageText":
            children = pair_dds_image_text(children, excluded_image_ids=excluded_images, compact_pairs=compact_pairs)
        overlays = _local_overlays(node, children, source_nodes, adopted_anchors | promoted_popups | pointer_popups | cursor_menus)
        if node.get("type") == "lanhupage":
            projected_ids = _projected_column_overlays(node, children)
            for child in overlays:
                contents = child.get("children", [])
                if child.get("layerId") not in projected_ids or not contents:
                    continue
                heading, leaves = contents[0], contents[0].get("children", [])
                if (heading.get("layerId") not in original_nodes and len(leaves) == 1
                        and leaves[0].get("type") == "lanhutext" and _safe_container(heading)
                        and all(key in _BOX_KEYS | _PLACEMENT_KEYS or _no_effect(key, value)
                                for key, value in _styles(heading).items())
                        and _frame(heading) == _frame(leaves[0])):
                    # A floating original card keeps its heading directly;
                    # the one-cell row belonged to its former flow context.
                    child["children"] = [leaves[0], *contents[1:]]
                    _place_dds(child, "column")
        overlay_ids = {child.get("layerId") for child in overlays}
        child_by_id = {child.get("layerId"): child for child in children}
        singleton_cells = set()
        for cohort in source_cohorts:
            identities = {member.get("layerId") for member in cohort}
            remaining = identities - overlay_ids
            if (len(remaining) == 1 and identities & overlay_ids
                    and identities <= child_by_id.keys()):
                identity = next(iter(remaining))
                if _safe_container(child_by_id[identity]) and _painted_cell(child_by_id[identity]):
                    # A source row/column whose annotation became an overlay
                    # still contributes its sole painted cell to the matrix.
                    singleton_cells.add(identity)
        panels = external_overlays.get(id(node), [])
        labels = lifted_labels.get(id(node), [])
        inline = [child for child in children if child.get("layerId") in reparented and child not in overlays]
        flow = [child for child in children if child not in overlays and child not in inline and child not in panels and child not in labels]
        node["children"], direction = _arrange_frames(flow, source_nodes)
        if (node.get("type") == "lanhupage" and direction == "column" and node["children"]
                and is_multicolumn_text_header(node["children"][0])):
            # A multi-column canvas represents each body band as a row, even
            # when only one original panel occupies that vertical band.
            for index, child in enumerate(node["children"][1:], start=1):
                if child.get("layerId") in original_nodes and child.get("type") in {"lanhublock", "lanhuimage"}:
                    row = _group([child], "row")
                    _place_dds(row, "row")
                    node["children"][index] = row
        if inline and direction == "column":
            # A contained marker that overlaps just one item is an inline row:
            # its negative top margin retains that overlap without enlarging
            # an unrelated row or creating an absolute overlap cluster.
            node["children"].extend(inline)
            node["children"].sort(key=lambda child: _frame(child)["top"])
        elif inline:
            node["children"], direction = _arrange_frames([*flow, *inline], source_nodes)
        _place_dds(node, direction)
        _wrap_single_text_rows(node, original_nodes=original_nodes, singleton_cells=singleton_cells,
                               source_text_frames=source_text_frames)
        _place_with_overlays(node, direction, overlays)
        _attach_inline_labels(node, labels, original_nodes)
        _attach_external_overlays(node, panels, original_nodes)

    visit(result)
    result["props"]["style"]["position"] = "relative"
    result["style"] = deepcopy(result["props"]["style"])
    return result
