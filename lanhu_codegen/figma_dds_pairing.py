"""DDS image/text pairing with explicit source control roles.

These are inferred compatibility rules, not the unavailable DDS classifier.
Source component metadata excludes checkbox glyphs from generic icon pairs;
ordinary icon geometry remains governed by the existing layout helper.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from copy import deepcopy
import math

from .figma_layout import (
    _end, _frame, _group, _image_text_pairs, _overlap, _paint_bounds,
    _place, _rect_union, _simple_image,
)


def checkbox_layer_ids(source_nodes: Mapping[str, dict]) -> set[str]:
    """Return source IDs in explicitly identified checkbox component subtrees.

    An exported glyph may be several transparent wrappers below the component.
    Only componentGroup establishes the role; names, dimensions, text content,
    and incidental variant-property names do not. IDs only join raw nodes.
    """
    result: set[str] = set()
    visited: set[int] = set()

    def collect(node: dict) -> None:
        if id(node) in visited:
            return
        visited.add(id(node))
        identity = node.get("id")
        if isinstance(identity, str):
            result.add(identity)
        for child in node.get("layers", []):
            collect(source_nodes.get(child.get("id"), child))

    for node in source_nodes.values():
        if node.get("componentGroup") in ("checkbox", ".checkbox-input"):
            collect(node)
    return result


def repeated_view_layer_ids(source_nodes: Mapping[str, dict]) -> set[str]:
    """Find repeated complete-view scopes for the observed DDS classifier.

    Multiple peer views with a painted full-width header and a partitioned,
    nested body do not acquire generic ImageText wrappers in the paired wide
    composition. Standalone component examples outside those views still do.
    This is an empirical ancestor-context rule, not an official classifier or
    a canvas-size threshold. It never inspects names, text contents or URLs.
    """
    containers = {"artboard", "groupLayer", "symbolInstance", "symbolInstence"}
    epsilon = 1e-6
    stats: dict[int, tuple[int, int, int]] = {}

    def children(node):
        return [child for child in node.get("layers", [])
                if child.get("visible", True) and child.get("opacity", 1) != 0]

    def frame(node):
        value = node.get("frame")
        if not isinstance(value, dict):
            return None
        if any(isinstance(value.get(key), bool) or not isinstance(value.get(key), (int, float))
               or not math.isfinite(value[key]) for key in ("left", "top", "width", "height")):
            return None
        return value if value["width"] > 0 and value["height"] > 0 else None

    def background(node):
        style = node.get("style") or {}
        if style.get("isEnabled", True) is False:
            return False
        return any(paint.get("isEnabled", True) and paint.get("type") == "color"
                   and paint.get("opacity", 1) != 0
                   and (paint.get("color") or {}).get("a", 1) != 0
                   for paint in style.get("fills", []))

    def structure(node):
        if id(node) not in stats:
            if node.get("hasExportDDSImage") or node.get("hasExportImage"):
                stats[id(node)] = (0, 1, 0)
            elif node.get("type") == "textLayer":
                stats[id(node)] = (1, 0, 0)
            else:
                nested = children(node)
                parts = [structure(child) for child in nested]
                stats[id(node)] = (sum(p[0] for p in parts), sum(p[1] for p in parts),
                                   sum(p[2] for p in parts) + int(bool(nested) and node.get("type") in containers))
        return stats[id(node)]

    def full_view(node):
        outer = frame(node)
        if (outer is None or node.get("type") not in containers or not background(node)
                or node.get("hasExportDDSImage") or node.get("hasExportImage")):
            return False
        painted = [(child, frame(child)) for child in children(node)
                   if child.get("type") in containers and background(child) and frame(child) is not None]
        for header, hf in painted:
            if not (abs(hf["left"] - outer["left"]) <= epsilon
                    and abs(hf["top"] - outer["top"]) <= epsilon
                    and abs(hf["width"] - outer["width"]) <= epsilon
                    and hf["height"] < outer["height"]
                    and structure(header)[0] and structure(header)[1]):
                continue
            body = []
            for partition, pf in painted:
                texts, images, nested = structure(partition)
                if (partition is not header and texts >= 2 and images >= 1 and nested >= 2
                        and pf["top"] >= _end(hf, "top") - epsilon
                        and pf["left"] >= outer["left"] - epsilon
                        and _end(pf, "left") <= _end(outer, "left") + epsilon
                        and _end(pf, "top") <= _end(outer, "top") + epsilon):
                    body.append(pf)
            for index, first in enumerate(body):
                if any((_end(first, "left") <= second["left"] + epsilon
                        or _end(second, "left") <= first["left"] + epsilon)
                       and min(_end(first, "top"), _end(second, "top")) > max(first["top"], second["top"])
                       for second in body[index + 1:]):
                    return True
        return False

    result: set[str] = set()

    def collect(node):
        if isinstance(node.get("id"), str):
            result.add(node["id"])
        for child in children(node):
            collect(child)

    for parent in source_nodes.values():
        cohorts: list[list[dict]] = []
        for candidate in children(parent):
            if not full_view(candidate):
                continue
            cf = frame(candidate)
            cohort = next((group for group in cohorts if all(
                abs(cf[key] - frame(group[0])[key]) <= epsilon for key in ("top", "width", "height"))), None)
            if cohort is None:
                cohorts.append([candidate])
            else:
                cohort.append(candidate)
        for cohort in cohorts:
            if len(cohort) < 2:
                continue
            ordered = sorted(cohort, key=lambda item: frame(item)["left"])
            if all(_end(frame(left), "left") <= frame(right)["left"] + epsilon
                   for left, right in zip(ordered, ordered[1:])):
                for node in ordered:
                    collect(node)
    return result


def contextual_pairing_exclusions(source_nodes: Mapping[str, dict]) -> set[str]:
    """Infer bounded DDS contexts where proximity does not imply ImageText.

    A full-view scrim weakens background grouping, except within independently
    bordered multiline cards, fully bordered exported units or explicit Link
    components. The observed Button exception is limited to controls entirely
    behind a later opaque foreground. A transparent, oversized two-leaf field
    label also keeps its trailing icon independent. An opaque Button that
    already fills a transparent single-child source wrapper is kept as one
    control boundary, without adding a second semantic wrapper inside it.
    These are empirical source-context rules, not recovered official logic.
    Source IDs only join metadata; names, text contents and asset URLs are unused.
    """
    containers = {"artboard", "groupLayer", "symbolInstance", "symbolInstence"}
    epsilon = 1e-6
    result: set[str] = set()

    def children(node):
        return [source_nodes.get(child.get("id"), child) for child in node.get("layers", [])
                if child.get("visible", True) and child.get("opacity", 1) != 0]

    def frame(node):
        box = node.get("frame")
        if (not isinstance(box, dict) or any(isinstance(box.get(k), bool)
                or not isinstance(box.get(k), (int, float)) or not math.isfinite(box[k])
                for k in ("left", "top", "width", "height"))):
            return None
        return box if min(box["width"], box["height"]) > 0 else None

    def safe_style(node):
        style = node.get("style") or {}
        if (not isinstance(style, dict) or node.get("clipped") or node.get("isMask")
                or node.get("opacity", 1) != 1 or node.get("rotation", 0) != 0
                or style.get("opacity", 1) != 1 or style.get("isEnabled", True) is False
                or node.get("blendMode") not in (None, 0, "normal", "NORMAL")
                or style.get("blendMode") not in (None, 0, "normal", "NORMAL")
                or set(style) - {"isEnabled", "opacity", "blendMode", "fills", "borders", "shadows", "blurs"}
                or style.get("shadows") or style.get("blurs")):
            return None
        matrix = node.get("transform")
        if matrix is not None and (not isinstance(matrix, list) or len(matrix) != 2
                or any(not isinstance(row, list) or len(row) != 3 for row in matrix)
                or any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
                       for row in matrix for value in row)
                or (matrix[0][0], matrix[0][1], matrix[1][0], matrix[1][1]) != (1, 0, 0, 1)):
            return None
        return style

    def fill_alpha(node):
        style = safe_style(node)
        fills = style.get("fills", []) if style is not None else []
        if len(fills) != 1 or fills[0].get("type") != "color" or not fills[0].get("isEnabled", True):
            return None
        fill = fills[0]
        alphas = (fill.get("opacity", 1), (fill.get("color") or {}).get("a", 1))
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= 1 for v in alphas):
            return None
        return min(alphas)  # Native alpha is duplicated in paint and color.

    def inside(inner, outer):
        return (inner["left"] >= outer["left"] - epsilon and inner["top"] >= outer["top"] - epsilon
                and _end(inner, "left") <= _end(outer, "left") + epsilon
                and _end(inner, "top") <= _end(outer, "top") + epsilon)

    def leaves(node):
        if node.get("hasExportDDSImage") or node.get("hasExportImage") or node.get("type") == "textLayer":
            return [node]
        return [leaf for child in children(node) for leaf in leaves(child)]

    def transparent_leaves(node):
        if node.get("hasExportDDSImage") or node.get("type") == "textLayer":
            return [node]
        style = safe_style(node)
        if (node.get("type") not in containers or style is None
                or style.get("fills") or style.get("borders") or node.get("hasExportImage")):
            return None
        parts = [transparent_leaves(child) for child in children(node)]
        return None if any(part is None for part in parts) else [leaf for part in parts for leaf in part]

    def independent_bordered_boundary(node):
        style, outer = safe_style(node), frame(node)
        if style is None or outer is None or fill_alpha(node) != 1 or len(style.get("borders", [])) != 1:
            return False
        border = style["borders"][0]
        sides = border.get("widths")
        widths = list(sides.get(side, 0) for side in ("top", "right", "bottom", "left")) if isinstance(sides, dict) else [border.get("width", 0)] * 4
        if (not border.get("isEnabled", True) or border.get("lineAlignment") != "inside"
                or border.get("style", "solid") != "solid" or border.get("opacity", 1) != 1
                or (border.get("color") or {}).get("a", 1) != 1
                or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0 for v in widths)):
            return False
        # The export already bakes an independently painted, closed border
        # into this image; its descendants need not expose multiline text.
        # This extends the observed card boundary, not a size/name/URL rule.
        if node.get("hasExportDDSImage") or node.get("hasExportImage"):
            return True
        rows = [frame(child) for child in children(node) if frame(child) is not None
                and inside(frame(child), outer) and any(n.get("type") == "textLayer" for n in leaves(child))]
        return any(_end(first, "top") <= second["top"] + epsilon or _end(second, "top") <= first["top"] + epsilon
                   for i, first in enumerate(rows) for second in rows[i + 1:])

    def opaque_foreground_interior(node):
        box = frame(node)
        if box is None or fill_alpha(node) != 1:
            return None
        paths = node.get("paths") or []
        if paths and (len(paths) != 1 or paths[0].get("type") != "rect"
                      or paths[0].get("frame") != box):
            return None
        radii = [*(node.get("radius") or {}).values(),
                 *((paths[0].get("radius") or {}).values() if paths else ())]
        if any(isinstance(value, bool) or not isinstance(value, (int, float))
               or not math.isfinite(value) or value < 0 for value in radii):
            return None
        inset = max(radii, default=0)
        if 2 * inset >= min(box["width"], box["height"]):
            return None
        # A rectangular interior avoids claiming opaque coverage in rounded
        # corners. Using its full inset on both axes is deliberately conservative.
        return {"left": box["left"] + inset, "top": box["top"] + inset,
                "width": box["width"] - 2 * inset, "height": box["height"] - 2 * inset}

    def covered_control(node, foregrounds):
        def safe_frames(item):
            box = frame(item)
            if box is None or safe_style(item) is None:
                return None
            if item.get("hasExportDDSImage") or item.get("hasExportImage"):
                return [box]
            nested = [safe_frames(child) for child in children(item)]
            return None if any(part is None for part in nested) else [box, *[f for part in nested for f in part]]

        boxes = safe_frames(node)
        return boxes is not None and any(all(inside(box, cover) for box in boxes) for cover in foregrounds)

    def collect_background(node, foregrounds):
        if (node.get("componentGroup") == "Link" or independent_bordered_boundary(node)
                or (node.get("componentGroup") == "Button" and covered_control(node, foregrounds))):
            return
        if node.get("hasExportDDSImage") or node.get("hasExportImage"):
            if isinstance(node.get("id"), str):
                result.add(node["id"])
            return
        for child in children(node):
            collect_background(child, foregrounds)

    def miscentered_table_images(parent, rows, outer, parent_style):
        if (outer is None or parent.get("type") not in containers or parent_style is None
                or parent.get("hasExportDDSImage") or parent.get("hasExportImage")
                or parent_style.get("fills") or parent_style.get("borders") or len(rows) < 3):
            return set()
        boxes = [frame(row) for row in rows]
        if (any(box is None for box in boxes) or fill_alpha(rows[0]) != 1
                or not all(leaf.get("type") == "textLayer" for leaf in leaves(rows[0]))
                or not leaves(rows[0])
                or any(abs(box["left"] - outer["left"]) > epsilon
                       or abs(box["width"] - outer["width"]) > epsilon for box in boxes)
                or abs(boxes[0]["top"] - outer["top"]) > epsilon
                or abs(_end(boxes[-1], "top") - _end(outer, "top")) > epsilon
                or any(abs(_end(first, "top") - second["top"]) > epsilon
                       for first, second in zip(boxes, boxes[1:]))):
            return set()
        for row in rows:
            style = safe_style(row)
            if (row.get("type") not in containers or style is None or len(style.get("borders", [])) != 1
                    or row.get("hasExportDDSImage") or row.get("hasExportImage")):
                return set()
            border = style["borders"][0]
            widths = border.get("widths")
            if (not isinstance(widths, dict) or not border.get("isEnabled", True)
                    or border.get("lineAlignment") != "inside" or border.get("style", "solid") != "solid"
                    or border.get("opacity", 1) != 1 or (border.get("color") or {}).get("a", 1) != 1
                    or any(isinstance(widths.get(side), bool) or not isinstance(widths.get(side), (int, float))
                           or not math.isfinite(widths[side]) for side in ("top", "right", "bottom", "left"))
                    or widths["bottom"] <= 0 or any(widths[side] != 0 for side in ("top", "right", "left"))):
                return set()
        excluded = set()
        for row in rows[1:]:
            parts = [transparent_leaves(child) for child in children(row)]
            terminal = [] if any(part is None for part in parts) else [leaf for part in parts for leaf in part]
            if (len(terminal) != 2 or not terminal[0].get("hasExportDDSImage")
                    or terminal[1].get("type") != "textLayer"):
                continue
            image, text = terminal
            raw_boxes = [frame(item) for item in (row, image, text)]
            if any(box is None for box in raw_boxes) or any(not inside(box, raw_boxes[0]) for box in raw_boxes[1:]):
                continue
            cell, im, tf = [{key: math.ceil(value) for key, value in box.items()} for box in raw_boxes]
            image_center, text_center = im["top"] + im["height"] / 2, tf["top"] + tf["height"] / 2
            if (0 < im["width"] == im["height"] <= 32 and 0 < im["height"] - tf["height"] <= 2
                    and 0 <= tf["left"] - _end(im, "left") <= im["width"]
                    and abs(image_center - text_center) <= epsilon
                    and abs(image_center - cell["top"] - cell["height"] / 2) > epsilon):
                # The taller-leading-icon allowance is observed only for a
                # centered row in these source table columns. DDS uses ceil-
                # normalized outer frames, not a border-subtracted content box.
                # This is a bounded compatibility hypothesis, not official logic.
                excluded.add(image["id"])
        return excluded

    def borderless_field_images(parent, descendants, outer, parent_style):
        if (outer is None or parent.get("type") not in containers or parent_style is None
                or fill_alpha(parent) != 1 or parent_style.get("borders")
                or parent.get("hasExportDDSImage") or parent.get("hasExportImage")
                or not 1 <= len(descendants) <= 2):
            return set()
        excluded = set()
        for body in descendants:
            terminal, bf = transparent_leaves(body), frame(body)
            if (terminal is None or len(terminal) != 2 or bf is None
                    or not terminal[0].get("hasExportDDSImage") or terminal[1].get("type") != "textLayer"):
                continue
            image, text = terminal
            im, tf = frame(image), frame(text)
            if (im is None or tf is None or not inside(im, bf) or not inside(tf, bf)
                    or not (outer["left"] < bf["left"] and outer["top"] < bf["top"]
                            and _end(bf, "left") < _end(outer, "left") and _end(bf, "top") < _end(outer, "top"))
                    or not 0 < im["width"] == im["height"] <= 32
                    or not 0 < im["height"] - tf["height"] <= 2
                    or not 0 <= tf["left"] - _end(im, "left") <= im["width"]):
                continue
            content = _rect_union(im, tf)
            if (bf["width"] <= 2 * content["width"] or bf["height"] <= content["height"]
                    or outer["height"] > 2 * content["height"]
                    or abs(content["left"] - bf["left"]) > epsilon
                    or abs(im["top"] + im["height"] / 2 - tf["top"] - tf["height"] / 2) > epsilon
                    or abs(content["top"] + content["height"] / 2 - outer["top"] - outer["height"] / 2) > epsilon):
                continue
            others = [child for child in descendants if child is not body]
            tails = [transparent_leaves(child) for child in others]
            if any(part is None or len(part) != 1 or not part[0].get("hasExportDDSImage")
                   or frame(part[0]) is None or not inside(frame(part[0]), outer)
                   or frame(part[0])["left"] < _end(bf, "left") for part in tails):
                continue
            # The source already reserves a padded, wide content body in a
            # borderless filled field. Keep that field's leaf layout instead
            # of treating the short leading caption as a new semantic unit.
            # This is geometry/paint evidence, not a gray-color or readonly test.
            excluded.add(image["id"])
        return excluded

    def menu_footer_images(parent, descendants, outer):
        if (parent.get("componentGroup") != "dropdown-menu" or outer is None or len(descendants) < 2
                or parent.get("hasExportDDSImage") or parent.get("hasExportImage")):
            return set()
        style = parent.get("style") or {}
        if not isinstance(style, dict):
            return set()
        # The menu's own shadow stays on the same ancestor; this predicate only
        # avoids an extra semantic wrapper inside the footer. Other scope guards
        # still apply, and the renderer remains responsible for shadow support.
        scope = {**parent, "style": {**style, "shadows": []}}
        if safe_style(scope) is None or fill_alpha(scope) != 1:
            return set()
        footer = descendants[-1]
        ff, style = frame(footer), safe_style(footer)
        if (footer.get("componentGroup") != "components/dropdown/menu-item" or ff is None
                or style is None or fill_alpha(footer) != 1 or not inside(ff, outer)
                or abs(ff["left"] - outer["left"]) > epsilon or abs(ff["width"] - outer["width"]) > epsilon
                or len(style.get("borders", [])) != 1):
            return set()
        border = style["borders"][0]
        widths = border.get("widths")
        if (not isinstance(widths, dict) or not border.get("isEnabled", True)
                or border.get("lineAlignment") != "inside" or border.get("style", "solid") != "solid"
                or border.get("opacity", 1) != 1 or (border.get("color") or {}).get("a", 1) != 1
                or any(isinstance(widths.get(side), bool) or not isinstance(widths.get(side), (int, float))
                       or not math.isfinite(widths[side]) for side in ("top", "right", "bottom", "left"))
                or widths["top"] <= 0 or any(widths[side] != 0 for side in ("right", "bottom", "left"))):
            return set()
        parts = [transparent_leaves(child) for child in children(footer)]
        terminal = [] if any(part is None for part in parts) else [leaf for part in parts for leaf in part]
        if (len(terminal) != 2 or not terminal[0].get("hasExportDDSImage")
                or terminal[1].get("type") != "textLayer"
                or any(frame(item) is None or not inside(frame(item), ff) for item in terminal)):
            return set()
        # An explicitly identified terminal menu item with its own top
        # separator already supplies the observed footer-content boundary.
        # This does not classify ordinary menu options or detached artboards.
        return {terminal[0]["id"]}

    for parent in source_nodes.values():
        outer, descendants = frame(parent), children(parent)
        parent_style = safe_style(parent)
        result.update(miscentered_table_images(parent, descendants, outer, parent_style))
        result.update(borderless_field_images(parent, descendants, outer, parent_style))
        result.update(menu_footer_images(parent, descendants, outer))
        if (outer is not None and parent.get("type") in containers and parent_style is not None
                and not any(parent_style.get(key) for key in ("fills", "borders"))
                and not parent.get("hasExportDDSImage") and not parent.get("hasExportImage")
                and len(descendants) == 1):
            control = descendants[0]
            cf = frame(control)
            if (control.get("componentGroup") == "Button" and cf is not None
                    and fill_alpha(control) == 1
                    and not control.get("hasExportDDSImage") and not control.get("hasExportImage")
                    and all(abs(cf[key] - outer[key]) <= epsilon for key in outer)):
                parts = [transparent_leaves(child) for child in children(control)]
                terminal = [] if any(part is None for part in parts) else [leaf for part in parts for leaf in part]
                if (len(terminal) == 2 and sum(item.get("type") == "textLayer" for item in terminal) == 1
                        and sum(bool(item.get("hasExportDDSImage")) for item in terminal) == 1
                        and all(frame(item) is not None and inside(frame(item), cf) for item in terminal)):
                    # The wrapper itself is the inferred grouping boundary.
                    # This narrow observed context does not apply to Link,
                    # arbitrary icon/text rows, or loose/painted wrappers.
                    result.update(item["id"] for item in terminal if item.get("hasExportDDSImage"))
        if outer is not None and parent.get("type") in containers and fill_alpha(parent) == 1:
            for index, scrim in enumerate(descendants):
                sf, alpha = frame(scrim), fill_alpha(scrim)
                paths = scrim.get("paths") or []
                if (index < 2 or sf is None or alpha is None or not 0 < alpha < 1
                        or scrim.get("type") != "shapeLayer" or children(scrim)
                        or len(paths) != 1 or paths[0].get("type") != "rect"
                        or paths[0].get("frame") != sf
                        or any((paths[0].get("radius") or {}).values())
                        or any(abs(sf[k] - outer[k]) > epsilon for k in outer)):
                    continue
                # A header, body and later inset foreground panel establish a
                # view overlay, rather than a repeated small control or tint.
                before, after = descendants[:index], descendants[index + 1:]
                header = any((cf := frame(child)) is not None and child.get("type") in containers
                             and fill_alpha(child) == 1 and cf["height"] < outer["height"]
                             and all(abs(cf[k] - outer[k]) <= epsilon for k in ("left", "top", "width"))
                             for child in before)
                foreground = any((cf := frame(child)) is not None and child.get("type") in containers
                                 and fill_alpha(child) == 1 and inside(cf, outer)
                                 and cf["width"] < outer["width"] and cf["height"] < outer["height"]
                                 for child in after)
                if header and foreground:
                    # This bounds the earlier broad Button exception using the
                    # paired source evidence. It is not proof that occlusion is
                    # the private classifier's reason for preserving a wrapper.
                    covers = [cover for child in after if (cover := opaque_foreground_interior(child)) is not None]
                    for child in before:
                        collect_background(child, covers)
        # Only trailing icons in transparent two-leaf labels qualify. A broad
        # left-icon navigation row is not a field label and remains unchanged.
        style = safe_style(parent)
        if (outer is None or parent.get("type") not in containers or style is None
                or style.get("fills") or style.get("borders") or len(descendants) != 2):
            continue
        terminal = transparent_leaves(parent)
        if (terminal is None or len(terminal) != 2 or terminal[0].get("type") != "textLayer"
                or not terminal[1].get("hasExportDDSImage")):
            continue
        tf, image = frame(terminal[0]), frame(terminal[1])
        if (tf is None or image is None or not inside(tf, outer) or not inside(image, outer)
                or image["left"] < _end(tf, "left") or image["height"] > tf["height"]
                or abs((image["top"] + image["height"] / 2) - (tf["top"] + tf["height"] / 2)) > 1):
            continue
        content = _rect_union(tf, image)
        if (abs(content["left"] - outer["left"]) <= epsilon
                and abs(content["height"] - outer["height"]) <= epsilon
                and outer["width"] > 2 * content["width"]):
            result.add(terminal[1]["id"])
    return result


def compact_source_pairs(source_nodes: Mapping[str, dict]) -> set[tuple[str, str]]:
    """Record ordered two-leaf pairs whose transparent source box is tight.

    This is structural evidence for grouping adjacent leaves without moving
    them across a later shadow. It does not override icon eligibility or an
    unknown paint effect. Only direct text/DDS-image children qualify.
    """
    result = set()
    for parent in source_nodes.values():
        style = parent.get("style") or {}
        if (parent.get("type") not in {"artboard", "groupLayer", "symbolInstance", "symbolInstence"}
                or parent.get("clipped") or parent.get("isMask") or parent.get("opacity", 1) != 1
                or parent.get("rotation", 0) != 0 or parent.get("hasExportDDSImage") or parent.get("hasExportImage")
                or not isinstance(style, dict) or style.get("opacity", 1) != 1
                or style.get("isEnabled", True) is False
                or parent.get("blendMode") not in (None, 0, "normal", "NORMAL")
                or style.get("blendMode") not in (None, 0, "normal", "NORMAL")
                or set(style) - {"isEnabled", "opacity", "blendMode", "fills", "borders", "shadows", "blurs"}
                or any(style.get(key) for key in ("fills", "borders", "shadows", "blurs"))):
            continue
        matrix = parent.get("transform")
        if matrix is not None and (not isinstance(matrix, list) or len(matrix) != 2
                or any(not isinstance(row, list) or len(row) != 3 for row in matrix)
                or any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
                       for row in matrix for value in row)
                or (matrix[0][0], matrix[0][1], matrix[1][0], matrix[1][1]) != (1, 0, 0, 1)):
            continue
        children = [source_nodes.get(child.get("id"), child) for child in parent.get("layers", [])
                    if child.get("visible", True) and child.get("opacity", 1) != 0]
        if (len(children) != 2 or sum(c.get("type") == "textLayer" for c in children) != 1
                or sum(bool(c.get("hasExportDDSImage")) for c in children) != 1
                or any(c.get("isMask") for c in children)):
            continue
        boxes = [n.get("frame") for n in (parent, *children)]
        if any(not isinstance(box, dict) or any(isinstance(box.get(key), bool)
               or not isinstance(box.get(key), (int, float)) or not math.isfinite(box[key])
               for key in ("left", "top", "width", "height"))
               or min(box["width"], box["height"]) <= 0 for box in boxes):
            continue
        union = _rect_union(boxes[1], boxes[2])
        if all(abs(boxes[0][key] - value) <= 1e-6 for key, value in union.items()):
            result.add((children[0]["id"], children[1]["id"]))
    return result


def _compact_adjacent_pairs(nodes: list[dict], excluded: frozenset[str],
                            source_pairs: Collection[tuple[str, str]]) -> list[dict]:
    """Allow only external shadow overlap for corroborated adjacent leaves."""
    if not source_pairs:
        return nodes
    paint = [_paint_bounds(node) for node in nodes]
    if any(bounds is None for bounds in paint):
        return nodes
    nonshadow_bounds = {}

    def without_shadows(node):
        # The diagnostic copy retains every descendant and clipping boundary;
        # only boxShadow is omitted to distinguish blur from escaping real ink.
        result = {**node, "children": [without_shadows(child) for child in node.get("children", [])]}
        result["style"] = {key: value for key, value in node.get("style", {}).items() if key != "boxShadow"}
        props = node.get("props", {})
        result["props"] = {**props, "style": {key: value for key, value in props.get("style", {}).items() if key != "boxShadow"}}
        return result

    def only_external_shadows(first_index, bounds):
        for other_index, other in enumerate(nodes):
            if other_index in {first_index, first_index + 1} or not _overlap(bounds, paint[other_index]):
                continue
            if other_index not in nonshadow_bounds:
                nonshadow_bounds[other_index] = _paint_bounds(without_shadows(other))
            body = nonshadow_bounds[other_index]
            if body is None or _overlap(bounds, body):
                return False
        return True

    result, index = [], 0
    while index < len(nodes):
        first = nodes[index]
        second = nodes[index + 1] if index + 1 < len(nodes) else {}
        eligible = (first.get("layerId"), second.get("layerId")) in source_pairs
        leading = first.get("type") == "lanhuimage"
        image, text = (first, second) if leading else (second, first)
        if (eligible and image.get("layerId") not in excluded and _simple_image(image)
                and text.get("type") == "lanhutext" and not text.get("children")):
            image_frame, text_frame = _frame(image), _frame(text)
            gap = (text_frame["left"] - _end(image_frame, "left") if leading
                   else image_frame["left"] - _end(text_frame, "left"))
            limit = image_frame["width"] if leading else text_frame["height"]
            centered = abs(image_frame["top"] + image_frame["height"] / 2
                           - text_frame["top"] - text_frame["height"] / 2) <= 1
            if (0 < image_frame["width"] == image_frame["height"] <= 32
                    and image_frame["height"] <= text_frame["height"] + (2 if leading else 0)
                    and centered and 0 <= gap <= limit
                    and only_external_shadows(index, _rect_union(paint[index], paint[index + 1]))):
                text["uiType"] = "TextGroup"
                group = _group([first, second], "row", image_text=True)
                _place(group, "row")
                result.append(group)
                index += 2
                continue
        result.append(first)
        index += 1
    return result


def _additional_pairs(nodes: list[dict], excluded: frozenset[str], *, leading: bool) -> list[dict]:
    """Pair a slightly taller leading icon or an ordinary suffix icon."""
    paint_bounds = [_paint_bounds(node) for node in nodes]
    result: list[dict] = []
    consumed: set[int] = set()
    for index, anchor in enumerate(nodes):
        if index in consumed:
            continue
        candidates = []
        anchor_type = "lanhuimage" if leading else "lanhutext"
        if anchor.get("type") == anchor_type and not anchor.get("children"):
            for other_index in range(index + 1, len(nodes)):
                other = nodes[other_index]
                image, text = (anchor, other) if leading else (other, anchor)
                if (other_index in consumed or image.get("layerId") in excluded or not _simple_image(image)
                        or text.get("type") != "lanhutext" or text.get("children")):
                    continue
                frame, tf = _frame(image), _frame(text)
                if not 0 < frame["width"] == frame["height"] <= 32:
                    continue
                if leading:
                    if not 0 < frame["height"] - tf["height"] <= 2:
                        continue
                    gap, limit = tf["left"] - _end(frame, "left"), frame["width"]
                else:
                    if frame["height"] > tf["height"]:
                        continue
                    gap, limit = frame["left"] - _end(tf, "left"), tf["height"]
                center_delta = abs(frame["top"] + frame["height"] / 2 - tf["top"] - tf["height"] / 2)
                if not 0 <= gap <= limit or center_delta > 1:
                    continue
                if paint_bounds[index] is None or paint_bounds[other_index] is None:
                    continue
                bounds = _rect_union(paint_bounds[index], paint_bounds[other_index])
                if any(obstacle not in {index, other_index}
                       and (paint is None or _overlap(bounds, paint))
                       for obstacle, paint in enumerate(paint_bounds)):
                    continue
                candidates.append((gap, other_index, other, text))
        if candidates:
            _, other_index, other, text = min(candidates, key=lambda item: (item[0], item[1]))
            consumed.add(other_index)
            text["uiType"] = "TextGroup"
            group = _group([anchor, other], "row", image_text=True)
            _place(group, "row")
            result.append(group)
        else:
            result.append(anchor)
    return result


def pair_dds_image_text(nodes: list[dict], *, excluded_image_ids: Collection[str] = (),
                        compact_pairs: Collection[tuple[str, str]] = ()) -> list[dict]:
    """Return copied nodes with eligible left- and right-icon pairs grouped.

    Leading icons also allow the observed two-pixel excess over a text line
    box. Suffix icons can be at most one text-frame height away. These inferred
    thresholds preserve painter order and the complete bounds of both leaves.
    Excluded controls/view scopes remain present as possible paint obstacles.
    ``compact_pairs`` can corroborate adjacent leaves when only known shadows
    outside their source-order interval overlap them. Real frame/escaped-child
    paint remains an obstacle. Defaults are unchanged.
    """
    excluded = frozenset(excluded_image_ids)
    copied = _image_text_pairs(
        deepcopy(nodes), accept_image=lambda node: node.get("layerId") not in excluded,
    )
    copied = _additional_pairs(copied, excluded, leading=True)
    copied = _additional_pairs(copied, excluded, leading=False)
    return _compact_adjacent_pairs(copied, excluded, compact_pairs)
