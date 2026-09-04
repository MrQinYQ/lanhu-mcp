"""Source-resource reuse and ancestor-paint policy for DDS composition.

The paired exports distinguish globally unique raster fragments from reused
image resources. Identical adjacent icons are composed when their source URLs
occur once, but remain independent when the same URLs are used elsewhere in
the design. Local dimensions, PNG pixels and source wrapper geometry alone
cannot distinguish those observed cases.

The source tree also retains later-painted ancestor siblings that flattening
can move outside a merge's local sibling list. A proposal beneath such paint
stays separate when the paint intersects its union or has unknown bounds.

These are empirical DDS compatibility rules, not the upstream algorithm. They
only veto otherwise eligible merges; local geometry and paint-order checks
remain in ``figma_layout._merge_images``. Resource identity means the exact
source URL, not the layer ID, name, text or an oracle-provided grouping.
"""

from collections import Counter
from collections.abc import Callable, Mapping, Sequence

from .figma_layout import _overlap, _paint_bounds, _union


def build_dds_image_merge_policy(root: Mapping) -> Callable[[Sequence[Mapping]], bool]:
    """Capture source usage and paint scopes before layout rewrites the tree.

    ``root`` is the normalized DDS tree, after source exports have replaced
    their vector descendants. Counting this tree avoids counting nested source
    objects that will never render. Counts, tree paths and painted rectangles
    are frozen so flattening, reparenting or an earlier merge cannot change a
    later decision. No resources are loaded and no input objects are changed.

    A run involving any reused or unknown source stays separate. We do not
    guess which subset of a rejected run the official service might merge.
    """
    counts: Counter[str] = Counter()
    paths: dict[str, tuple[int, ...]] = {}
    child_bounds: dict[tuple[int, ...], tuple[dict | None, ...]] = {}

    def bounds(node: Mapping) -> dict | None:
        try:
            return _paint_bounds(node)
        except (TypeError, ValueError):
            # Invalid or missing geometry cannot establish non-intersection.
            return None

    def visit(node: Mapping, path: tuple[int, ...] = ()) -> None:
        if node.get("type") == "lanhuimage":
            src = (node.get("props") or {}).get("src")
            if isinstance(src, str) and src:
                counts[src] += 1
                paths[src] = path
        children = node.get("children", [])
        child_bounds[path] = tuple(bounds(child) for child in children)
        for index, child in enumerate(children):
            visit(child, (*path, index))

    visit(root)

    def accept_merge(nodes: Sequence[Mapping]) -> bool:
        if len(nodes) < 2:
            return False
        sources = []
        for node in nodes:
            if node.get("type") != "lanhuimage":
                return False
            src = (node.get("props") or {}).get("src")
            if not isinstance(src, str) or not src or counts[src] != 1:
                return False
            sources.append(src)
        # A caller cannot repeat the same unique node inside one proposal.
        if len(sources) != len(set(sources)):
            return False
        common_path = []
        for indices in zip(*(paths[src] for src in sources)):
            if len(set(indices)) != 1:
                break
            common_path.append(indices[0])
        union = _union(list(nodes))
        for depth, branch_index in enumerate(common_path):
            parent_path = tuple(common_path[:depth])
            # Only scopes above the proposal's original common parent are
            # checked here. The local merger checks its remaining siblings;
            # another proposal member must not become its own occluder.
            for paint in child_bounds[parent_path][branch_index + 1:]:
                if paint is None or _overlap(union, paint):
                    return False
        return True

    return accept_merge
