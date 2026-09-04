"""Convert Lanhu Figma exports into DDS using observed normalization rules.

Layout inference is reconstructed from paired exports, not Lanhu server source.
Missing paint/geometry remains an error except for an explicitly warned, narrow
DDS rectangle-envelope projection. Absolute/source modes retain strict geometry.
"""

from __future__ import annotations

from copy import deepcopy
import html
import math
import re
from collections.abc import Callable
from urllib.parse import urlsplit


class UnsupportedFigmaFeature(ValueError):
    """A visible layer cannot be represented faithfully by this adapter."""

    def __init__(self, layer: dict, feature: str):
        self.layer_id = str(layer.get("id", "<unknown>"))
        self.layer_name = str(layer.get("name", "<unnamed>"))
        self.feature = feature
        super().__init__(
            f"Unsupported Figma feature: {feature}; "
            f"layer_id={self.layer_id!r}, layer_name={self.layer_name!r}"
        )


_CONTAINERS = {"artboard", "groupLayer", "symbolInstance", "symbolInstence"}
_RECTANGLE_NAME = re.compile(r"^(?:rectangle|矩形)(?:\s|\d|$)", re.IGNORECASE)
_NORMAL_BLEND = {None, 0, "0", "normal", "NORMAL", "pass-through", "PASS_THROUGH"}


def _number(value, node: dict, feature: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise UnsupportedFigmaFeature(node, f"invalid {feature}: expected a finite number")
    if minimum is not None and value < minimum:
        raise UnsupportedFigmaFeature(node, f"invalid {feature}: below {minimum}")
    return value


def _alpha(value, node: dict, feature: str) -> float:
    result = _number(value, node, feature, minimum=0)
    if result > 1:
        raise UnsupportedFigmaFeature(node, f"invalid {feature}: above 1")
    return result


def _px(value: float) -> str:
    return f"{value:.10f}".rstrip("0").rstrip(".") + "px"


def _opacity(node: dict) -> float:
    style = node.get("style") or {}
    if not isinstance(style, dict):
        raise UnsupportedFigmaFeature(node, "invalid style")
    layer_opacity = _alpha(node.get("opacity", style.get("opacity", 1)), node, "opacity")
    if "opacity" in node and "opacity" in style:
        style_opacity = _alpha(style["opacity"], node, "style.opacity")
        # Lanhu duplicates the Figma layer opacity in both fields.
        # The native plugin also emits style.opacity=1 as a default while the
        # actual layer alpha lives in node.opacity.
        if style_opacity != 1 and not math.isclose(layer_opacity, style_opacity, abs_tol=1e-6):
            raise UnsupportedFigmaFeature(node, "conflicting layer/style opacity")
    return layer_opacity


def _color(color: dict, node: dict, paint_opacity: float = 1) -> str:
    if not isinstance(color, dict):
        raise UnsupportedFigmaFeature(node, "missing color information")
    paint_opacity = _alpha(paint_opacity, node, "paint opacity")
    if all(channel in color for channel in ("r", "g", "b")):
        values = [_number(color[channel], node, "color channel", minimum=0) for channel in ("r", "g", "b")]
        if any(channel > 1 for channel in values):
            raise UnsupportedFigmaFeature(node, "non-normalized Figma color channels")
        rgb = [round(channel * 255) for channel in values]
        alpha = _alpha(color.get("a", color.get("alpha", 1)), node, "color alpha")
    else:
        value = color.get("value", "")
        rgba = re.fullmatch(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)(?:\s*,\s*([\d.]+))?\s*\)", value)
        hex_color = re.fullmatch(r"#([0-9a-fA-F]{6})([0-9a-fA-F]{2})?", value)
        if rgba:
            rgb = [int(rgba[index]) for index in (1, 2, 3)]
            if any(channel > 255 for channel in rgb):
                raise UnsupportedFigmaFeature(node, "invalid RGB color")
            alpha = _alpha(float(rgba[4]) if rgba[4] else 1, node, "color alpha")
        elif hex_color:
            rgb = [int(hex_color[1][index:index + 2], 16) for index in (0, 2, 4)]
            alpha = int(hex_color[2], 16) / 255 if hex_color[2] else 1
        else:
            raise UnsupportedFigmaFeature(node, "unsupported color representation")
    # Figma exports commonly duplicate paint opacity into color.a. Applying it
    # twice makes e.g. a 10% fill become 1% opaque.
    if alpha == 1:
        alpha = paint_opacity
    elif paint_opacity != 1 and not math.isclose(alpha, paint_opacity, abs_tol=1e-6):
        raise UnsupportedFigmaFeature(node, "ambiguous paint opacity and color alpha")
    return f"rgba({rgb[0]}, {rgb[1]}, {rgb[2]}, {alpha:.10f}".rstrip("0").rstrip(".") + ")"


def _active(values: list | None, node: dict, feature: str) -> list[dict]:
    if values is None:
        return []
    if not isinstance(values, list) or any(not isinstance(value, dict) for value in values):
        raise UnsupportedFigmaFeature(node, f"invalid {feature} list")
    return [value for value in values if value.get("isEnabled", True) and value.get("opacity", 1) != 0]


def _check_blend(value, node: dict) -> None:
    if not isinstance(value, (str, int, type(None))) or value not in _NORMAL_BLEND:
        raise UnsupportedFigmaFeature(node, f"blend mode {value!r}")


def _export_url(node: dict, *, prefer_dds_descendants: bool = True) -> str | None:
    for marker, key in (("hasExportDDSImage", "ddsImage"), ("hasExportImage", "image")):
        resource = node.get(key)
        if not node.get(marker):
            continue
        # A normal export is a designer's slice, not a DDS flattening decision.
        # In particular a slice can contain separately exported DDS children.
        if marker == "hasExportImage" and prefer_dds_descendants and _has_dds_descendant(node):
            continue
        if not isinstance(resource, dict):
            raise UnsupportedFigmaFeature(node, f"{marker} without {key} resource")
        url = resource.get("imageUrl") or resource.get("svgUrl")
        if not isinstance(url, str) or not url:
            raise UnsupportedFigmaFeature(node, f"{key} without image URL")
        parsed = urlsplit(url)
        if parsed.scheme not in {"https", "http"} or not parsed.netloc or any(char in url for char in ('"', "<", ">", "\n", "\r")):
            raise UnsupportedFigmaFeature(node, f"invalid {key} image URL")
        return url
    return None


def _has_dds_descendant(node: dict) -> bool:
    return any(
        isinstance(child, dict) and child.get("visible", True)
        and (child.get("hasExportDDSImage") or _has_dds_descendant(child))
        for child in node.get("layers") or []
    )


def _frame(node: dict, *, root: bool = False) -> dict:
    frame = node.get("frame")
    if not isinstance(frame, dict):
        raise UnsupportedFigmaFeature(node, "missing frame")
    result = {key: _number(frame.get(key), node, f"frame.{key}", minimum=0 if key in {"width", "height"} else None)
              for key in ("left", "top", "width", "height")}
    if root:
        result.update(left=0, top=0)
    return result


def _corners(node: dict, *, integer_pixels: bool = False) -> str | None:
    radius = node.get("radius")
    paths = node.get("paths") or []
    if paths and isinstance(paths[0], dict) and isinstance(paths[0].get("radius"), dict):
        # Containers in actual exports may have node.radius=0 and path.radius>0.
        radius = paths[0]["radius"]
    if radius is None:
        return None
    if not isinstance(radius, dict):
        raise UnsupportedFigmaFeature(node, "non-per-corner radius")
    corners = [_number(radius.get(key, 0), node, f"radius.{key}", minimum=0)
               for key in ("topLeft", "topRight", "bottomRight", "bottomLeft")]
    if integer_pixels:
        # DDS uses integer corner pixels; subpixel corners become zero.
        corners = [math.floor(value) for value in corners]
    return " ".join(_px(value) for value in corners) if any(corners) else None


def _dds_rect_envelope(node: dict, *, hairline: bool = False) -> bool:
    """Recognize the observed DDS projection, not the missing vector contour.

    A solid square with a quarter-turn unit transform has a square envelope,
    but that envelope need not be the original shape. Only this explicit,
    corroborated payload may use the compatibility projection with a warning.
    The separate hairline case admits a zero-corner strip with one dimension
    no larger than one CSS pixel, verified against its transformed realFrame.
    Neither case recovers the contour. Names, IDs and colors play no part.
    """
    source, paths = node.get("style"), node.get("paths")
    if (node.get("type") != "shapeLayer" or node.get("shapeType") is not None
            or node.get("layers") or node.get("clipped") or node.get("isMask")
            or not isinstance(source, dict) or source.get("isEnabled", True) is False
            or set(source) - {"isEnabled", "opacity", "blendMode", "fills", "borders", "shadows", "blurs"}
            or not isinstance(paths, list) or len(paths) != 1 or not isinstance(paths[0], dict)):
        return False
    path = paths[0]
    if (path.get("type") != "rect" or set(path) != {"type", "frame", "radius"}
            or any(node.get(key) for key in ("vectorPaths", "fillGeometry", "strokeGeometry", "points", "pathData", "geometry"))):
        return False
    try:
        frame = _frame(node)
        size = frame["width"]
        short, long = sorted((frame["width"], frame["height"]))
        dimensions_match = 0 < short <= 1 < long if hairline else size > 0 and size == frame["height"]
        if not dimensions_match:
            return False
        if path["frame"] != frame:
            return False
        for key, value in path["frame"].items():
            _number(value, node, f"paths.frame.{key}")
        rotation = _number(node.get("rotation"), node, "rotation")
        turns = round(rotation / 90)
        if turns % 2 != 1 or not math.isclose(rotation, turns * 90, rel_tol=0, abs_tol=1e-5):
            return False
        matrix = node.get("transform")
        if (not isinstance(matrix, list) or len(matrix) != 2
                or any(not isinstance(row, list) or len(row) != 3 for row in matrix)):
            return False
        for row in matrix:
            for value in row:
                _number(value, node, "transform")
        linear = (matrix[0][0], matrix[0][1], matrix[1][0], matrix[1][1])
        direction = (1 if matrix[1][0] > 0 else -1) if hairline else (1 if turns % 4 == 1 else -1)
        expected = (0, -direction, direction, 0)
        if not all(math.isclose(value, ideal, rel_tol=0, abs_tol=1e-6) for value, ideal in zip(linear, expected)):
            return False
        # The native export uses a rotated corner anchor in frame, while its
        # separate realFrame records the transformed square's actual bounds.
        real = node.get("realFrame")
        actual_bounds = dict(frame)
        if hairline:
            # Native strips can report +90 degrees with the opposite-signed
            # unit matrix. Use the matrix and independently recorded realFrame,
            # including its dimension-scaled float noise, to verify the anchor.
            a, b, c, d = linear
            points = [(frame["left"] + a * x + b * y, frame["top"] + c * x + d * y)
                      for x in (0, frame["width"]) for y in (0, frame["height"])]
            xs, ys = zip(*points)
            actual_bounds = {"left": min(xs), "top": min(ys),
                             "width": max(xs) - min(xs), "height": max(ys) - min(ys)}
        else:
            actual_bounds["left" if direction == 1 else "top"] -= size
        if (not isinstance(real, dict)
                or any(not math.isclose(_number(real.get(key), node, f"realFrame.{key}"), value,
                                        rel_tol=0, abs_tol=1e-5) for key, value in actual_bounds.items())):
            return False
        corner_keys = {"topLeft", "topRight", "bottomRight", "bottomLeft"}
        radius = path["radius"]
        if not isinstance(radius, dict) or set(radius) != corner_keys:
            return False
        radii = [_number(radius[key], node, f"radius.{key}", minimum=0) for key in sorted(corner_keys)]
        if len(set(radii)) != 1 or (radii[0] != 0 if hairline else radii[0] > size / 2):
            return False
        if node.get("radius", radius) != radius:
            return False
        if _opacity(node) != 1:
            return False
        _check_blend(node.get("blendMode"), node)
        _check_blend(source.get("blendMode"), node)
        if any(_active(source.get(key), node, key) for key in ("borders", "shadows", "blurs")):
            return False
        fills = _active(source.get("fills"), node, "fills")
        if len(fills) != 1 or fills[0].get("type") != "color" or fills[0].get("opacity", 1) != 1:
            return False
        _check_blend(fills[0].get("blendMode"), node)
        return _color(fills[0].get("color"), node).endswith(", 1)")
    except UnsupportedFigmaFeature:
        return False


def _axis_flips(node: dict) -> tuple[bool, bool] | None:
    """Recognize exact signed axes, not a nearly 180-degree rotation.

    Native exports use a corner anchor for exact reflections. Near-axis and
    general rotations use a different frame convention and must not enter
    this branch just because their matrix is numerically close to a mirror.
    """
    matrix = node.get("transform")
    if (not isinstance(matrix, list) or len(matrix) != 2
            or any(not isinstance(row, list) or len(row) != 3 for row in matrix)):
        return None
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
           for row in matrix for value in row):
        return None
    a, b, _ = matrix[0]
    c, d, _ = matrix[1]
    if b == c == 0 and a in {-1, 1} and d in {-1, 1}:
        return a == -1, d == -1
    return None


def _dds_empty_shape(node: dict, *, zero_height: bool = False) -> bool:
    """Bound the observed DDS empty-block projection of a real exported image.

    A nontransparent PNG can still satisfy this metadata rule. DDS discards
    those pixels, so callers must retain its URL in an explicit warning and
    must never use this projection in source-preserving modes.
    """
    source, paths = node.get("style"), node.get("paths")
    if (node.get("type") != "shapeLayer" or node.get("shapeType") is not None
            or node.get("layers") or node.get("clipped") or node.get("isMask")
            or not node.get("hasExportDDSImage") or node.get("hasExportImage")
            or not isinstance(source, dict) or source.get("isEnabled", True) is False
            or set(source) - {"isEnabled", "opacity", "blendMode", "fills", "borders", "shadows", "blurs"}
            or any(source.get(key) != [] for key in ("fills", "borders", "shadows", "blurs"))
            or not isinstance(paths, list) or len(paths) != 1 or not isinstance(paths[0], dict)
            or any(node.get(key) for key in ("vectorPaths", "fillGeometry", "strokeGeometry", "points", "pathData", "geometry"))):
        return False
    path = paths[0]
    if path.get("type") != "rect" or set(path) != {"type", "frame", "radius"}:
        return False
    try:
        frame = _frame(node)
        dimensions_match = (frame["width"] > 0 and frame["height"] == 0 if zero_height
                            else min(frame["width"], frame["height"]) > 0)
        if not dimensions_match or path["frame"] != frame:
            return False
        for key, value in path["frame"].items():
            _number(value, node, f"paths.frame.{key}")
        real = node.get("realFrame")
        if (not isinstance(real, dict) or any(not math.isclose(
                _number(real.get(key), node, f"realFrame.{key}"), value, rel_tol=0, abs_tol=1e-5)
                for key, value in frame.items())):
            return False
        rotation = _number(node.get("rotation"), node, "rotation")
        if not math.isclose(rotation % 360, 0, rel_tol=0, abs_tol=1e-5) or _axis_flips(node) != (False, False):
            return False
        corner_keys = {"topLeft", "topRight", "bottomRight", "bottomLeft"}
        radius, node_radius = path["radius"], node.get("radius")
        if (not isinstance(radius, dict) or set(radius) != corner_keys
                or not isinstance(node_radius, dict) or set(node_radius) != corner_keys):
            return False
        radii = [_number(radius[key], node, f"radius.{key}", minimum=0) for key in sorted(corner_keys)]
        radius_matches = radii[0] == 0 if zero_height else 0 < radii[0] <= min(frame["width"], frame["height"]) / 2
        if len(set(radii)) != 1 or not radius_matches:
            return False
        node_radii = [_number(node_radius[key], node, f"radius.{key}", minimum=0) for key in sorted(corner_keys)]
        if any(node_radii) and node_radius != radius:
            return False
        _check_blend(node.get("blendMode"), node)
        _check_blend(source.get("blendMode"), node)
        return _opacity(node) == 1
    except UnsupportedFigmaFeature:
        return False


def _verified_unit_turn(node: dict) -> int | None:
    """Return a corroborated nonidentity unit quarter-turn, without repairing it."""
    try:
        frame = _frame(node)
        if min(frame["width"], frame["height"]) <= 0:
            return None
        rotation = _number(node.get("rotation"), node, "rotation")
        turns = round(rotation / 90)
        if turns % 4 == 0 or not math.isclose(rotation, turns * 90, rel_tol=0, abs_tol=1e-5):
            return None
        matrix = node.get("transform")
        if (not isinstance(matrix, list) or len(matrix) != 2
                or any(not isinstance(row, list) or len(row) != 3 for row in matrix)):
            return None
        for row in matrix:
            for value in row:
                _number(value, node, "transform")
        a, b, _ = matrix[0]
        c, d, _ = matrix[1]
        expected = {1: (0, -1, 1, 0), 2: (-1, 0, 0, -1), 3: (0, 1, -1, 0)}[turns % 4]
        if any(not math.isclose(value, ideal, rel_tol=0, abs_tol=1e-6)
               for value, ideal in zip((a, b, c, d), expected)):
            return None
        points = [(frame["left"] + a * x + b * y, frame["top"] + c * x + d * y)
                  for x in (0, frame["width"]) for y in (0, frame["height"])]
        xs, ys = zip(*points)
        bounds = {"left": min(xs), "top": min(ys), "width": max(xs) - min(xs), "height": max(ys) - min(ys)}
        real = node.get("realFrame")
        if isinstance(real, dict) and all(math.isclose(
                _number(real.get(key), node, f"realFrame.{key}"), value, rel_tol=0, abs_tol=1e-5)
                for key, value in bounds.items()):
            return turns % 4
    except UnsupportedFigmaFeature:
        pass
    return None


def _dds_transparent_rect(node: dict) -> bool:
    """Retain a verified unpainted rounded envelope as a DDS layout box.

    An alpha-zero solid fill contributes no pixels, but the official schema
    can retain its box and color channels for later containment. This is an
    envelope projection, not evidence that the missing vector was rectangular.
    """
    source, paths = node.get("style"), node.get("paths")
    if (node.get("type") != "shapeLayer" or node.get("shapeType") is not None
            or node.get("layers") or node.get("clipped") or node.get("isMask")
            or not isinstance(source, dict) or source.get("isEnabled", True) is False
            or set(source) - {"isEnabled", "opacity", "blendMode", "fills", "borders", "shadows", "blurs"}
            or any(source.get(key) != [] for key in ("borders", "shadows", "blurs"))
            or not isinstance(paths, list) or len(paths) != 1 or not isinstance(paths[0], dict)
            or any(node.get(key) for key in ("vectorPaths", "fillGeometry", "strokeGeometry", "points", "pathData", "geometry"))):
        return False
    path, fills = paths[0], source.get("fills")
    if (path.get("type") != "rect" or set(path) != {"type", "frame", "radius"}
            or not isinstance(fills, list) or len(fills) != 1 or not isinstance(fills[0], dict)
            or fills[0].get("type") != "color" or fills[0].get("isEnabled", True) is False):
        return False
    try:
        frame = _frame(node)
        if min(frame["width"], frame["height"]) <= 0 or path["frame"] != frame:
            return False
        for key, value in path["frame"].items():
            _number(value, node, f"paths.frame.{key}")
        real = node.get("realFrame")
        if (not isinstance(real, dict) or any(not math.isclose(
                _number(real.get(key), node, f"realFrame.{key}"), value, rel_tol=0, abs_tol=1e-5)
                for key, value in frame.items())):
            return False
        if (not math.isclose(_number(node.get("rotation"), node, "rotation") % 360, 0, rel_tol=0, abs_tol=1e-5)
                or _axis_flips(node) != (False, False) or _opacity(node) != 1):
            return False
        keys = {"topLeft", "topRight", "bottomRight", "bottomLeft"}
        radius, node_radius = path["radius"], node.get("radius")
        if (not isinstance(radius, dict) or set(radius) != keys
                or not isinstance(node_radius, dict) or set(node_radius) != keys):
            return False
        radii = [_number(radius[key], node, f"radius.{key}", minimum=0) for key in sorted(keys)]
        node_radii = [_number(node_radius[key], node, f"radius.{key}", minimum=0) for key in sorted(keys)]
        if (len(set(radii)) != 1 or not 0 < radii[0] <= min(frame["width"], frame["height"]) / 2
                or any(node_radii) and node_radius != radius):
            return False
        for value in (node.get("blendMode"), source.get("blendMode"), fills[0].get("blendMode")):
            _check_blend(value, node)
        return _color(fills[0].get("color"), node, fills[0].get("opacity", 1)).endswith(", 0)")
    except UnsupportedFigmaFeature:
        return False


def _dds_half_turn_rect(node: dict) -> bool:
    """Recognize the bounded DDS projection of a decorated, nearly square rect.

    The source's rotation/contour is not restored. Only its explicit uniform
    rounded envelope, opaque fill, inside border and representable box shadows
    qualify; ordinary unsupported vectors and general rotations stay errors.
    """
    source, paths = node.get("style"), node.get("paths")
    if (node.get("type") != "shapeLayer" or node.get("shapeType") is not None
            or node.get("layers") or node.get("clipped") or node.get("isMask")
            or not isinstance(source, dict) or source.get("isEnabled", True) is False
            or set(source) - {"isEnabled", "opacity", "blendMode", "fills", "borders", "shadows", "blurs"}
            or not isinstance(paths, list) or len(paths) != 1 or not isinstance(paths[0], dict)
            or _verified_unit_turn(node) != 2
            or any(node.get(key) for key in ("vectorPaths", "fillGeometry", "strokeGeometry", "points", "pathData", "geometry"))):
        return False
    path = paths[0]
    if path.get("type") != "rect" or set(path) != {"type", "frame", "radius"}:
        return False
    try:
        frame = _frame(node)
        if path["frame"] != frame or not math.isclose(frame["width"], frame["height"], rel_tol=0, abs_tol=1e-5):
            return False
        for key, value in path["frame"].items():
            _number(value, node, f"paths.frame.{key}")
        keys = {"topLeft", "topRight", "bottomRight", "bottomLeft"}
        radius, node_radius = path["radius"], node.get("radius")
        if (not isinstance(radius, dict) or set(radius) != keys
                or not isinstance(node_radius, dict) or set(node_radius) != keys):
            return False
        radii = [_number(radius[key], node, f"radius.{key}", minimum=0) for key in sorted(keys)]
        node_radii = [_number(node_radius[key], node, f"radius.{key}", minimum=0) for key in sorted(keys)]
        if (len(set(radii)) != 1 or not 0 < radii[0] <= min(frame["width"], frame["height"]) / 2
                or any(node_radii) and node_radius != radius or _opacity(node) != 1):
            return False
        fills, borders = _active(source.get("fills"), node, "fills"), _active(source.get("borders"), node, "borders")
        if (len(fills) != 1 or fills[0].get("type") != "color"
                or fills[0].get("opacity", 1) != 1 or not _color(fills[0].get("color"), node).endswith(", 1)")
                or len(borders) != 1 or not _active(source.get("shadows"), node, "shadows")):
            return False
        border = borders[0]
        base = _number(border.get("width"), node, "border.width", minimum=0)
        if base <= 0 or base > min(frame["width"], frame["height"]) / 2:
            return False
        sides = border.get("widths")
        if sides is not None and (not isinstance(sides, dict) or any(
                _number(sides.get(side), node, f"border.widths.{side}") != base for side in ("top", "right", "bottom", "left"))):
            return False
        # Validate all remaining visible paint/effects through the normal strict
        # renderer, bypassing only the independently verified unit half-turn.
        _visual_style({**node, "rotation": 0, "transform": [[1, 0, 0], [0, 1, 0]]})
        return True
    except UnsupportedFigmaFeature:
        return False


def _dds_projected_group(node: dict) -> bool:
    """Allow a transparent turned group only around verified projected leaves."""
    if (node.get("type") != "groupLayer" or node.get("clipped") or node.get("isMask")
            or node.get("hasExportDDSImage") or node.get("hasExportImage") or _verified_unit_turn(node) is None):
        return False
    try:
        source = node.get("style") or {}
        if (not isinstance(source, dict) or _opacity(node) != 1
                or set(source) - {"isEnabled", "opacity", "blendMode", "fills", "borders", "shadows", "blurs"}
                or any(source.get(key) for key in ("fills", "borders", "shadows", "blurs"))):
            return False
        _check_blend(node.get("blendMode"), node)
        _check_blend(source.get("blendMode"), node)
        children = node.get("layers") or []
        if not isinstance(children, list) or any(not isinstance(child, dict) for child in children):
            return False
        projected = False
        for child in children:
            if child.get("visible", True) is False or _opacity(child) == 0:
                continue
            if child.get("isMask"):
                return False
            if child.get("hasExportDDSImage") and _export_url(child):
                continue
            if _dds_rect_envelope(child) or _dds_half_turn_rect(child) or _dds_projected_group(child):
                projected = True
            else:
                return False
        return projected
    except UnsupportedFigmaFeature:
        return False


def _export_frame(node: dict, frame: dict) -> dict:
    flips = _axis_flips(node)
    real = node.get("realFrame")
    if not flips or not any(flips) or not isinstance(real, dict):
        return frame
    # Require the separately exported geometry to corroborate the anchor
    # correction. This also avoids double-correcting an already normalized box.
    corrected = dict(frame)
    for flipped, axis, size in zip(flips, ("left", "top"), ("width", "height")):
        if flipped:
            corrected[axis] -= frame[size]
    if all(isinstance(real.get(key), (int, float)) and not isinstance(real[key], bool)
           and math.isclose(real[key], value, rel_tol=0, abs_tol=1e-5)
           for key, value in corrected.items()):
        return corrected
    return frame


def _verified_swapped_axes(node: dict) -> bool:
    """Verify a unit quarter-turn/reflection and its separate corner bounds.

    This does not repair vectors. It is only used for transparent containers
    whose exported descendants already carry their transformed pixels.
    """
    try:
        frame = _frame(node)
        if frame["width"] <= 0 or frame["height"] <= 0:
            return False
        rotation = _number(node.get("rotation"), node, "rotation")
        turns = round(rotation / 90)
        if turns % 2 != 1 or not math.isclose(rotation, turns * 90, rel_tol=0, abs_tol=1e-5):
            return False
        matrix = node.get("transform")
        if (not isinstance(matrix, list) or len(matrix) != 2
                or any(not isinstance(row, list) or len(row) != 3 for row in matrix)):
            return False
        for row in matrix:
            for value in row:
                _number(value, node, "transform")
        a, b, _ = matrix[0]
        c, d, _ = matrix[1]
        if any(not math.isclose(value, ideal, rel_tol=0, abs_tol=1e-6)
               for value, ideal in ((a, 0), (d, 0), (abs(b), 1), (abs(c), 1))):
            return False
        points = [(frame["left"] + a * x + b * y, frame["top"] + c * x + d * y)
                  for x in (0, frame["width"]) for y in (0, frame["height"])]
        xs, ys = zip(*points)
        expected = {"left": min(xs), "top": min(ys), "width": max(xs) - min(xs), "height": max(ys) - min(ys)}
        real = node.get("realFrame")
        return isinstance(real, dict) and all(
            math.isclose(_number(real.get(key), node, f"realFrame.{key}"), value, rel_tol=0, abs_tol=1e-5)
            for key, value in expected.items())
    except UnsupportedFigmaFeature:
        return False


def _raster_only_wrapper(node: dict, *, allow_swapped_axes: bool = False) -> bool:
    """Whether an axis-aligned wrapper adds no paint around baked DDS images."""
    if (node.get("type") not in _CONTAINERS or node.get("isMask") or node.get("clipped")
            or _opacity(node) != 1):
        return False
    source = node.get("style") or {}
    if (allow_swapped_axes and (not isinstance(source, dict)
            or set(source) - {"isEnabled", "opacity", "blendMode", "fills", "borders", "shadows", "blurs"})):
        return False
    _check_blend(node.get("blendMode"), node)
    _check_blend(source.get("blendMode"), node)
    if source.get("isEnabled", True) and any(_active(source.get(key), node, key)
                                             for key in ("fills", "borders", "shadows", "blurs")):
        return False
    if (node.get("transform") is not None and _axis_flips(node) is None
            and not (allow_swapped_axes and _verified_swapped_axes(node))):
        return False
    children = node.get("layers") or []
    if not isinstance(children, list) or any(not isinstance(child, dict) for child in children):
        return False
    visible = [child for child in children if child.get("visible", True) and _opacity(child) != 0]
    return bool(visible) and all(not child.get("isMask") and (
        (child.get("hasExportDDSImage") and _export_url(child))
        or _raster_only_wrapper(child, allow_swapped_axes=allow_swapped_axes)
    ) for child in visible)


def _shadows(node: dict, source: dict, *, text: bool, dds: bool) -> dict:
    values = _active(source.get("shadows"), node, "shadows")
    if not values:
        return {}
    # Text effects have different spread/outline semantics. A bitmap remains
    # necessary until those can be represented without changing the glyphs.
    if text:
        raise UnsupportedFigmaFeature(node, "text shadows without an exported image")
    css = []
    for shadow in values:
        _check_blend(shadow.get("blendMode"), node)
        x = _number(shadow.get("x"), node, "shadows.x")
        y = _number(shadow.get("y"), node, "shadows.y")
        blur = _number(shadow.get("blur"), node, "shadows.blur", minimum=0)
        spread = _number(shadow.get("spread"), node, "shadows.spread")
        inset = shadow.get("inset")
        if not isinstance(inset, bool):
            raise UnsupportedFigmaFeature(node, "shadows.inset must be a boolean")
        color = _color(shadow.get("color"), node, shadow.get("opacity", 1))
        if dds:
            channels = color.removeprefix("rgba(").removesuffix(")").split(",")
            color = f"rgba({int(channels[0])},{int(channels[1])},{int(channels[2])},{float(channels[3]):.6f})"
        css.append(("inset " if inset else "") + " ".join(_px(v) for v in (x, y, blur, spread)) + " " + color)
    return {"boxShadow": ", ".join(css)}


def _visual_style(node: dict, *, text: bool = False, dds: bool = False,
                  baked_wrapper: bool = False, integer_corners: bool = False) -> tuple[dict, dict]:
    """Return paint style and border widths affecting child positioning."""
    source = node.get("style") or {}
    if not isinstance(source, dict):
        raise UnsupportedFigmaFeature(node, "invalid style")
    _check_blend(node.get("blendMode"), node)
    _check_blend(source.get("blendMode"), node)
    if node.get("isMask"):
        raise UnsupportedFigmaFeature(node, "mask affecting sibling layers")
    rotation = _number(node.get("rotation", 0), node, "rotation")
    if not baked_wrapper and not math.isclose(rotation % 360, 0, abs_tol=1e-5):
        raise UnsupportedFigmaFeature(node, "rotation without an exported image")
    transform = node.get("transform")
    if transform is not None and not baked_wrapper:
        try:
            linear = [transform[0][0], transform[0][1], transform[1][0], transform[1][1]]
            if any(not math.isclose(_number(value, node, "transform"), expected, abs_tol=1e-6)
                   for value, expected in zip(linear, [1, 0, 0, 1])):
                raise UnsupportedFigmaFeature(node, "transformed geometry without an exported image")
        except (IndexError, TypeError):
            raise UnsupportedFigmaFeature(node, "invalid transform matrix") from None
    result = {}
    widths = dict.fromkeys(("top", "right", "bottom", "left"), 0)
    opacity = _opacity(node)
    if opacity != 1:
        result["opacity"] = opacity
    if node.get("clipped"):
        result["overflow"] = "hidden"
    radius = _corners(node, integer_pixels=integer_corners)
    if radius:
        result["borderRadius"] = radius
    if source.get("isEnabled", True) is False:
        return result, widths
    if _active(source.get("blurs"), node, "blurs"):
        raise UnsupportedFigmaFeature(node, "blurs without an exported image")
    result.update(_shadows(node, source, text=text, dds=dds))
    fills = _active(source.get("fills"), node, "fills")
    if len(fills) > 1:
        raise UnsupportedFigmaFeature(node, "multiple visible fills")
    if fills:
        fill = fills[0]
        _check_blend(fill.get("blendMode"), node)
        if fill.get("type") != "color":
            raise UnsupportedFigmaFeature(node, f"fill type {fill.get('type')!r}")
        color = _color(fill.get("color"), node, fill.get("opacity", 1))
        if not text:
            result["backgroundColor"] = color
    borders = _active(source.get("borders"), node, "borders")
    if len(borders) > 1:
        raise UnsupportedFigmaFeature(node, "multiple visible borders")
    if borders:
        border = borders[0]
        _check_blend(border.get("blendMode"), node)
        if border.get("style", "solid") != "solid":
            raise UnsupportedFigmaFeature(node, "non-solid border")
        base = _number(border.get("width", 0), node, "border.width", minimum=0)
        sides = border.get("widths")
        if sides is not None and not isinstance(sides, dict):
            raise UnsupportedFigmaFeature(node, "invalid border.widths")
        if sides and any(sides.get(side, 0) for side in widths):
            widths = {side: _number(sides.get(side, 0), node, f"border.widths.{side}", minimum=0) for side in widths}
        else:
            widths = dict.fromkeys(widths, base)
        if any(widths.values()):
            if text:
                raise UnsupportedFigmaFeature(node, "text outline without an exported image")
            if border.get("lineAlignment", "center") != "inside":
                raise UnsupportedFigmaFeature(node, "center/outside border without an exported image")
            if border.get("lineJoin", "miter") != "miter" or border.get("lineCap", "none") not in {"none", "butt"}:
                raise UnsupportedFigmaFeature(node, "border line joins/caps without an exported image")
            color = _color(border.get("color"), node, border.get("opacity", 1))
            if dds:
                # The paired official schema uses strokeWeight, even for a
                # per-edge Figma border. Callers can choose absolute layout to
                # retain per-edge source rendering instead of this DDS rule.
                result["border"] = f"{_px(base)} solid {color}"
                widths = dict.fromkeys(widths, base)
            else:
                for side, value in widths.items():
                    if value:
                        result[f"border{side.title()}"] = f"{_px(value)} solid {color}"
    return result, widths


def _text_style(node: dict, *, dds: bool = False, font_envelope: bool = False) -> tuple[str, dict]:
    text = node.get("text")
    if not isinstance(text, dict) or not isinstance(text.get("value"), str):
        raise UnsupportedFigmaFeature(node, "missing text content")
    content = text["value"]
    base = text.get("style") or {}
    segments = text.get("styles") or []
    if not isinstance(segments, list) or any(not isinstance(segment, dict) for segment in segments):
        raise UnsupportedFigmaFeature(node, "invalid rich-text styles")
    if segments:
        cursor = 0
        for segment in segments:
            start, end = segment.get("from"), segment.get("to")
            if not isinstance(start, int) or not isinstance(end, int) or start != cursor or end < start:
                raise UnsupportedFigmaFeature(node, "incomplete or overlapping rich-text ranges")
            cursor = end
        if cursor != len(content.encode("utf-16-le", errors="surrogatepass")) // 2:
            raise UnsupportedFigmaFeature(node, "incomplete rich-text range coverage")
        signatures = [{key: value for key, value in segment.items() if key not in {"from", "to", "length", "content"}}
                      for segment in segments]
        if any(signature != signatures[0] for signature in signatures[1:]):
            raise UnsupportedFigmaFeature(node, "mixed rich-text styles")
        base = segments[0]
    font = base.get("font") or {}
    size = _number(font.get("size"), node, "font size", minimum=0)
    family = font.get("postScriptName") or font.get("name")
    if not isinstance(family, str) or not family or any(char in family for char in ("\n", "\r", "<", ">")):
        raise UnsupportedFigmaFeature(node, "missing or invalid font family")
    family = '"' + family.replace("\\", "\\\\").replace('"', '\\"') + '"'
    weight = font.get("fontWeight")
    if weight is None:
        weight = 700 if font.get("bold") else {"Regular": 400, "Medium": 500, "Semibold": 600, "Bold": 700}.get(font.get("type", "Regular"))
    if isinstance(weight, str) and weight.isdigit():
        weight = int(weight)
    if not isinstance(weight, (int, float)) or isinstance(weight, bool) or not 1 <= weight <= 1000:
        raise UnsupportedFigmaFeature(node, "unknown font weight")
    if font.get("lineSpacing", 0) or font.get("paragraphSpacing", 0):
        raise UnsupportedFigmaFeature(node, "paragraph or line spacing")
    align = font.get("align", "left")
    if align not in {"left", "right", "center", "justify"}:
        raise UnsupportedFigmaFeature(node, "text alignment")
    result = {"display": "block", "fontSize": size, "fontFamily": family, "fontWeight": weight,
              "textAlign": align, "whiteSpace": "pre-wrap", "overflowWrap": "break-word",
              "color": _color(base.get("color"), node)}
    line_height = font.get("lineHeight")
    if line_height is not None:
        if not isinstance(line_height, dict):
            raise UnsupportedFigmaFeature(node, "invalid line-height representation")
        unit = str(line_height.get("unit", "")).upper()
        if unit != "AUTO":
            value = _number(line_height.get("value"), node, "line height", minimum=0)
            if unit == "PIXELS":
                result["lineHeight"] = value
            elif unit in {"PERCENT", "PERCENTAGE"}:
                result["lineHeight"] = size * value / 100
            else:
                raise UnsupportedFigmaFeature(node, f"line-height unit {unit!r}")
    vertical = font.get("verticalAlignment", "top")
    if vertical not in {"top", None}:
        # A single explicit line box filling the frame has zero extra vertical
        # space to distribute. Taller, wrapped or auto-height text is not a no-op.
        no_extra_space = (vertical == "center" and "\n" not in content and "\r" not in content
                          and "lineHeight" in result and math.isclose(
                              _frame(node)["height"], result["lineHeight"], rel_tol=0, abs_tol=1e-6))
        if not no_extra_space:
            raise UnsupportedFigmaFeature(node, "vertical text alignment")
    if font.get("italic"):
        result["fontStyle"] = "italic"
    decorations = []
    if font.get("underline"):
        decorations.append("underline")
    if font.get("linethrough"):
        decorations.append("line-through")
    if decorations:
        result["textDecoration"] = " ".join(decorations)
    spacing = font.get("letterSpacing")
    if spacing is not None:
        if not isinstance(spacing, dict):
            raise UnsupportedFigmaFeature(node, "invalid letter spacing")
        value = _number(spacing.get("value"), node, "letter spacing")
        unit = str(spacing.get("unit", "")).upper()
        if unit in {"PERCENT", "PERCENTAGE"}:
            value *= size / 100
        elif unit not in {"PIXELS", "PIXEL", "PX"}:
            raise UnsupportedFigmaFeature(node, f"letter-spacing unit {unit!r}")
        result["letterSpacing"] = _px(value)
    # The official serializer truncates its legacy box properties with parseInt.
    # A font shorthand placed last preserves fractional metrics in pixel CSS.
    if size % 1 or result.get("lineHeight", 0) % 1:
        height = _px(result["lineHeight"]) if "lineHeight" in result else "normal"
        for key in ("fontSize", "fontFamily", "fontWeight", "fontStyle", "lineHeight"):
            result.pop(key, None)
        result["font"] = f"{'italic' if font.get('italic') else 'normal'} {weight} {_px(size)}/{height} {family}"
    escaped = html.escape(content, quote=False).replace("{", "&#123;").replace("}", "&#125;")
    # Prettier's HTML formatter otherwise folds a literal newline into a space,
    # before white-space: pre-wrap ever reaches the browser.
    escaped = escaped.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "&#10;").replace("\t", "&#9;")
    if dds:
        result.pop("display", None)
        if "fontFamily" in result and re.fullmatch(r"[\w -]+", family[1:-1]):
            result["fontFamily"] = family[1:-1]
        if "fontWeight" in result:
            result["fontWeight"] = "normal" if weight == 400 else str(weight)
        # DDS's single-line hint also uses the font-size envelope. A deliberately
        # tall line box (at least two em) keeps normal wrapping even when its
        # explicit line-height fills that box. Preserve whitespace separately.
        if ("\n" not in content and (not font_envelope or node["frame"]["height"] < 2 * size)
                and node["frame"]["height"] <= result.get("lineHeight", size) + 1):
            result["whiteSpace"] = "nowrap"
        if result.get("letterSpacing") == "0px":
            result.pop("letterSpacing")
        # The observed DDS single tall-line envelope omits white-space while
        # retaining isolated internal spaces as NBSPs. Require one explicit
        # line box; multiline text and layout-significant whitespace keep the
        # source-preserving break opportunities below. Source mode does not
        # use this empirical font-envelope convention.
        tall_single_line = (font_envelope and " " in content
                            and content == content.strip(" ")
                            and re.search(r"  |[^\S ]", content) is None
                            and "lineHeight" in result
                            and node["frame"]["height"] == result["lineHeight"]
                            and node["frame"]["height"] >= 2 * size)
        unbreakable_spaces = result["whiteSpace"] == "nowrap" or tall_single_line
        if tall_single_line:
            result.pop("whiteSpace")
        # Numeric ASCII spaces survive HTML formatting without turning a
        # normally wrapped whole sentence into an unbreakable word.
        escaped = escaped.replace(" ", "&nbsp;" if unbreakable_spaces else "&#32;")
    else:
        escaped = escaped.replace(" ", "&#32;")
    return escaped, result


def _normalize_dds_properties(node: dict, *, source_nodes: dict[str, dict] | None = None) -> None:
    """Use observed DDS declaration phases without dropping extra styles.

    Columns whose direct source text has moved into inferred groups, or whose
    one source child survives as one output child, acquire width later.
    Final flow children determine the delayed width phase; an attached overlay
    does not become a flow child. Retained singleton content and projected
    dividers can receive their containing-block placement after that phase.
    These phases remain empirical for other source/layout shapes.
    Source IDs only join raw metadata. Names, class names and text values play
    no part in the ordering. Without source metadata keep the legacy ordering
    used by the separate source-border layout mode.
    """
    style = node["props"]["style"]
    radius = style.get("borderRadius")
    if isinstance(radius, str):
        values = radius.split()
        if len(values) == 4:
            if values[1] == values[3]:
                values.pop()
                if values[0] == values[2]:
                    values.pop()
                    if values[0] == values[1]:
                        values.pop()
            style["borderRadius"] = " ".join(values)
    children = node.get("children", [])
    direction = style.get("flexDirection")
    ui_type = node.get("uiType")
    source = (source_nodes or {}).get(node.get("layerId"), {})
    source_children = source.get("layers") or []
    content = (source.get("text") or {}).get("value")
    if (source_nodes is not None and style.get("whiteSpace") == "pre-wrap"
            and isinstance(content, str) and content and not re.search(r"\s", content)):
        # Without whitespace, normal wrapping paints identically. DDS omits
        # this declaration on its multiline tooltip. Preserve explicit spaces,
        # tabs and newlines, and leave the source mode unchanged.
        style.pop("whiteSpace")
    absolute_overlay = source_nodes is not None and style.get("position") == "absolute"
    flow_children = [child for child in children
                     if child.get("props", {}).get("style", {}).get("position") != "absolute"]
    has_overlays = len(flow_children) != len(children)
    adopted_shape = bool(source_nodes is not None and source.get("type") == "shapeLayer"
                         and not source_children and len(flow_children) == 1 and not ui_type and direction == "column")
    grouped_source_text = (any(child.get("type") == "textLayer" for child in source_children)
                           and not any(child.get("type") == "lanhutext" for child in flow_children))
    projected_divider = bool(source_nodes is not None and has_overlays and any(
        child.get("type") == "shapeLayer" and _dds_rect_envelope(child, hairline=True)
        for child in source_children))
    retained_single_flow = len(flow_children) == 1 and (len(source_children) == 1 or has_overlays)
    # A flattened source text matrix receives its final rows before its width
    # and containing-block placement. Require actual synthetic text rows, not
    # merely one source child expanding into arbitrary output children.
    def source_text_ids(item: dict) -> set[str]:
        if item.get("type") == "textLayer":
            return {item.get("id")}
        return {identity for child in item.get("layers") or [] for identity in source_text_ids(child)}

    matrix_text_ids = source_text_ids(source_children[0]) if len(source_children) == 1 else set()
    regrouped_text_rows = bool(source_nodes is not None and len(source_children) == 1
        and len(flow_children) > 1 and all(
            child.get("layerId") not in source_nodes and not child.get("uiType")
            and child.get("props", {}).get("style", {}).get("flexDirection") == "row"
            and len(child.get("children", [])) >= 2
            and all(leaf.get("type") == "lanhutext" and leaf.get("layerId") in matrix_text_ids
                    for leaf in child["children"])
            for child in flow_children))
    delayed_width = adopted_shape or bool(source_nodes is not None and source and flow_children
                         and node.get("type") == "lanhublock" and not ui_type and direction == "column"
                         and (retained_single_flow or projected_divider or regrouped_text_rows
                              or (not absolute_overlay and grouped_source_text)))
    late_position = delayed_width and not adopted_shape
    dimensions = ["height"] if delayed_width else ["width", "height"]
    if (source_nodes is None and node.get("type") == "lanhublock" and not ui_type and children
            and all(child.get("type") == "lanhutext" for child in children)
            and "backgroundColor" in style and direction == "column"):
        dimensions.reverse()
    placement = ["borderRadius", "position"] if source_nodes is not None else ["position", "borderRadius"]
    if adopted_shape or late_position:
        placement = ["borderRadius"]
    coordinates = [] if adopted_shape or late_position else ["left", "top"]
    ordered_keys = ["boxShadow", "backgroundColor", "background", *placement, *coordinates, *dimensions,
                    "overflow", "border", "overflowWrap", "color", "fontSize", "fontFamily", "fontWeight",
                    "textAlign", "whiteSpace", "lineHeight"]
    margins = [key for key in style if key.startswith("margin")]
    if source_nodes is None:
        ordered_keys += ["display", "flexDirection", "justifyContent"]
        ordered_keys += [key for key in style if key not in ordered_keys and key not in margins] + margins
    else:
        # A single-axis placement is stored before the container's flex layout;
        # the margin shorthand is assembled after that layout has finished.
        ordered_keys += [key for key in margins if key != "margin"]
        if delayed_width and len(flow_children) > 1:
            ordered_keys.append("width")
            if late_position:
                ordered_keys += ["position", "left", "top"]
        ordinary_row = not ui_type and direction == "row" and len(children) >= 2
        semantic_image_row = ui_type == "ImageText" and direction == "row"
        ordered_keys += ["flexDirection", "display"] if ordinary_row or semantic_image_row else ["display", "flexDirection"]
        ordered_keys.append("justifyContent")
        if delayed_width and len(flow_children) == 1:
            ordered_keys.append("width")
            if late_position:
                ordered_keys += ["position", "left", "top"]
        if adopted_shape:
            # A source paint leaf gains a container layout before it receives
            # its new overlay placement (e.g. a dialog's backdrop rectangle).
            ordered_keys += ["position", "left", "top"]
        ordered_keys += [key for key in style if key not in ordered_keys and key != "margin"] + ["margin"]
    node["props"]["style"] = {key: style[key] for key in ordered_keys if key in style}
    for child in node["children"]:
        _normalize_dds_properties(child, source_nodes=source_nodes)


def figma_to_dds_schema(data: dict, *, asset_loader: Callable[[str], bytes] | None = None,
                        layout: str = "inferred", border_layout: str = "dds") -> dict:
    """Return DDS inferred from raw Figma data, or fail on missing visual data.

    Input is the Lanhu Figma plugin's meta/assets/artboard format, not the Figma
    REST API document format. Exported layer frames are in artboard coordinates;
    the artboard's own frame has document coordinates and is normalized to 0,0.
    The input is never changed. ``asset_loader`` supplies original PNG bytes for
    image composition; it must not supply already merged official oracle images.
    Without it, image layers remain separate. ``layout='absolute'`` preserves
    source fractions, hierarchy and per-edge borders for geometry inspection.
    Inferred layout defaults to the official DDS border-origin convention.
    ``border_layout='source'`` instead uses conservative paint-order grouping
    and compensates CSS border insets, preserving source positions and paint.
    DDS mode may project a validated quarter-turned square envelope or zero-
    corner hairline strip without its vector contour; each carries a warning.
    Its narrowly qualified zero-width/empty-shape image policies also warn
    when discarding exported pixels, and never apply to source/absolute modes.
    """
    if layout not in {"inferred", "absolute"}:
        raise ValueError("layout must be 'inferred' or 'absolute'")
    if border_layout not in {"dds", "source"}:
        raise ValueError("border_layout must be 'dds' or 'source'")
    inferred = layout == "inferred"
    if not isinstance(data, dict) or not isinstance(data.get("artboard"), dict):
        raise UnsupportedFigmaFeature({}, "expected Lanhu Figma meta/assets/artboard JSON")
    meta = data.get("meta") or {}
    origin = data["artboard"].get("origin") or (meta.get("host") or {}).get("name")
    if origin != "figma":
        raise UnsupportedFigmaFeature(data["artboard"], f"source origin {origin!r} is not figma")
    counter = 0
    omitted_warnings = []

    def convert(node: dict, parent_frame: dict | None, parent_borders: dict, sibling_index: int) -> dict | None:
        warning_count = len(omitted_warnings)
        try:
            return convert_node(node, parent_frame, parent_borders, sibling_index)
        except UnsupportedFigmaFeature as error:
            # A fallback slice may include pixels omitted by an abandoned
            # structural attempt; only report omissions in the returned tree.
            del omitted_warnings[warning_count:]
            # Prefer structural DDS children only when the complete subtree can
            # be represented. A normal slice still safely supplies unsupported
            # parent effects or siblings baked into that image.
            if (isinstance(node, dict) and parent_frame is not None and node.get("hasExportImage")
                    and not node.get("hasExportDDSImage") and not node.get("isMask")
                    and _has_dds_descendant(node)):
                fallback = convert_node(node, parent_frame, parent_borders, sibling_index, prefer_dds_descendants=False)
                if fallback is not None:
                    fallback["conversionWarnings"] = [{"layerId": str(node.get("id")),
                                                        "reason": "Used complete ordinary slice: " + error.feature}]
                return fallback
            raise

    def convert_node(node: dict, parent_frame: dict | None, parent_borders: dict, sibling_index: int,
                     *, prefer_dds_descendants: bool = True) -> dict | None:
        nonlocal counter
        if not isinstance(node, dict):
            raise UnsupportedFigmaFeature({}, "non-object layer")
        if node.get("visible", True) is False or _opacity(node) == 0:
            return None
        root = parent_frame is None
        frame = _frame(node, root=root)
        if node.get("isMask"):
            raise UnsupportedFigmaFeature(node, "mask affecting sibling layers")
        resource = _export_url(node, prefer_dds_descendants=prefer_dds_descendants)
        empty_shape_resource = None
        if (inferred and border_layout == "dds" and not root and resource
                and node.get("hasExportDDSImage") and not node.get("hasExportImage")):
            if frame["width"] == 0:
                omitted_warnings.append({"code": "dds_zero_width_image_omitted", "layerId": str(node.get("id")),
                    "reason": "DDS compatibility omits a zero-width exported image; source image pixels are not inspected or considered transparent",
                    "sourceFrame": deepcopy(node["frame"]), "sourceImageUrl": resource})
                return None
            if _dds_empty_shape(node, zero_height=True):
                omitted_warnings.append({"code": "dds_zero_height_shape_omitted", "layerId": str(node.get("id")),
                    "reason": "DDS compatibility omits an exported zero-height empty shape envelope; this does not imply that the source image is transparent",
                    "sourceFrame": deepcopy(node["frame"]), "sourceImageUrl": resource})
                return None
            if _dds_empty_shape(node):
                empty_shape_resource, resource = resource, None
        if resource and not root:
            frame = _export_frame(node, frame)
        if inferred:
            frame = {key: math.ceil(value) for key, value in frame.items()}
        kind = node.get("type")
        if not resource and kind not in _CONTAINERS | {"shapeLayer", "textLayer"}:
            raise UnsupportedFigmaFeature(node, f"layer type {kind!r}")
        rect_envelope = rotated_hairline = half_turn_rect = transparent_rect = False
        if not resource and kind == "shapeLayer":
            paths = node.get("paths") or []
            # Establish the geometric DDS projection independently of the old
            # rectangle naming hint, so renaming cannot bypass its safeguards.
            rect_envelope = inferred and border_layout == "dds" and _dds_rect_envelope(node)
            rotated_hairline = (inferred and border_layout == "dds" and not rect_envelope
                                and _dds_rect_envelope(node, hairline=True))
            half_turn_rect = inferred and border_layout == "dds" and _dds_half_turn_rect(node)
            transparent_rect = inferred and border_layout == "dds" and _dds_transparent_rect(node)
            explicit_rectangle = node.get("shapeType") in {"rect", "rectangle"} or bool(_RECTANGLE_NAME.match(node.get("name", "")))
            if not (rect_envelope or rotated_hairline or half_turn_rect or transparent_rect or empty_shape_resource) and (not explicit_rectangle or len(paths) != 1 or paths[0].get("type") != "rect"):
                raise UnsupportedFigmaFeature(node, "missing vector geometry or exported image")
        counter += 1
        class_name = "page" if root else f"figma_{counter}"
        left = 0 if root else frame["left"] - parent_frame["left"] - parent_borders["left"]
        top = 0 if root else frame["top"] - parent_frame["top"] - parent_borders["top"]
        style = ({"position": "relative" if root else "absolute"} if inferred else
                 {"position": "relative" if root else "absolute", "zIndex": sibling_index,
                  "boxSizing": "border-box"})
        # Preserve fractions through the official serializer without modifying
        # the official generator. These overrides are for fixed-pixel output.
        for physical, logical, value in (("left", "insetInlineStart", left), ("top", "insetBlockStart", top),
                                         ("width", "inlineSize", frame["width"]), ("height", "blockSize", frame["height"])):
            style[logical if value % 1 else physical] = _px(value) if value % 1 else value
        dds_type = "lanhupage" if root else "lanhuimage" if resource else "lanhutext" if kind == "textLayer" else "lanhublock"
        result = {"id": class_name, "eleName": str(node.get("name", class_name)), "layerId": str(node.get("id", class_name)),
                  "type": dds_type, "componentName": dds_type, "rowDims": deepcopy(frame),
                  "data": {"value": ""}, "uiType": "", "uiTypeProb": {}, "alignJustify": {},
                  "props": {"className": class_name, "style": style}, "children": []}
        borders = dict.fromkeys(("top", "right", "bottom", "left"), 0)
        if resource:
            if root:
                raise UnsupportedFigmaFeature(node, "artboard-only image export is not a structural schema")
            # A Figma export already includes its own paint, rotation, opacity,
            # clipping and descendants. Applying those effects again doubles them.
            result["data"]["value"] = resource
            result["props"]["src"] = resource
            result["mergeEligible"] = bool(node.get("hasExportDDSImage"))
            if node.get("hasExportImage"):
                result["sourceHasOrdinaryImage"] = True
            if not inferred:
                style["display"] = "block"
        else:
            if empty_shape_resource:
                result["ddsEmptyShapeProjection"] = True
                result["conversionWarnings"] = [{"code": "dds_empty_shape_projection", "layerId": result["layerId"],
                    "reason": "DDS compatibility retains an empty rounded rectangle and omits the exported image's pixels; this does not imply the image is transparent or restore its vector contour",
                    "sourceFrame": deepcopy(node["frame"]), "sourceImageUrl": empty_shape_resource}]
            flips = _axis_flips(node)
            baked_wrapper = not root and flips is not None and any(flips) and _raster_only_wrapper(node)
            if (not baked_wrapper and not root and inferred and border_layout == "dds"
                    and _verified_swapped_axes(node)):
                baked_wrapper = _raster_only_wrapper(node, allow_swapped_axes=True)
            projected_group = not root and inferred and border_layout == "dds" and _dds_projected_group(node)
            if projected_group:
                baked_wrapper = True
                omitted_warnings.append({"code": "dds_projected_group_transform", "layerId": result["layerId"],
                    "reason": "DDS compatibility retains validated child envelopes and baked images while omitting the group transform; the original vector contours and rotations are not restored",
                    "sourceRotation": node["rotation"], "sourceFrame": deepcopy(node["frame"]),
                    "sourceRealFrame": deepcopy(node["realFrame"])})
            visual_node = node
            if rect_envelope or rotated_hairline or half_turn_rect:
                # Render the declared raw rectangle, intentionally retaining
                # its anchor instead of claiming to recover vector geometry.
                visual_node = {**node, "rotation": 0, "transform": [[1, 0, 0], [0, 1, 0]]}
                # Hairlines retain their source parent; the square projection's
                # separate marker permits its guarded DDS containment rewrite.
                marker = "ddsHalfTurnRectProjection" if half_turn_rect else "ddsRotatedHairlineProjection" if rotated_hairline else "ddsRectEnvelopeProjection"
                code = "dds_half_turn_rect_projection" if half_turn_rect else "dds_rotated_hairline_projection" if rotated_hairline else "dds_rect_envelope_projection"
                result[marker] = True
                result["conversionWarnings"] = [{"code": code, "layerId": result["layerId"],
                    "reason": "DDS compatibility projects the raw rectangle envelope; the original vector contour and rotation are not restored",
                    "sourceRotation": node["rotation"], "sourceFrame": deepcopy(node["frame"]),
                    "sourceRealFrame": deepcopy(node["realFrame"])}]
                if half_turn_rect:
                    # This DDS projection serializes shadow pixel terms as
                    # integers; keep fractional border width verbatim below.
                    source_style = deepcopy(node["style"])
                    for shadow in _active(source_style.get("shadows"), node, "shadows"):
                        for key in ("x", "y", "blur", "spread"):
                            shadow[key] = math.trunc(_number(shadow.get(key), node, f"shadows.{key}"))
                    visual_node = {**visual_node, "style": source_style}
            visual, borders = _visual_style(visual_node, text=kind == "textLayer", dds=inferred,
                                            baked_wrapper=baked_wrapper,
                                            integer_corners=inferred and border_layout == "dds")
            style.update(visual)
            if transparent_rect:
                # Retain the source's zero-alpha color explicitly: _active
                # ordinarily omits zero-opacity paints as a rendering no-op.
                fill = node["style"]["fills"][0]
                style["backgroundColor"] = _color(fill["color"], node, fill.get("opacity", 1))
                result["ddsTransparentRectProjection"] = True
                result["conversionWarnings"] = [{"code": "dds_transparent_rect_projection", "layerId": result["layerId"],
                    "reason": "DDS compatibility retains the transparent rounded rectangle envelope for layout; the original vector contour is not restored",
                    "sourceFrame": deepcopy(node["frame"]), "sourceRealFrame": deepcopy(node["realFrame"])}]
            if half_turn_rect:
                border = _active(node["style"].get("borders"), node, "borders")[0]
                color = _color(border.get("color"), node, border.get("opacity", 1))
                style["border"] = f"{border['width']}px solid {color}"
            if inferred and any(borders.values()):
                border = _active((node.get("style") or {}).get("borders"), node, "borders")[0]
                sides = border.get("widths") or {}
                per_edge = bool(any(sides.values()) and len({sides.get(side, 0) for side in borders}) > 1)
                if per_edge:
                    result["conversionWarnings"] = [{"layerId": result["layerId"],
                        "reason": "DDS compatibility expands a per-edge Figma border to the uniform stroke width"}]
                if border_layout == "source":
                    result["layoutInsets"] = deepcopy(borders)
                elif node.get("layers"):
                    result["ddsBorderOffsets"] = True
                    result.setdefault("conversionWarnings", []).append({"layerId": result["layerId"],
                        "reason": "DDS compatibility retains outer-frame child offsets; CSS borders may shift descendants"})
            if kind == "textLayer":
                content, text_style = _text_style(node, dds=inferred,
                                                 font_envelope=inferred and border_layout == "dds")
                style.update(text_style)
                result["data"]["value"] = content if inferred else node["text"]["value"]
                result["props"]["text"] = content
                result["props"]["lines"] = node["text"]["value"].count("\n") + 1
            else:
                children = node.get("layers") or []
                if not isinstance(children, list):
                    raise UnsupportedFigmaFeature(node, "invalid children list")
                for index, child in enumerate(children):
                    converted = convert(child, frame, borders, index)
                    if converted is not None:
                        result["children"].append(converted)
        result["style"] = deepcopy(style)
        return result

    root = convert(data["artboard"], None, {}, 0)
    if root is None:
        raise UnsupportedFigmaFeature(data["artboard"], "invisible artboard")
    if inferred:
        from .figma_dds_layout import infer_dds_layout
        from .figma_naming import assign_class_names
        from .figma_dds_semantics import refine_dds_semantics
        composer = None
        if asset_loader is not None:
            from .figma_images import compose_image_nodes
            composer = lambda nodes: compose_image_nodes(nodes, asset_loader)
        if border_layout == "source":
            from .figma_layout import infer_layout
            root = infer_layout(root, image_composer=composer)
        else:
            source_nodes = {}
            def index_source(node: dict) -> None:
                source_nodes[str(node.get("id", ""))] = node
                for child in node.get("layers") or []:
                    index_source(child)
            index_source(data["artboard"])
            root = refine_dds_semantics(
                infer_dds_layout(root, image_composer=composer, source_nodes=source_nodes))
        root = assign_class_names(root)
        root["props"]["style"]["overflow"] = "hidden"
        _normalize_dds_properties(root, source_nodes=source_nodes if border_layout == "dds" else None)
        root["style"] = deepcopy(root["props"]["style"])
    root["designType"] = "mobile" if inferred else "fixed"
    root["thirdpartyComponent"] = "none"
    if omitted_warnings:
        root.setdefault("conversionWarnings", []).extend(omitted_warnings)
    return root
