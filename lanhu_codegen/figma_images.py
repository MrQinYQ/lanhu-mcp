"""Compose already selected, one-times DDS PNG exports before DDS layout.

This module does not choose merge groups or fetch resources. Source rowDims are
in artboard coordinates. The resulting style coordinates use that same basis;
the caller must derive local/flex positioning when it builds the layout tree.
"""

from __future__ import annotations

import base64
from copy import deepcopy
from io import BytesIO
import math
from typing import Callable, Sequence

from PIL import Image, UnidentifiedImageError


class FigmaImageCompositionError(ValueError):
    """A selected image group cannot be composed without guessing its pixels."""


_GEOMETRY = ("left", "top", "width", "height")
_LOGICAL_GEOMETRY = ("insetInlineStart", "insetBlockStart", "inlineSize", "blockSize")


def _error(layer_id: str, message: str) -> FigmaImageCompositionError:
    return FigmaImageCompositionError(f"Cannot compose Figma image layer {layer_id!r}: {message}")


def _raster_bounds(node: dict) -> dict[str, int]:
    layer_id = str(node.get("layerId", "<unknown>"))
    dims = node.get("rowDims")
    if not isinstance(dims, dict):
        raise _error(layer_id, "missing rowDims")
    result = {}
    for key in _GEOMETRY:
        value = dims.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise _error(layer_id, f"rowDims.{key} must be a finite number")
        if key in {"width", "height"} and value <= 0:
            raise _error(layer_id, f"rowDims.{key} must be positive")
        result[key] = math.ceil(value)
    return result


def _load_png(node: dict, bounds: dict, load_asset: Callable[[str], bytes]) -> tuple[str, Image.Image]:
    layer_id = str(node.get("layerId", "<unknown>"))
    props = node.get("props")
    src = props.get("src") if isinstance(props, dict) else None
    if not isinstance(src, str) or not src:
        raise _error(layer_id, "missing props.src")
    try:
        content = load_asset(src)
    except Exception as exc:
        raise _error(layer_id, f"resource loader failed ({type(exc).__name__})") from exc
    if not isinstance(content, bytes) or not content:
        raise _error(layer_id, "resource loader must return nonempty bytes")
    try:
        with Image.open(BytesIO(content)) as source:
            if source.format != "PNG":
                raise _error(layer_id, f"expected a DDS PNG, got {source.format or 'unknown'}")
            if getattr(source, "n_frames", 1) != 1:
                raise _error(layer_id, "animated PNGs are not DDS raster snapshots")
            size = (bounds["width"], bounds["height"])
            if source.size != size:
                raise _error(layer_id, f"PNG size {source.size} does not match ceil(rowDims) {size}; resampling is not inferred")
            source.load()
            image = source.convert("RGBA")
    except FigmaImageCompositionError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise _error(layer_id, f"invalid PNG resource ({type(exc).__name__})") from exc
    return src, image


def compose_image_nodes(nodes: Sequence[dict], load_asset: Callable[[str], bytes]) -> dict:
    """Return one DDS image for an ordered group of already rasterized nodes.

    Images are drawn in input order with standard source-over alpha composition.
    Every source coordinate and dimension is independently rounded upward, then
    their union defines the output canvas. PNG dimensions must agree with those
    rounded dimensions: this function neither scales nor crops a source image.

    The last node supplies identity/metadata. ``sourceLayerIds`` and
    ``imageComposition`` retain source identity, URLs, original rowDims, rounded
    raster bounds, and placement offsets for diagnostics. The inputs are never
    changed, and all resource access goes through the supplied loader.
    """
    if not isinstance(nodes, (list, tuple)) or not nodes:
        raise FigmaImageCompositionError("Cannot compose an empty image group")
    if not callable(load_asset):
        raise FigmaImageCompositionError("Image resource loader must be callable")
    bounds = []
    for node in nodes:
        if not isinstance(node, dict) or node.get("type") != "lanhuimage":
            raise FigmaImageCompositionError("Every composed node must have type 'lanhuimage'")
        if node.get("children"):
            raise _error(str(node.get("layerId", "<unknown>")), "image node has children; resolve rasterization before composition")
        bounds.append(_raster_bounds(node))
    left = min(item["left"] for item in bounds)
    top = min(item["top"] for item in bounds)
    right = max(item["left"] + item["width"] for item in bounds)
    bottom = max(item["top"] + item["height"] for item in bounds)
    union = {"left": left, "top": top, "width": right - left, "height": bottom - top}
    if Image.MAX_IMAGE_PIXELS and union["width"] * union["height"] > Image.MAX_IMAGE_PIXELS:
        raise FigmaImageCompositionError("Composition dimensions exceed Pillow's image pixel limit")
    try:
        canvas = Image.new("RGBA", (union["width"], union["height"]))
    except (ValueError, OverflowError, MemoryError) as exc:
        raise FigmaImageCompositionError("Composition canvas dimensions cannot be allocated") from exc
    sources = []
    for node, item in zip(nodes, bounds):
        src, image = _load_png(node, item, load_asset)
        offset = {"left": item["left"] - left, "top": item["top"] - top}
        canvas.alpha_composite(image, (offset["left"], offset["top"]))
        sources.append({
            "layerId": str(node.get("layerId", "<unknown>")),
            "src": src,
            "rowDims": deepcopy(node["rowDims"]),
            "rasterBounds": deepcopy(item),
            "offset": offset,
            "pixelSize": {"width": image.width, "height": image.height},
        })
    stream = BytesIO()
    canvas.save(stream, format="PNG")
    uri = "data:image/png;base64," + base64.b64encode(stream.getvalue()).decode("ascii")
    result = deepcopy(nodes[-1])
    result["rowDims"] = union
    result["children"] = []
    result.setdefault("data", {})["value"] = uri
    result.setdefault("props", {})["src"] = uri
    for style in (result.setdefault("style", {}), result["props"].setdefault("style", {})):
        for key in _LOGICAL_GEOMETRY:
            style.pop(key, None)
        style.update(union)
    result["sourceLayerIds"] = [source["layerId"] for source in sources]
    result["imageComposition"] = {
        "algorithm": "rgba-source-over",
        "coordinateRounding": "ceil",
        "coordinateSpace": "artboard",
        "format": "image/png",
        "sources": sources,
    }
    return result
